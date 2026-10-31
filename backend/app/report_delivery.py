"""Email a campaign's report after a scheduled run. Best-effort, runs in a thread
(PDF rendering is heavy). Triggered on completion for campaigns a schedule launched."""
import logging
import threading

from sqlmodel import Session, select

from .db import engine
from .email_service import send_email
from .models import Campaign, Finding, Schedule
from .orchestrator.targets import Target
from .reports import builder

log = logging.getLogger("xyberah.report_delivery")


def maybe_deliver(campaign_id: int) -> None:
    """If this campaign was launched by a schedule with report recipients, render the
    report and email it to them."""
    def _run() -> None:
        try:
            with Session(engine) as s:
                c = s.get(Campaign, campaign_id)
                if not c:
                    return
                sid = (c.tools or {}).get("_schedule_id")
                if not sid:
                    return
                sch = s.get(Schedule, sid)
                if not sch or not sch.report_emails:
                    return
                findings = [f.model_dump() for f in
                            s.exec(select(Finding).where(Finding.campaign_id == campaign_id)).all()]
                target_display = Target(**c.target).display
                fmt = (sch.report_format or "pdf").lower()
                recipients = list(sch.report_emails)
                name = c.name
                if fmt == "attestation":
                    from .models import AuditLog
                    head = s.exec(select(AuditLog).order_by(AuditLog.id.desc())).first()
                    html = builder.render_attestation(c, findings, target_display,
                                                      assessor="Scheduled delivery",
                                                      audit_head=head.row_hash if head else "")
                    fname = f"{name}-attestation.pdf"
                else:
                    tools_used = sorted({f["tool"] for f in findings})
                    html = builder.render_html(c, findings, tools_used, target_display)
                    fname = f"{name}.pdf"
            pdf = builder.render_pdf(html)
            subject = f"[Xyberah] Report: {name}"
            body = (f"<p>The automated Xyberah report for <b>{name}</b> is attached "
                    f"({fmt}).</p><p>This was sent by a scheduled scan.</p>")
            for to in recipients:
                try:
                    send_email(to, subject, body, attachments=[(fname, pdf, "application", "pdf")])
                except Exception as exc:  # noqa: BLE001
                    log.warning("report email to %s failed: %s", to, exc)
        except Exception:
            log.exception("report delivery failed for campaign %s", campaign_id)

    threading.Thread(target=_run, name=f"report-deliver-{campaign_id}", daemon=True).start()
