"""Command line: run scenarios, check a log, audit exports."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from importlib import resources
from pathlib import Path
from typing import Any

from . import __version__
from .checks import CheckResult, check_events
from .events import read_events, write_events
from .policy import load_policy
from .runner import load_agent, run_scenario
from .scenario import builtin_scenario_paths, load_scenario

GREEN, RED, YELLOW, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"


def _color(enabled: bool):
    def c(code: str, text: str) -> str:
        return f"{code}{text}{RESET}" if enabled else text
    return c


def _print_result(name: str, result: CheckResult, c, log_path: Any = None) -> None:
    status = c(GREEN, "PASS") if result.passed else c(RED, "FAIL")
    s = result.stats
    stats = "sent={} failed={} contacts_created={}".format(
        s.get("emails_sent", 0), s.get("send_failures", 0), s.get("contacts_created", 0)
    )
    print(f"{status}  {c(BOLD, name)}  {c(DIM, stats)}")
    for f in result.findings:
        tag = c(RED, "block") if f.severity == "block" else c(YELLOW, "warn ")
        seq = f" (seq {f.seq})" if f.seq is not None else ""
        print(f"      {tag}  {f.rule}: {f.message}{c(DIM, seq)}")
    if log_path and not result.passed:
        print(c(DIM, f"      trace: {log_path}"))


def cmd_run(args: argparse.Namespace) -> int:
    policy = load_policy(args.policy)
    paths = [Path(p) for p in args.scenario] if args.scenario else builtin_scenario_paths()
    agent = load_agent(args.agent) if args.agent else None
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    c = _color(sys.stdout.isatty() and not args.no_color)

    results = []
    for path in paths:
        scenario = load_scenario(path, policy)
        if args.only and scenario.name not in args.only:
            continue
        r = run_scenario(
            scenario, policy, agent=agent, agent_cmd=args.agent_cmd,
            log_path=out_dir / f"{scenario.name}.events.jsonl", phase_timeout=args.timeout,
        )
        results.append(r)
        _print_result(scenario.name, r.check, c, r.log_path)

    passed = sum(r.check.passed for r in results)
    print()
    print(f"{passed}/{len(results)} scenarios passed")
    summary = {"version": __version__, "passed": passed == len(results), "scenarios": [r.to_dict() for r in results]}
    (out_dir / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(c(DIM, f"results: {out_dir / 'results.json'}"))
    return 0 if passed == len(results) else 1


def cmd_check(args: argparse.Namespace) -> int:
    policy = load_policy(args.policy)
    events = read_events(args.events)
    result = check_events(events, policy)
    c = _color(sys.stdout.isatty() and not args.no_color)
    _print_result(Path(args.events).name, result, c)
    if args.json:
        Path(args.json).write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    return 0 if result.passed else 1


def cmd_audit(args: argparse.Namespace) -> int:
    from .audit import convert_exports

    mapping = dict(m.split("=", 1) for m in (args.map or []))
    events = convert_exports(
        activity_csv=args.activity, contacts_csv=args.contacts,
        customer_domains=args.customer_domain or [], column_map=mapping,
    )
    write_events(events, args.out)
    print(f"wrote {len(events)} events to {args.out}")
    args.events = args.out
    return cmd_check(args)


def cmd_scenarios(args: argparse.Namespace) -> int:
    policy = load_policy(None)
    for path in builtin_scenario_paths():
        sc = load_scenario(path, policy)
        traps = ", ".join(sc.traps) or "none"
        print(f"{sc.name:<22} phases={len(sc.phases)}  traps: {traps}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if target.exists() and not args.force:
        print(f"{target} already exists (use --force to overwrite)")
        return 1
    src = resources.files("outbound_check").joinpath("default_policy.yaml")
    with resources.as_file(src) as p:
        shutil.copy(p, target)
    print(f"wrote {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="outbound-check", description="Crash-test lab for AI sales agents.")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="run an agent through scenarios")
    who = p.add_mutually_exclusive_group(required=True)
    who.add_argument("--agent", help="Python agent: module:function or file.py:function")
    who.add_argument("--agent-cmd", help="external agent command; gets OUTBOUND_MCP_URL and OUTBOUND_TASK")
    p.add_argument("--scenario", action="append", help="scenario YAML (repeatable; default: built-in suite)")
    p.add_argument("--only", action="append", help="run only scenarios with this name (repeatable)")
    p.add_argument("--policy", help="policy YAML (merged over defaults)")
    p.add_argument("--out", default="outbound-check-results", help="output directory for logs and results.json")
    p.add_argument("--timeout", type=float, default=300, help="seconds per phase for --agent-cmd")
    p.add_argument("--no-color", action="store_true")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("check", help="check an existing event log")
    p.add_argument("events")
    p.add_argument("--policy")
    p.add_argument("--json", help="write result JSON here")
    p.add_argument("--no-color", action="store_true")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("audit", help="convert CSV exports to an event log and check it")
    p.add_argument("--activity", required=True, help="sending activity CSV (sent, failed, bounced, replied, unsubscribed, complained)")
    p.add_argument("--contacts", help="CRM contacts CSV (HubSpot export column names by default)")
    p.add_argument("--map", action="append", help="column mapping, e.g. email='E-mail Address' (repeatable)")
    p.add_argument("--customer-domain", action="append", help="treat this domain as a customer (repeatable)")
    p.add_argument("--out", default="audit.events.jsonl")
    p.add_argument("--policy")
    p.add_argument("--json")
    p.add_argument("--no-color", action="store_true")
    p.set_defaults(fn=cmd_audit)

    p = sub.add_parser("scenarios", help="list built-in scenarios")
    p.set_defaults(fn=cmd_scenarios)

    p = sub.add_parser("init-policy", help="write the default policy file to edit")
    p.add_argument("path", nargs="?", default="outbound-policy.yaml")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
