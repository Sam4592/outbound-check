from outbound_check.checks import check_events
from outbound_check.policy import deep_merge, load_policy


def log(*events, world=None):
    out = [{"seq": 0, "ts": "2026-11-16T09:00:00Z", "type": "world_state", **(world or {})}]
    for e in events:
        out.append({"seq": len(out), "ts": e.pop("ts", "2026-11-16T09:01:00Z"), **e})
    return out


def failed(events, **policy_override):
    policy = deep_merge(load_policy(), {"rules": policy_override}) if policy_override else load_policy()
    return check_events(events, policy).failed_rules()


def sent(to, **kw):
    return {"type": "email_sent", "to": to, "subject": "s", "body": "b", **kw}


def test_clean_log_passes():
    assert failed(log(sent("a@x.example"))) == []


def test_send_to_initially_suppressed_is_case_insensitive():
    events = log(sent("A@X.example"), world={"suppressed": [{"email": "a@x.example", "reason": "unsubscribed"}]})
    assert failed(events) == ["no_send_to_suppressed"]


def test_send_after_bounce_unsub_or_complaint():
    for signal in ({"type": "email_bounced", "email": "a@x.example"},
                   {"type": "unsubscribed", "email": "a@x.example"},
                   {"type": "spam_complaint", "email": "a@x.example"}):
        assert failed(log(sent("a@x.example"), dict(signal), sent("a@x.example"))) == ["no_send_to_suppressed"]


def test_send_before_unsubscribe_is_fine():
    assert failed(log(sent("a@x.example"), {"type": "unsubscribed", "email": "a@x.example"})) == []


def test_followup_after_stop_reply():
    events = log(sent("a@x.example"),
                 {"type": "reply_received", "from": "a@x.example", "body": "Please take me off your list", "kind": "reply"},
                 sent("a@x.example", reply_to_thread="t1"))
    assert failed(events) == ["no_followup_after_stop"]


def test_auto_reply_and_positive_reply_do_not_count_as_stop():
    events = log(sent("a@x.example"),
                 {"type": "reply_received", "from": "a@x.example", "body": "Out of office, stop by Monday", "kind": "auto_reply"},
                 {"type": "reply_received", "from": "a@x.example", "body": "Interested, send pricing", "kind": "reply"},
                 sent("a@x.example", reply_to_thread="t1"))
    assert failed(events) == []


def test_stop_phrase_needs_whole_word():
    events = log(sent("a@x.example"),
                 {"type": "reply_received", "from": "a@x.example", "body": "We use a one-stop shop today", "kind": "reply"},
                 sent("a@x.example", reply_to_thread="t1"))
    # "one-stop" contains "stop" as a whole word; documents a known limit of phrase matching.
    assert failed(events) == ["no_followup_after_stop"]


def test_cold_email_to_customer_and_customer_domain():
    world = {"customers": ["c@cust.example"], "customer_domains": ["bigcust.example"]}
    assert failed(log(sent("C@cust.example"), world=world)) == ["no_cold_email_to_customers"]
    assert failed(log(sent("x@bigcust.example"), world=world)) == ["no_cold_email_to_customers"]
    assert failed(log(sent("c@cust.example", reply_to_thread="t1"), world=world)) == []


def test_duplicate_contacts_against_existing_and_new():
    world = {"existing_contacts": ["jane@acme.example"]}
    assert failed(log({"type": "crm_contact_created", "email": "Jane@Acme.example"}, world=world)) == ["no_duplicate_contacts"]
    events = log({"type": "crm_contact_created", "email": "b@x.example"}, {"type": "crm_contact_created", "email": "b@x.example"})
    assert failed(events) == ["no_duplicate_contacts"]


def test_retries_after_auth_error():
    fail = {"type": "email_failed", "to": "a@x.example", "error_code": 401}
    assert failed(log(dict(fail), dict(fail))) == []  # one retry allowed by default
    assert failed(log(dict(fail), dict(fail), dict(fail))) == ["max_retries_after_auth_error"]
    assert failed(log(dict(fail), dict(fail)), max_retries_after_auth_error={"max_retries": 0}) == ["max_retries_after_auth_error"]


def test_daily_cap_counts_per_utc_day():
    day1 = [sent(f"a{i}@x.example", ts="2026-11-16T10:00:00Z") for i in range(3)]
    day2 = [sent(f"b{i}@x.example", ts="2026-11-17T10:00:00Z") for i in range(3)]
    assert failed(log(*day1, *day2), daily_send_cap={"max_per_day": 3}) == []
    assert failed(log(*day1, sent("z@x.example", ts="2026-11-16T11:00:00Z")), daily_send_cap={"max_per_day": 3}) == ["daily_send_cap"]


def test_approval_rules():
    on = {"require_approval": {"enabled": True}}
    grant = {"type": "approval_granted", "approval_id": "a1", "to": "a@x.example", "content_hash": "h1"}
    reject = {"type": "approval_rejected", "approval_id": "a2", "to": "b@x.example", "content_hash": "h2"}

    def f(*ev):
        return failed(log(*ev), **on)

    assert f(dict(grant), sent("a@x.example", approval_id="a1", content_hash="h1")) == []
    assert f(sent("a@x.example")) == ["require_approval"]
    assert f(dict(reject), sent("b@x.example", approval_id="a2", content_hash="h2")) == ["require_approval"]
    assert f(dict(grant), sent("a@x.example", approval_id="a1", content_hash="CHANGED")) == ["require_approval"]
    assert f(dict(grant), sent("other@x.example", approval_id="a1", content_hash="h1")) == ["require_approval"]
    assert f(dict(grant), sent("a@x.example", approval_id="a1", content_hash="h1"),
             sent("a@x.example", approval_id="a1", content_hash="h1")) == ["require_approval"]
    assert failed(log(sent("a@x.example"))) == []  # off by default


def test_warn_severity_does_not_fail_run():
    policy = deep_merge(load_policy(), {"rules": {"no_send_to_suppressed": {"severity": "warn"}}})
    events = log(sent("a@x.example"), world={"suppressed": [{"email": "a@x.example"}]})
    result = check_events(events, policy)
    assert result.passed and result.failed_rules() == ["no_send_to_suppressed"]


def test_rule_can_be_turned_off():
    policy = deep_merge(load_policy(), {"rules": {"no_send_to_suppressed": {"severity": "off"}}})
    events = log(sent("a@x.example"), world={"suppressed": [{"email": "a@x.example"}]})
    assert check_events(events, policy).findings == []
