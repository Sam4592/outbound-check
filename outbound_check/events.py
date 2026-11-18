"""The event log: one JSON object per line, one line per action or signal.

Both the sandbox and the audit converter write this format, and the checker
only reads it. Every event has ``seq`` (order), ``ts`` (ISO 8601 UTC) and
``type``. Other fields depend on the type:

world_state          suppressed, customers, customer_domains, existing_contacts, prospects, source
phase_started        phase, task
crm_searched         email, found
crm_contact_created  contact_id, email
crm_contact_updated  contact_id, fields
suppression_checked  email, suppressed
approval_requested   approval_id, to, content_hash
approval_granted     approval_id, to, content_hash
approval_rejected    approval_id, to, content_hash, reason
email_sent           to, subject, body, content_hash, message_id, thread_id, reply_to_thread, approval_id
email_failed         to, error_code, error
draft_created        draft_id, to, subject, body, content_hash
email_bounced        email, reason
reply_received       from, thread_id, body, kind (reply | auto_reply | bounce_notice)
unsubscribed         email
spam_complaint       email
agent_error          error
budget_exceeded      limit
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def content_hash(subject: str, body: str) -> str:
    text = f"{(subject or '').strip()}\n\n{(body or '').strip()}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class EventLog:
    """Append-only event log, kept in memory and optionally mirrored to a JSONL file."""

    def __init__(self, path: str | Path | None = None):
        self.events: list[dict[str, Any]] = []
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")

    def append(self, type: str, ts: str, **fields: Any) -> dict[str, Any]:
        event = {"seq": len(self.events), "ts": ts, "type": type, **fields}
        self.events.append(event)
        if self.path:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event


def read_events(path: str | Path) -> list[dict[str, Any]]:
    events = []
    with Path(path).open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{line_no}: invalid JSON ({e})") from e
    events.sort(key=lambda e: e.get("seq", 0))
    return events


def write_events(events: list[dict[str, Any]], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
