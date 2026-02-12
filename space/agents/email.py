
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from space.core.models import Email, EmailDirection, EmailStatus
from space.core.types import AgentId
from space.lib import config, store

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
GATEKEEPERS = {"sentinel", "tyson"}

ROUTING_RULES: list[tuple[list[str], str, str]] = [
    (["bug", "error", "crash", "broken", "fix"], "zealot", "code issue"),
    (["code", "implement", "feature", "technical", "api"], "zealot", "technical work"),
    (["security", "vulnerability", "audit"], "sentinel", "security concern"),
    (["strategy", "roadmap", "plan", "direction"], "seldon", "strategic planning"),
    (["risk", "concern", "worry", "consequence"], "harbinger", "risk assessment"),
    (["design", "ux", "ui", "user", "experience"], "jobs", "product/design"),
    (["investigate", "debug", "analyze", "case"], "kitsuragi", "investigation"),
    (["question", "why", "purpose", "mission"], "heretic", "mission alignment"),
    (["paper", "research", "publish", "academic"], "prime", "research work"),
]


@dataclass
class EmailResult:
    id: str | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.id is not None


@dataclass
class TriageResult:
    agent: str
    reason: str


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_email(r: tuple[str, ...]) -> Email:
    return Email(
        id=r[0],
        resend_id=r[1],
        direction=EmailDirection(r[2]),
        from_addr=r[3],
        to_addr=r[4],
        subject=r[5],
        body_text=r[6],
        body_html=r[7],
        status=EmailStatus(r[8]) if r[8] else EmailStatus.SENT,
        approved_by=AgentId(r[9]) if r[9] else None,
        approved_at=r[10],
        created_at=r[11],
    )


def fetch_body(email_id: str, received: bool = False) -> dict[str, Any] | None:
    cfg = config.load()
    if not cfg.email.api_key:
        return None

    url = f"{RESEND_API_URL}/receiving/{email_id}" if received else f"{RESEND_API_URL}/{email_id}"
    try:
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {cfg.email.api_key}"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch email {email_id}: {e}")
        return None


def fetch_received(limit: int = 20) -> list[dict[str, Any]]:
    cfg = config.load()
    if not cfg.email.api_key:
        return []

    try:
        response = httpx.get(
            f"{RESEND_API_URL}/receiving",
            headers={"Authorization": f"Bearer {cfg.email.api_key}"},
            params={"limit": limit},
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("data", [])
    except Exception as e:
        logger.error(f"Failed to fetch received emails: {e}")
        return []


def sync_inbound() -> list[Email]:
    received = fetch_received(limit=50)
    if not received:
        return []

    with store.ensure() as conn:
        existing = {
            r[0]
            for r in conn.execute(
                "SELECT resend_id FROM emails WHERE resend_id IS NOT NULL"
            ).fetchall()
        }

    new_emails = []
    for item in received:
        resend_id = item.get("id")
        if not resend_id or resend_id in existing:
            continue

        details = fetch_body(resend_id, received=True)
        if not details:
            continue

        to_list = item.get("to", [])
        to_addr = to_list[0] if to_list else ""

        saved = save_inbound(
            resend_id=resend_id,
            from_addr=item.get("from", ""),
            to_addr=to_addr,
            subject=item.get("subject"),
            body_text=details.get("text"),
            body_html=details.get("html"),
        )
        new_emails.append(saved)

    return new_emails


def save_inbound(
    resend_id: str,
    from_addr: str,
    to_addr: str,
    subject: str | None,
    body_text: str | None = None,
    body_html: str | None = None,
) -> Email:
    email = Email(
        id=str(uuid.uuid4()),
        resend_id=resend_id,
        direction=EmailDirection.INBOUND,
        from_addr=from_addr,
        to_addr=to_addr,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        status=EmailStatus.SENT,
        created_at=_now_iso(),
    )
    with store.ensure() as conn:
        conn.execute(
            """
            INSERT INTO emails (id, resend_id, direction, from_addr, to_addr, subject, body_text, body_html, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                email.id,
                email.resend_id,
                email.direction.value,
                email.from_addr,
                email.to_addr,
                email.subject,
                email.body_text,
                email.body_html,
                email.status.value,
                email.created_at,
            ),
        )
        conn.commit()
    return email


def list_emails(
    direction: EmailDirection | None = None,
    status: EmailStatus | None = None,
    limit: int = 50,
) -> list[Email]:
    with store.ensure() as conn:
        clauses = []
        params: list[str | int] = []
        if direction:
            clauses.append("direction = ?")
            params.append(direction.value)
        if status:
            clauses.append("status = ?")
            params.append(status.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM emails {where} ORDER BY created_at DESC LIMIT ?",  # noqa: S608
            params,
        ).fetchall()
    return [_row_to_email(r) for r in rows]


def get(email_id: str) -> Email | None:
    with store.ensure() as conn:
        row = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
        if not row:
            row = conn.execute("SELECT * FROM emails WHERE id LIKE ?", (f"{email_id}%",)).fetchone()
    if not row:
        return None
    return _row_to_email(row)


def draft(
    to: str | list[str],
    subject: str,
    body: str,
    from_addr: str | None = None,
    html: bool = False,
) -> Email:
    cfg = config.load()
    sender = from_addr or cfg.email.from_addr
    recipients = ", ".join([to] if isinstance(to, str) else to)
    email = Email(
        id=str(uuid.uuid4()),
        resend_id=None,
        direction=EmailDirection.OUTBOUND,
        from_addr=sender,
        to_addr=recipients,
        subject=subject,
        body_text=None if html else body,
        body_html=body if html else None,
        status=EmailStatus.DRAFT,
        created_at=_now_iso(),
    )
    with store.ensure() as conn:
        conn.execute(
            """
            INSERT INTO emails (id, resend_id, direction, from_addr, to_addr, subject, body_text, body_html, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                email.id,
                email.resend_id,
                email.direction.value,
                email.from_addr,
                email.to_addr,
                email.subject,
                email.body_text,
                email.body_html,
                email.status.value,
                email.created_at,
            ),
        )
        conn.commit()
    return email


def approve(email_id: str, approver_id: AgentId, approver_identity: str) -> EmailResult:
    if approver_identity not in GATEKEEPERS:
        return EmailResult(id=None, error=f"Only {GATEKEEPERS} can approve outbound emails")
    email = get(email_id)
    if not email:
        return EmailResult(id=None, error="Email not found")
    if email.status != EmailStatus.DRAFT:
        return EmailResult(id=None, error=f"Email is {email.status.value}, not draft")
    with store.ensure() as conn:
        conn.execute(
            "UPDATE emails SET status = ?, approved_by = ?, approved_at = ? WHERE id = ?",
            (EmailStatus.APPROVED.value, approver_id, _now_iso(), email.id),
        )
        conn.commit()
    return EmailResult(id=email.id, error=None)


def reject(email_id: str, approver_id: AgentId, approver_identity: str) -> EmailResult:
    if approver_identity not in GATEKEEPERS:
        return EmailResult(id=None, error=f"Only {GATEKEEPERS} can reject outbound emails")
    email = get(email_id)
    if not email:
        return EmailResult(id=None, error="Email not found")
    if email.status != EmailStatus.DRAFT:
        return EmailResult(id=None, error=f"Email is {email.status.value}, not draft")
    with store.ensure() as conn:
        conn.execute(
            "UPDATE emails SET status = ?, approved_by = ?, approved_at = ? WHERE id = ?",
            (EmailStatus.REJECTED.value, approver_id, _now_iso(), email.id),
        )
        conn.commit()
    return EmailResult(id=email.id, error=None)


def send_approved(email_id: str) -> EmailResult:
    email = get(email_id)
    if not email:
        return EmailResult(id=None, error="Email not found")
    if email.status != EmailStatus.APPROVED:
        return EmailResult(
            id=None, error=f"Email must be approved first (status: {email.status.value})"
        )
    body = email.body_html or email.body_text or ""
    html = email.body_html is not None
    result = _send_via_resend(
        to=email.to_addr.split(", "),
        subject=email.subject or "",
        body=body,
        from_addr=email.from_addr,
        html=html,
    )
    if result.ok:
        with store.ensure() as conn:
            conn.execute(
                "UPDATE emails SET status = ?, resend_id = ? WHERE id = ?",
                (EmailStatus.SENT.value, result.id, email.id),
            )
            conn.commit()
    return result


def _send_via_resend(
    to: str | list[str],
    subject: str,
    body: str,
    from_addr: str | None = None,
    html: bool = False,
) -> EmailResult:
    cfg = config.load()
    if not cfg.email.api_key:
        return EmailResult(id=None, error="RESEND_API_KEY not configured")
    sender = from_addr or cfg.email.from_addr
    recipients = [to] if isinstance(to, str) else to
    payload: dict[str, str | list[str]] = {
        "from": sender,
        "to": recipients,
        "subject": subject,
    }
    if html:
        payload["html"] = body
    else:
        payload["text"] = body
    try:
        response = httpx.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {cfg.email.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return EmailResult(id=data.get("id"), error=None)
    except httpx.HTTPStatusError as e:
        error = f"HTTP {e.response.status_code}: {e.response.text}"
        logger.error(f"Email send failed: {error}")
        return EmailResult(id=None, error=error)
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return EmailResult(id=None, error=str(e))


def send(
    to: str | list[str],
    subject: str,
    body: str,
    from_addr: str | None = None,
    html: bool = False,
) -> EmailResult:
    return EmailResult(
        id=None,
        error="Direct send disabled. Use 'email draft' then 'email approve' (sentinel/tyson only).",
    )


def triage(email_id: str) -> TriageResult | None:
    email_obj = get(email_id)
    if not email_obj:
        return None

    text = f"{email_obj.subject or ''} {email_obj.body_text or ''}".lower()

    for keywords, agent, reason in ROUTING_RULES:
        if any(kw in text for kw in keywords):
            return TriageResult(agent=agent, reason=reason)

    return TriageResult(agent="consul", reason="no clear routing - escalate to swarm")
