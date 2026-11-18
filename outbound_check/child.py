"""Run one scenario for a Python agent in a separate process.

Used by `outbound-check run --agent` so that an agent that runs out of memory,
hangs or calls sys.exit() is recorded as a failure instead of taking the runner
down with it. The event log is written to disk as the run goes, so the parent
can still check everything that happened before the crash.
"""

from __future__ import annotations

import argparse
import sys


def _limit_memory(max_memory_mb: int) -> None:
    if max_memory_mb <= 0:
        return
    try:
        import resource

        limit = max_memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):  # not available on this platform
        pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", required=True)
    p.add_argument("--agent", required=True)
    p.add_argument("--log", required=True)
    p.add_argument("--policy")
    p.add_argument("--max-memory-mb", type=int, default=0)
    args = p.parse_args(argv)

    _limit_memory(args.max_memory_mb)

    from .policy import load_policy
    from .runner import load_agent, run_scenario
    from .scenario import load_scenario

    policy = load_policy(args.policy)
    scenario = load_scenario(args.scenario, policy)
    run_scenario(scenario, policy, agent=load_agent(args.agent), log_path=args.log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
