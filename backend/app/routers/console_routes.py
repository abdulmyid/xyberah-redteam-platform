"""Interactive red-team console: send a single prompt to a target and get the
reply (Burp Repeater-style manual probing). Works with any target type."""
from fastapi import APIRouter, Depends

from ..auth import require_role
from ..models import Role, User
from ..orchestrator import runner
from ..schemas import TargetTestIn

router = APIRouter(prefix="/api/console", tags=["console"])


@router.post("/send")
def send(body: TargetTestIn, user: User = Depends(require_role(Role.analyst))):
    if not body.prompt:
        return {"ok": False, "error": "Enter a prompt"}
    return runner.run_single(body.target, body.prompt, company_id=user.company_id)
