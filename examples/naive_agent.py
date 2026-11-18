"""A deliberately naive outbound agent: the happy-path demo that ships to production.

It creates a contact for every lead, emails everyone, retries failures, and
follows up with the whole list. It ignores every rule in its task.

    outbound-check run --agent examples/naive_agent.py:run
"""


def run(task, tools):
    prospects = tools.list_prospects()["prospects"]
    follow_up = "after the first touch" in task

    if follow_up:
        tools.read_replies()  # reads them, then ignores them
    for p in prospects:
        tools.create_contact(p["email"], p["first_name"], p["last_name"], p["company"], p["title"])
        subject = f"Quick follow-up, {p['first_name']}" if follow_up else f"{p['company']} + Northwind"
        body = (
            f"Hi {p['first_name']},\n\nCongrats on the recent growth at {p['company']}! "
            "Northwind helps teams like yours turn messy data into weekly decisions. Worth a 15-minute chat?\n\nBest,\nAlex"
        )
        for _ in range(5):  # "retry on failure"
            result = tools.send_email(p["email"], subject, body)
            if result.get("ok"):
                break
