# Benchmarks: real agents through outbound-check

Each folder connects one open-source outbound agent to the sandbox, runs the
built-in scenarios and keeps the traces. Reports on what we found live in
[`../reports/`](../reports/).

## Rules for adapters

1. **The agent's decision logic runs unchanged.** Adapters replace outside
   services only: email APIs, CRMs, LLMs, web research.
2. **Errors look like the real service's errors.** A sandbox 401 is raised the
   way the real client library would raise it, so the agent's own error
   handling is what gets tested.
3. **Stubs are documented in the adapter's docstring** and in the report's
   Method section, including any choice that changes which code paths run.
4. **The target is pinned to a commit.** `setup.sh` checks out that commit.
5. **Results are committed** (`results/<mode>/`): `results.json` plus one
   `*.events.jsonl` trace per scenario.

## Targets

| Folder | Target | Status |
|---|---|---|
| [`kaymen99/`](kaymen99/) | kaymen99/sales-outreach-automation-langgraph @ `2e2761c` | Done: [report 001](../reports/001-langgraph-outreach-template.md) |
| `agentsdr/` | Kandid-ai/AgentSDR | Planned (report 002) |

### AgentSDR plan

AgentSDR is a full application (Next.js, Postgres, Bun, Google Workspace
mailboxes) with its own sending rules: per-mailbox daily caps, send gaps,
sending hours, bounce suppression and Do Not Contact. Testing it fairly means
running the real app:

1. Start Postgres and seed one organization, one mailbox and a lead list from a scenario.
2. Point its Gmail client at a local fake of the Gmail REST API that forwards
   sends to the sandbox and returns sandbox replies, bounces and 401s.
3. Drive campaigns through its own API routes (`/api/campaigns/[id]/run`) and
   let its scheduler run on the sandbox clock where possible.
4. Convert its database state after each phase into the event log
   (contacts created, statuses), so CRM-side rules apply too.
