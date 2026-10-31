"""Signing, attack-pack parsing, aggregation, and auto-migration idempotency."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import inspect
from sqlmodel import Session, SQLModel, create_engine, select

from app import sign
from app.attackgen import _extract
from app.db import _add_missing_columns, engine
from app.governance import budget_status, retention_sweep
from app.models import Campaign, Company, Finding
from app.reports.aggregate import summarize


def test_sign_verify_and_tamper():
    d = sign.content_hash({"a": 1, "b": [2, 3]})
    sg = sign.sign(d)
    assert sign.verify(d, sg)
    assert not sign.verify(d, sg[:-1] + ("0" if sg[-1] != "0" else "1"))


def test_attackgen_extract_variants():
    assert _extract('["a", "b"]') == ["a", "b"]
    assert _extract('```json\n["x", "y"]\n```') == ["x", "y"]
    assert _extract("prose then\n[\"p1\", \"p2\"]") == ["p1", "p2"]
    assert _extract("1. one\n2. two\n- three") == ["one", "two", "three"]


def test_summarize_counts():
    findings = [
        {"tool": "custom", "category": "c", "plugin": "p", "severity": "high", "passed": False,
         "score": 0.0, "extra": {"cost": 0.1, "tokens": 10}},
        {"tool": "custom", "category": "c", "plugin": "p", "severity": "low", "passed": True,
         "score": 1.0, "extra": {}},
    ]
    s = summarize(findings)
    assert s["total"] == 2 and s["failed"] == 1
    assert s["by_severity"]["high"] == 1
    assert 0 <= s["risk_score"] <= 100


def test_migration_idempotent():
    # Running the migration twice must not raise.
    _add_missing_columns()
    _add_missing_columns()
    cols = {c["name"] for c in inspect(engine).get_columns("company")}
    assert {"redact_findings", "retention_days", "monthly_cost_budget"} <= cols


def test_recover_interrupted_marks_failed():
    from app.orchestrator import runner
    with Session(engine) as s:
        c = Company(name="RecCo", slug="recco")
        s.add(c); s.commit(); s.refresh(c)
        camp = Campaign(company_id=c.id, name="stuck", created_by=1, target={}, tools={}, status="running")
        s.add(camp); s.commit(); s.refresh(camp)
        cid = camp.id
    assert runner.recover_interrupted() >= 1
    with Session(engine) as s:
        c = s.get(Campaign, cid)
        assert c.status == "failed"
        assert "restart" in c.error.lower()


def test_budget_and_retention_in_memory():
    mem = create_engine("sqlite://")
    SQLModel.metadata.create_all(mem)
    with Session(mem) as s:
        co = Company(name="T", slug="t", monthly_cost_budget=1.0, monthly_token_budget=100, retention_days=1)
        s.add(co); s.commit(); s.refresh(co)
        now = datetime.now(timezone.utc)
        camp = Campaign(company_id=co.id, name="now", created_by=1, target={}, tools={},
                        status="completed", finished_at=now)
        s.add(camp); s.commit(); s.refresh(camp)
        s.add(Finding(company_id=co.id, campaign_id=camp.id, tool="t", category="c", plugin="p",
                      severity="high", passed=False, extra={"cost": 1.25, "tokens": 110}))
        s.commit()
        bs = budget_status(s, co)
        assert bs["cost"] == 1.25 and bs["tokens"] == 110 and bs["over_budget"] is True

        old = Campaign(company_id=co.id, name="old", created_by=1, target={}, tools={},
                       status="completed", finished_at=now - timedelta(days=5))
        s.add(old); s.commit(); oid = old.id
        assert retention_sweep(s) == 1
        assert s.get(Campaign, oid) is None
        assert s.get(Campaign, camp.id) is not None
