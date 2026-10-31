"""Prompts & Datasets library: a user's own reusable test prompts plus grading.
Tenancy-scoped. Used to run custom-prompt evaluations against a target."""
import csv
import io
import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, select

from ..auth import company_scope, current_user, require_role
from ..db import get_session
from ..models import PromptSet, Role, User, utcnow
from ..schemas import PromptSetIn

router = APIRouter(prefix="/api/prompts", tags=["prompts"])

MAX_UPLOAD = 10 * 1024 * 1024  # 10 MB of prompts is plenty
MAX_PROMPTS = 5000


def _accessible(ps: PromptSet, user: User) -> bool:
    scope = company_scope(user)
    return scope is None or ps.company_id == scope


def _get_owned(set_id: int, user: User, session: Session) -> PromptSet:
    ps = session.get(PromptSet, set_id)
    if not ps or not _accessible(ps, user):
        raise HTTPException(404, "No such prompt set")
    return ps


def _out(ps: PromptSet, full: bool = False) -> dict:
    data = {
        "id": ps.id, "name": ps.name, "description": ps.description,
        "company_id": ps.company_id, "count": len(ps.prompts or []),
        "grading": ps.grading or {}, "created_at": ps.created_at, "updated_at": ps.updated_at,
    }
    if full:
        data["prompts"] = ps.prompts or []
    return data


@router.get("")
def list_sets(user: User = Depends(current_user), session: Session = Depends(get_session)):
    scope = company_scope(user)
    q = select(PromptSet).order_by(PromptSet.updated_at.desc())
    if scope is not None:
        q = q.where(PromptSet.company_id == scope)
    return [_out(ps) for ps in session.exec(q).all()]


@router.post("", status_code=201)
def create_set(body: PromptSetIn, user: User = Depends(require_role(Role.analyst)),
               session: Session = Depends(get_session)):
    prompts = _clean_prompts(body.prompts)
    ps = PromptSet(company_id=user.company_id, name=body.name, description=body.description,
                   prompts=prompts, grading=body.grading.model_dump(), created_by=user.id)
    session.add(ps)
    session.commit()
    session.refresh(ps)
    return _out(ps, full=True)


@router.get("/attack-categories")
def attack_categories(user: User = Depends(require_role(Role.analyst))):
    """Attack goals for the AI generator + the model it uses (XYBERAH_GRADER).
    Registered before /{set_id} so the literal path is not captured as an id."""
    from ..attackgen import CATEGORIES
    from ..config import get_settings
    return {"model": get_settings().grader,
            "categories": [{"id": k, "desc": v} for k, v in CATEGORIES.items()]}


@router.get("/plugin-sources")
def plugin_sources(user: User = Depends(require_role(Role.analyst))):
    """Importable prompt sources from the installed scanners (garak probes, PyRIT
    seed datasets). Read-only — importing copies the prompts into the user's set."""
    from .. import plugin_library
    return plugin_library.list_sources()


class ImportPluginIn(BaseModel):
    source_id: str


@router.post("/import-plugin")
def import_plugin(body: ImportPluginIn, user: User = Depends(require_role(Role.analyst))):
    from .. import plugin_library
    try:
        res = plugin_library.get_prompts(body.source_id)
    except Exception as exc:  # e.g. a dataset pack fetch failing (offline)
        raise HTTPException(502, f"Could not fetch that source: {str(exc)[:200]}")
    if not res:
        raise HTTPException(404, "No such plugin source")
    return res


@router.get("/{set_id}")
def get_set(set_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    return _out(_get_owned(set_id, user, session), full=True)


@router.put("/{set_id}")
def update_set(set_id: int, body: PromptSetIn, user: User = Depends(require_role(Role.analyst)),
               session: Session = Depends(get_session)):
    ps = _get_owned(set_id, user, session)
    ps.name = body.name
    ps.description = body.description
    ps.prompts = _clean_prompts(body.prompts)
    ps.grading = body.grading.model_dump()
    ps.updated_at = utcnow()
    session.add(ps)
    session.commit()
    session.refresh(ps)
    return _out(ps, full=True)


@router.delete("/{set_id}")
def delete_set(set_id: int, user: User = Depends(require_role(Role.analyst)),
               session: Session = Depends(get_session)):
    ps = _get_owned(set_id, user, session)
    session.delete(ps)
    session.commit()
    return {"ok": True}


class GenerateIn(BaseModel):
    purpose: str = ""
    category: str = "prompt-injection"
    count: int = 10


@router.post("/generate")
def generate_prompts(body: GenerateIn, user: User = Depends(require_role(Role.analyst))):
    from ..attackgen import generate
    return generate(body.purpose, body.category, body.count)


@router.post("/parse-upload")
async def parse_upload(file: UploadFile = File(...), user: User = Depends(require_role(Role.analyst))):
    """Parse an uploaded dataset into a list of prompt strings.
    Supports .txt (one prompt per line), .json (array of strings or objects with a
    prompt/text/input field, or {"prompts": [...]}), and .csv (a 'prompt' column,
    else the first column; a header row is auto-detected and skipped)."""
    raw = await file.read()
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "File too large (max 10 MB)")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")
    name = (file.filename or "").lower()
    from .. import traffic

    if name.endswith((".jsonl", ".ndjson")):
        prompts = traffic.extract_jsonl(text)
    elif name.endswith(".json"):
        prompts = _parse_json_any(text, traffic)
    elif name.endswith((".csv", ".tsv")):
        prompts = _from_csv(text, delimiter="\t" if name.endswith(".tsv") else ",")
    else:
        # content-sniff: OTLP/JSON, JSONL, else line-per-prompt
        prompts = None
        stripped = text.lstrip()
        if stripped[:1] == "{" and '"resourceSpans"' in text:
            prompts = traffic.extract_otlp(json.loads(text))
        elif stripped[:1] in "[{":
            try:
                prompts = _parse_json_any(text, traffic)
            except Exception:
                prompts = None
        elif "\n" in text and stripped[:1] in "{[":
            prompts = traffic.extract_jsonl(text)
        if prompts is None:
            prompts = [ln for ln in (l.strip() for l in text.splitlines()) if ln]

    prompts = traffic.dedupe(_clean_prompts(prompts))
    if not prompts:
        raise HTTPException(422, "No prompts found in that file")
    return {"prompts": prompts, "count": len(prompts)}


def _parse_json_any(text: str, traffic) -> list[str]:
    """A .json upload: OTLP trace, array of records/strings, or {prompts:[...]}."""
    data = json.loads(text)
    if isinstance(data, dict) and "resourceSpans" in data:
        return traffic.extract_otlp(data)
    if isinstance(data, dict):
        data = data.get("prompts") or data.get("tests") or data.get("data") or [data]
    out: list[str] = []
    for item in data if isinstance(data, list) else []:
        out += traffic.extract_record(item)
    return out or _from_json(text)


# --------------------------------------------------------------------------- #
def _clean_prompts(items) -> list[str]:
    out = []
    for p in items or []:
        s = str(p).strip()
        if s:
            out.append(s[:20000])
        if len(out) >= MAX_PROMPTS:
            break
    return out


def _from_json(text: str) -> list[str]:
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("prompts") or data.get("tests") or data.get("data") or []
    out = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            for k in ("prompt", "text", "input", "query", "question", "message", "vars"):
                v = item.get(k)
                if isinstance(v, dict):  # e.g. promptfoo {"vars": {"prompt": ...}}
                    v = v.get("prompt") or v.get("query") or v.get("input")
                if isinstance(v, str) and v.strip():
                    out.append(v)
                    break
    return out


def _from_csv(text: str, delimiter: str = ",") -> list[str]:
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        return []
    header = [h.strip().lower() for h in rows[0]]
    col = 0
    start = 0
    if "prompt" in header:
        col = header.index("prompt")
        start = 1
    elif any(h in header for h in ("text", "input", "query", "question", "message")):
        for cand in ("text", "input", "query", "question", "message"):
            if cand in header:
                col = header.index(cand)
                break
        start = 1
    else:
        # No recognizable header; if the first cell looks like a label, skip it
        first = (rows[0][0] if rows[0] else "").strip().lower()
        if first in ("prompt", "prompts", "text", "input"):
            start = 1
    out = []
    for r in rows[start:]:
        if col < len(r) and r[col].strip():
            out.append(r[col])
    return out
