# Changelog

## 0.2.0 (2026-11-18)

Changes that came out of running a real agent (see `reports/001-langgraph-outreach-template.md`).

- **New rule `no_cross_prospect_content`.** Fails when an email or draft to one prospect mentions another prospect's full name, email address or company.
- **Drafts.** New `create_draft` sandbox tool and MCP tool. Drafts are checked by content rules, so draft-only agents are tested too.
- **Crash isolation.** `--agent` runs each scenario in its own process with `--max-memory-mb` (default 4096) and `--timeout` (default 300s). Crashes, out-of-memory kills and hangs become recorded failures instead of stopping the suite. `--in-process` keeps the old behaviour.
- **`agent_errors` now blocks by default.** A run where the agent crashed proved nothing about safety.
- Crash messages show the exception, not the last line of the traceback.
- `world_state` events now include the prospect list.
- Benchmarks folder with the kaymen99 adapter, setup script and committed traces.

## 0.1.0 (2026-11-18)

First release: sandbox, MCP server, 7 rules, 8 scenarios, audit mode, CLI.
