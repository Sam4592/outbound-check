"""A careful outbound agent that follows its rules. It should pass every scenario.

Rules come from the task text, the way a real agent gets them in its prompt.

    outbound-check run --agent examples/careful_agent.py:run
"""

import re


class StopSending(Exception):
    pass


def _cap(task):
    m = re.search(r"at most (\d+) emails per day", task)
    return int(m.group(1)) if m else 50


def _draft(p, follow_up):
    if follow_up:
        return (
            "Re: a quick idea for " + p.get("company", "your team"),
            f"Hi {p.get('first_name') or 'there'},\n\nFloating this back up in case it got buried. "
            "Happy to send a two-minute overview instead of a call.\n\nBest,\nAlex",
        )
    return (
        "A quick idea for " + p.get("company", "your team"),
        f"Hi {p.get('first_name') or 'there'},\n\nNorthwind helps operations teams turn scattered reporting "
        "into one weekly view. Open to a short overview?\n\nBest,\nAlex",
    )


def _ok_to_contact(tools, email):
    if tools.check_suppression(email)["suppressed"]:
        return False, None
    contacts = tools.search_contact(email)["contacts"]
    for c in contacts:
        if c.get("lifecycle_stage") == "customer" or c.get("email_status") not in (None, "ok"):
            return False, contacts
    return True, contacts


def _send(tools, p, follow_up, needs_approval, thread_id=None):
    subject, body = _draft(p, follow_up)
    approval_id = None
    if needs_approval:
        decision = tools.request_approval(p["email"], subject, body)
        if decision["status"] != "approved":
            return False
        approval_id = decision["approval_id"]
    result = tools.send_email(p["email"], subject, body, thread_id=thread_id, approval_id=approval_id)
    if not result.get("ok"):
        if result.get("error_code") in (401, 403):
            raise StopSending(result.get("error"))
        return False
    return True


def run(task, tools):
    cap = _cap(task)
    needs_approval = "request_approval" in task
    follow_up = "after the first touch" in task
    sent = 0
    try:
        if not follow_up:
            for p in tools.list_prospects()["prospects"]:
                if sent >= cap:
                    break
                ok, contacts = _ok_to_contact(tools, p["email"])
                if not ok:
                    continue
                if not contacts:
                    tools.create_contact(p["email"], p["first_name"], p["last_name"], p["company"], p["title"])
                if _send(tools, p, False, needs_approval):
                    sent += 1
        else:
            replies = tools.read_replies()["replies"]
            replied = {r["from"].lower() for r in replies if r["kind"] == "reply"}
            prospects = {p["email"].lower(): p for p in tools.list_prospects()["prospects"]}
            threads = {}
            for m in tools.list_sent()["sent"]:
                threads.setdefault(m["to"].lower(), m["thread_id"])
            for email, thread_id in threads.items():
                if sent >= cap or email in replied:
                    continue
                ok, _ = _ok_to_contact(tools, email)
                if not ok:
                    continue
                p = prospects.get(email, {"email": email})
                if _send(tools, p, True, needs_approval, thread_id=thread_id):
                    sent += 1
    except StopSending as e:
        print(f"Stopped sending: {e}")
