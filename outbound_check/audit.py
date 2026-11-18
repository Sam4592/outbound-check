"""Audit mode: turn CSV exports into an event log the checker can read.

For teams using a vendor agent they can't plug into CI. Export what the agent
did and run the same rules over it.

Activity CSV (one row per event; default column names, override with --map):
    timestamp, event, email, subject, body, error_code, thread_id, step, approval_id
    event is one of: sent, failed, bounced, replied, auto_reply, unsubscribed, complained
    step > 1 marks a follow-up in an existing sequence (not a cold email)

Contacts CSV (CRM export; HubSpot column names by default):
    Record ID, Email, Lifecycle Stage, Create Date

Known limits: lifecycle stage is the value at export time, so someone who
became a customer after being emailed would show as a cold email to a
customer. Check those findings by hand.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .events import content_hash, normalize_email

ACTIVITY_COLUMNS = {
    "timestamp": "timestamp",
    "event": "event",
    "email": "email",
    "subject": "subject",
    "body": "body",
    "error_code": "error_code",
    "thread_id": "thread_id",
    "step": "step",
    "approval_id": "approval_id",
}

CONTACT_COLUMNS = {
    "contact_id": "Record ID",
    "contact_email": "Email",
    "lifecycle_stage": "Lifecycle Stage",
    "created_at": "Create Date",
}

EVENT_TYPES = {
    "sent": "email_sent",
    "failed": "email_failed",
    "bounced": "email_bounced",
    "replied": "reply_received",
    "reply": "reply_received",
    "auto_reply": "reply_received",
    "unsubscribed": "unsubscribed",
    "complained": "spam_complaint",
    "spam": "spam_complaint",
}

EPOCH = "1970-01-01T00:00:00Z"


def _ts(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return EPOCH
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%m/%d/%Y %H:%M", "%d/%m/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"unrecognized timestamp: {value!r}")
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _col(row: dict[str, str], name: str) -> str:
    return (row.get(name) or "").strip()


def convert_exports(
    activity_csv: str | Path,
    contacts_csv: str | Path | None = None,
    customer_domains: list[str] | None = None,
    column_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    cols = {**ACTIVITY_COLUMNS, **CONTACT_COLUMNS, **(column_map or {})}
    staged: list[tuple[str, int, dict[str, Any]]] = []  # (ts, priority, event)
    customers: set[str] = set()

    if contacts_csv:
        rows = _read(contacts_csv)
        if rows and cols["contact_email"] not in rows[0]:
            raise ValueError(
                f"contacts CSV has no {cols['contact_email']!r} column; columns are {list(rows[0])}. "
                "Use --map contact_email='Your Column'."
            )
        for row in rows:
            email = _col(row, cols["contact_email"])
            if not email:
                continue
            if _col(row, cols["lifecycle_stage"]).lower() == "customer":
                customers.add(normalize_email(email))
            staged.append((_ts(_col(row, cols["created_at"])), 0, {
                "type": "crm_contact_created",
                "contact_id": _col(row, cols["contact_id"]) or None,
                "email": email,
            }))

    rows = _read(activity_csv)
    if rows and cols["event"] not in rows[0]:
        raise ValueError(
            f"activity CSV has no {cols['event']!r} column; columns are {list(rows[0])}. Use --map event='Your Column'."
        )
    for row in rows:
        kind = _col(row, cols["event"]).lower()
        etype = EVENT_TYPES.get(kind)
        if not etype:
            continue
        ts = _ts(_col(row, cols["timestamp"]))
        email = _col(row, cols["email"])
        ev: dict[str, Any] = {"type": etype}
        if etype == "email_sent":
            subject, body = _col(row, cols["subject"]), _col(row, cols["body"])
            thread = _col(row, cols["thread_id"]) or None
            step = _col(row, cols["step"])
            is_followup = step.isdigit() and int(step) > 1
            ev.update(to=email, subject=subject, body=body, content_hash=content_hash(subject, body),
                      thread_id=thread, reply_to_thread=(thread or f"step-{step}") if is_followup else None,
                      approval_id=_col(row, cols["approval_id"]) or None)
        elif etype == "email_failed":
            code = _col(row, cols["error_code"])
            ev.update(to=email, error_code=int(code) if code.isdigit() else code, error="")
        elif etype == "reply_received":
            ev.update(**{"from": email}, body=_col(row, cols["body"]), thread_id=_col(row, cols["thread_id"]) or None,
                      kind="auto_reply" if kind == "auto_reply" else "reply")
        else:
            ev.update(email=email)
        staged.append((ts, 1, ev))

    staged.sort(key=lambda t: (t[0], t[1]))
    first_ts = staged[0][0] if staged else EPOCH
    events: list[dict[str, Any]] = [{
        "seq": 0, "ts": first_ts, "type": "world_state", "source": "audit",
        "suppressed": [], "customers": sorted(customers),
        "customer_domains": [d.lower() for d in (customer_domains or [])],
        "existing_contacts": [],
    }]
    for ts, _, ev in staged:
        events.append({"seq": len(events), "ts": ts, **ev})
    return events
