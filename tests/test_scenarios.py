import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from outbound_check.cli import main
from outbound_check.policy import load_policy
from outbound_check.runner import load_agent, run_scenario
from outbound_check.scenario import builtin_scenario_paths, load_scenario

ROOT = Path(__file__).resolve().parents[1]
NAIVE = load_agent(str(ROOT / "examples" / "naive_agent.py") + ":run")
CAREFUL = load_agent(str(ROOT / "examples" / "careful_agent.py") + ":run")
SCENARIOS = builtin_scenario_paths()


def test_suite_has_eight_scenarios():
    assert len(SCENARIOS) == 8


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_naive_agent_trips_every_trap(path, tmp_path):
    policy = load_policy()
    scenario = load_scenario(path, policy)
    result = run_scenario(scenario, policy, agent=NAIVE, log_path=tmp_path / "events.jsonl")
    assert set(scenario.traps) <= set(result.check.failed_rules()), result.check.to_dict()
    assert not result.check.passed


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_careful_agent_passes_with_no_findings(path, tmp_path):
    policy = load_policy()
    scenario = load_scenario(path, policy)
    result = run_scenario(scenario, policy, agent=CAREFUL, log_path=tmp_path / "events.jsonl")
    assert result.check.findings == [], result.check.to_dict()


def test_event_log_written_and_ordered(tmp_path):
    policy = load_policy()
    scenario = load_scenario(SCENARIOS[0], policy)
    run_scenario(scenario, policy, agent=CAREFUL, log_path=tmp_path / "events.jsonl")
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert events[0]["type"] == "world_state"
    assert [e["seq"] for e in events] == list(range(len(events)))
    assert [e["ts"] for e in events] == sorted(e["ts"] for e in events)


def test_runaway_agent_hits_budget_and_is_reported(tmp_path):
    def runaway(task, tools):
        while True:
            tools.read_replies()

    policy = load_policy()
    scenario = load_scenario(SCENARIOS[0], policy)
    result = run_scenario(scenario, policy, agent=runaway)
    assert "agent_errors" in result.check.failed_rules()


def test_cli_exit_codes(tmp_path):
    agent = str(ROOT / "examples" / "careful_agent.py") + ":run"
    assert main(["run", "--agent", agent, "--out", str(tmp_path / "ok"), "--only", "happy_path"]) == 0
    agent = str(ROOT / "examples" / "naive_agent.py") + ":run"
    assert main(["run", "--agent", agent, "--out", str(tmp_path / "bad"), "--only", "auth_error"]) == 1
    summary = json.loads((tmp_path / "bad" / "results.json").read_text())
    assert summary["scenarios"][0]["failed_rules"] == ["max_retries_after_auth_error"]
    log = tmp_path / "bad" / "auth_error.events.jsonl"
    assert main(["check", str(log)]) == 1


def test_audit_mode_on_sample_exports(tmp_path):
    audit = ROOT / "examples" / "audit"
    code = main(["audit", "--activity", str(audit / "activity.csv"), "--contacts", str(audit / "contacts.csv"),
                 "--out", str(tmp_path / "audit.jsonl"), "--json", str(tmp_path / "audit.json")])
    assert code == 1
    result = json.loads((tmp_path / "audit.json").read_text())
    assert result["failed_rules"] == [
        "max_retries_after_auth_error", "no_cold_email_to_customers", "no_duplicate_contacts",
        "no_followup_after_stop", "no_send_to_suppressed",
    ]


@pytest.mark.skipif(importlib.util.find_spec("mcp") is None or importlib.util.find_spec("uvicorn") is None,
                    reason="MCP SDK not installed")
@pytest.mark.parametrize("name", ["negative_signals", "approval_required"])
def test_external_agent_over_mcp(name, tmp_path):
    import sys

    policy = load_policy()
    path = next(p for p in SCENARIOS if p.stem.endswith(name))
    scenario = load_scenario(path, policy)
    cmd = f"{shutil.which('python3') or sys.executable} {ROOT / 'examples' / 'mcp_agent.py'}"
    result = run_scenario(scenario, policy, agent_cmd=cmd, log_path=tmp_path / "events.jsonl", phase_timeout=60)
    assert result.check.findings == [], result.check.to_dict()
    assert result.check.stats["emails_sent"] > 0
