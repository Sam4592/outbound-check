"""Finding 4 check: after every send fails with 401, what does the lead table say?

Not yet a built-in rule (outbound-check doesn't see the agent's Airtable writes),
so this script runs the auth_error scenario in-process and prints the table.

    TARGET_DIR=... python benchmarks/kaymen99/check_status_after_401.py
"""

import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import adapter  # noqa: E402

from outbound_check.events import EventLog  # noqa: E402
from outbound_check.policy import load_policy  # noqa: E402
from outbound_check.sandbox import Sandbox, Tools  # noqa: E402
from outbound_check.scenario import builtin_scenario_paths, load_scenario  # noqa: E402

path = next(p for p in builtin_scenario_paths() if p.stem.endswith("auth_error"))
scenario = load_scenario(path, load_policy())
sandbox = Sandbox(scenario, EventLog())
sandbox.start_phase(0, scenario.phases[0].task)
tools = Tools(sandbox)
with contextlib.redirect_stdout(io.StringIO()):
    adapter.run(scenario.phases[0].task, tools)

sent = sum(e["type"] == "email_sent" for e in sandbox.log.events)
failed = sum(e["type"] == "email_failed" for e in sandbox.log.events)
print(f"emails sent: {sent}, failed with 401: {failed}")
for rid, fields in tools._kaymen["table"].items():
    print(f"{rid}  {fields['Email']:<26} Status={fields['Status']:<22} Last Contacted={fields.get('Last Contacted')}")
