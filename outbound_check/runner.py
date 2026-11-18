"""Run an agent through scenarios and check the resulting event logs.

Two ways to plug an agent in:

- Python callable: ``module:function`` or ``path/to/file.py:function``.
  Called once per phase as ``fn(task: str, tools)``.
- External command: any program, any language. It is started once per phase
  with OUTBOUND_MCP_URL (the sandbox MCP server) and OUTBOUND_TASK set.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import traceback
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

from .checks import CheckResult, check_events
from .events import EventLog
from .policy import deep_merge
from .sandbox import Sandbox, Tools, ToolBudgetExceeded
from .scenario import Scenario

AgentFn = Callable[[str, Tools], Any]


@dataclass
class RunResult:
    scenario: Scenario
    check: CheckResult
    log_path: Path | None
    events: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario.name,
            "description": self.scenario.description.strip(),
            "traps": self.scenario.traps,
            "log": str(self.log_path) if self.log_path else None,
            **self.check.to_dict(),
        }


def load_agent(spec: str) -> AgentFn:
    target, _, attr = spec.partition(":")
    attr = attr or "run"
    if target.endswith(".py") or os.path.sep in target:
        path = Path(target).resolve()
        mod_spec = importlib.util.spec_from_file_location(path.stem, path)
        if not mod_spec or not mod_spec.loader:
            raise ImportError(f"cannot load {path}")
        module = importlib.util.module_from_spec(mod_spec)
        sys.modules[path.stem] = module
        mod_spec.loader.exec_module(module)
    else:
        module = importlib.import_module(target)
    fn = getattr(module, attr, None)
    if not callable(fn):
        raise AttributeError(f"{spec}: no callable named {attr!r}")
    return fn


def _run_phases(sandbox: Sandbox, scenario: Scenario, run_phase: Callable[[int, str], None]) -> None:
    for i, phase in enumerate(scenario.phases):
        sandbox.start_phase(i, phase.task, phase.after_days)
        try:
            run_phase(i, phase.task)
        except ToolBudgetExceeded:
            pass
        except Exception as e:  # the agent crashing is reported, not raised
            summary = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            sandbox.record_agent_error(f"{summary}\n{traceback.format_exc(limit=3)}")
    # Let late signals (unsubscribes, replies) land so the log is complete.
    sandbox.advance(timedelta(days=7))


def run_scenario(
    scenario: Scenario,
    policy: dict[str, Any],
    agent: AgentFn | None = None,
    agent_cmd: str | None = None,
    log_path: str | Path | None = None,
    phase_timeout: float = 300,
) -> RunResult:
    if (agent is None) == (agent_cmd is None):
        raise ValueError("pass exactly one of agent or agent_cmd")
    effective = deep_merge(policy, scenario.policy_overrides)
    log = EventLog(log_path)
    sandbox = Sandbox(scenario, log)

    if agent is not None:
        tools = Tools(sandbox)
        _run_phases(sandbox, scenario, lambda i, task: agent(task, tools))
    else:
        from .mcp_server import BackgroundServer

        with BackgroundServer(sandbox) as server:
            def run_cmd(i: int, task: str) -> None:
                env = {
                    **os.environ,
                    "OUTBOUND_MCP_URL": server.url,
                    "OUTBOUND_TASK": task,
                    "OUTBOUND_SCENARIO": scenario.name,
                    "OUTBOUND_PHASE": str(i),
                }
                proc = subprocess.run(
                    shlex.split(agent_cmd), env=env, capture_output=True, text=True, timeout=phase_timeout
                )
                if proc.returncode != 0:
                    sandbox.record_agent_error(
                        f"agent exited with code {proc.returncode}: {proc.stderr.strip()[-2000:]}"
                    )

            _run_phases(sandbox, scenario, run_cmd)

    result = check_events(log.events, effective)
    return RunResult(scenario=scenario, check=result, log_path=Path(log_path) if log_path else None, events=log.events)


def run_scenario_isolated(
    scenario_path: str | Path,
    policy_path: str | None,
    agent_spec: str,
    log_path: str | Path,
    agent_log_path: str | Path | None = None,
    max_memory_mb: int = 4096,
    timeout: float = 600,
) -> RunResult:
    """Run a Python agent in a child process with memory and time limits.

    A crash, out-of-memory kill or timeout is appended to the event log as an
    agent_error, and the partial log is checked like any other.
    """
    from .events import read_events
    from .policy import load_policy
    from .scenario import load_scenario

    policy = load_policy(policy_path)
    scenario = load_scenario(scenario_path, policy)
    log_path = Path(log_path)
    cmd = [sys.executable, "-m", "outbound_check.child", "--scenario", str(scenario_path),
           "--agent", agent_spec, "--log", str(log_path), "--max-memory-mb", str(max_memory_mb)]
    if policy_path:
        cmd += ["--policy", str(policy_path)]

    problem = None
    out = open(agent_log_path, "w", encoding="utf-8") if agent_log_path else subprocess.DEVNULL
    try:
        proc = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT if agent_log_path else subprocess.PIPE,
                              timeout=timeout)
        if proc.returncode < 0:
            sig = -proc.returncode
            hint = " (killed, most likely out of memory)" if sig == 9 else ""
            problem = f"Agent process killed by signal {sig}{hint}."
        elif proc.returncode != 0:
            problem = f"Agent process exited with code {proc.returncode}."
    except subprocess.TimeoutExpired:
        problem = f"Agent did not finish within {timeout:.0f}s."
    finally:
        if agent_log_path:
            out.close()

    events = read_events(log_path) if log_path.exists() and log_path.stat().st_size else []
    if not events:
        problem = problem or "Agent produced no events."
    if problem:
        last_ts = events[-1]["ts"] if events else scenario.start.strftime("%Y-%m-%dT%H:%M:%SZ")
        event = {"seq": len(events), "ts": last_ts, "type": "agent_error", "error": problem}
        events.append(event)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    effective = deep_merge(policy, scenario.policy_overrides)
    return RunResult(scenario=scenario, check=check_events(events, effective), log_path=log_path, events=events)
