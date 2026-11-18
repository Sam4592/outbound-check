import sys
from pathlib import Path

import pytest

from outbound_check.runner import run_scenario_isolated
from outbound_check.scenario import builtin_scenario_paths

FIXTURES = Path(__file__).parent / "fixtures" / "crashing_agents.py"
HAPPY = next(p for p in builtin_scenario_paths() if p.stem.endswith("happy_path"))


def run(fn, tmp_path, **kw):
    return run_scenario_isolated(HAPPY, None, f"{FIXTURES}:{fn}", tmp_path / "e.jsonl",
                                 agent_log_path=tmp_path / "agent.log", **kw)


def test_hard_exit_is_recorded_and_partial_log_kept(tmp_path):
    r = run("sends_then_exits", tmp_path)
    assert r.check.stats["emails_sent"] == 1
    assert "agent_errors" in r.check.failed_rules()
    assert any("exited with code 3" in f.message for f in r.check.findings)


@pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_AS behaviour is Linux-specific")
def test_memory_limit_turns_runaway_memory_into_a_failure(tmp_path):
    r = run("eats_memory", tmp_path, max_memory_mb=512)
    assert "agent_errors" in r.check.failed_rules()
    assert any("MemoryError" in f.message or "signal" in f.message for f in r.check.findings)


def test_timeout_is_recorded(tmp_path):
    r = run("hangs", tmp_path, timeout=3)
    assert any("did not finish within 3s" in f.message for f in r.check.findings)
