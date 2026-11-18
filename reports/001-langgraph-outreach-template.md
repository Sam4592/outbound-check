# Report 001: crash-testing a LangGraph sales outreach template

**Date:** 2026-11-18
**Tool:** outbound-check 0.2.0
**Target:** [kaymen99/sales-outreach-automation-langgraph](https://github.com/kaymen99/sales-outreach-automation-langgraph) at commit [`2e2761c`](https://github.com/kaymen99/sales-outreach-automation-langgraph/tree/2e2761ccc16c26fe20adf101b4ec702cd0876b15) (2025-01-15)
**LangGraph:** 1.2.22, with every result reproduced on 0.2.62 (current when the template was written)

## Summary

We ran an open-source LangGraph outreach agent through the 8 outbound-check
scenarios. It researches each lead, writes a personalized email and either
saves it as a Gmail draft (the default) or sends it directly (a one-line
switch). The agent's own code ran unchanged. Only the outside services were
replaced (details under Method).

| | Direct-send mode | Draft mode (default) |
|---|---|---|
| Scenarios passed | 0 of 8 | 0 of 8 |
| Emails or drafts built from **another lead's research** | every one after the first lead in a run | every one after the first lead in a run |
| Emailed an unsubscribed and a hard-bounced address | yes | no (nothing sent) |
| Cold-emailed an existing customer | yes | no (nothing sent) |
| Kept attempting sends after a 401 | yes, one per remaining lead | no (nothing sent) |
| Marked leads "contacted" when every send failed | yes | n/a |
| Ran out of memory in one run of 60 leads | yes, at lead 22-23 | yes |

The most serious finding is the first row. A state bug means the research
report for the **first** lead in a run is reused to score and write the email
for **every** lead after it. With a real model, the email to the second lead
describes the first lead's company. In draft mode a reviewer has to catch
this by eye on every draft.

What it got right: it never emails a lead twice (a status column gates
re-sends), it never creates duplicate CRM records, and in its default mode
nothing leaves without a human.

These are bugs in a tutorial-style template, and the fixes are small
(see [Suggested fixes](#suggested-fixes)). We're publishing this because the
same patterns are easy to copy into production agents, and a regression suite
catches them before a sending domain or a customer relationship does.

## Why this agent

We looked at four open-source outbound agents and tested the one where a test
was both possible and fair:

| Project | Decision |
|---|---|
| [kaymen99/sales-outreach-automation-langgraph](https://github.com/kaymen99/sales-outreach-automation-langgraph) | **Tested.** Python and LangGraph, sends through the Gmail API, reads and updates a CRM table. |
| [Kandid-ai/AgentSDR](https://github.com/Kandid-ai/AgentSDR) | **Next.** A full product (Next.js, Postgres, Google Workspace) with its own caps, sending windows and bounce suppression. Testing it fairly needs the whole app running against a fake Gmail API. Planned for report 002. |
| [fayzan123/ghostline](https://github.com/fayzan123/ghostline) | **Excluded.** The current code doesn't send: approved drafts are printed for a person to copy and paste. (Its README still describes SMTP sending.) |
| [ladesai123/LangGraph-Lead-Generation](https://github.com/ladesai123/LangGraph-Lead-Generation) | **Excluded.** A course submission, which we don't think is fair to publish results about. |

## Method

| Part | What ran |
|---|---|
| Workflow graph, every node, the lead loop, CRM update logic | **Real code, unchanged** (`src/graph.py`, `src/nodes.py`) |
| `GmailTools`, including its error handling | **Real code**, with a fake Gmail `service` underneath. Sends and drafts go to the outbound-check sandbox, and a sandbox 401 is raised as an exception, like `googleapiclient` does |
| Airtable | In-memory table with the same semantics: fetch by `Status`, merge fields on update |
| LLM | Fixed responses (no API key in the test environment). Every lead is scored 8/10 so each one reaches the email step. Each stub report records which lead it was written about, and the email records which report it was given |
| Web research, Google Docs | Fixed text and placeholder links |

The adapter is [`benchmarks/kaymen99/adapter.py`](../benchmarks/kaymen99/adapter.py),
and full traces for both modes are in [`benchmarks/kaymen99/results/`](../benchmarks/kaymen99/results/).

## Findings

### 1. Every lead after the first gets an email built from the first lead's research

From the `happy_path` run (4 leads, processed last to first):

| Email to | Research it was written from |
|---|---|
| ben.carter@quill.example | Ben Carter |
| sofia.rossi@vela.example | **Ben Carter** |
| daniel.kim@harbor.example | **Ben Carter** |
| priya.shah@lumen.example | **Ben Carter** |

Three lines combine to cause it:

- `src/state.py:42` declares `reports: Annotated[list[Report], add]`, so every node's returned `reports` are **appended**.
- `src/nodes.py:562-581` `save_reports_to_google_docs` ends with `return state`, which hands the whole `reports` list back to be appended to itself.
- `src/nodes.py:597` tries to reset with `state["reports"] = []`. That mutates the node's local input and LangGraph never applies it.

`get_report()` (`src/utils.py:38-45`) returns the **first** report with a
matching title, which is always the first lead's.

Lead scoring uses the same lookup (`score_lead` reads the "Global Lead
Analysis Report"), so qualification is also decided on the first lead's
research:

```
scoring Ben Carter     on research about: Ben Carter
scoring Sofia Rossi    on research about: Ben Carter
scoring Daniel Kim     on research about: Ben Carter
scoring Priya Shah     on research about: Ben Carter
```

If the first lead in a run qualifies, the leads after it are scored on the
same research and are likely to qualify too, whoever they are.

outbound-check flags this with the `no_cross_prospect_content` rule: an email
to one prospect mentions another prospect's name. In this run the other
lead's name came from our stub marker. A real model given another lead's
research report would write about that lead's company instead.

### 2. Memory doubles with every lead

Because the list is appended to itself on each lead, its length doubles:

| Lead | Reports in state | Peak memory |
|---|---|---|
| 1 | 16 | 80 MB |
| 10 | 16,368 | 81 MB |
| 16 | 1,048,560 | 128 MB |
| 20 | 16,777,200 | 856 MB |
| 22 | 67,108,848 | 2,264 MB |

In the 60-lead `daily_cap` scenario the run hit a `MemoryError` at lead 22-23
(2 GB limit). On a machine without a limit, expect a hang or an
out-of-memory kill somewhere in the mid-twenties. Because the run ended
there, the daily cap itself couldn't be observed. We found no send limit in
the code.

### 3. Unsubscribed, bounced and customer addresses get emailed (direct mode)

The only gate is `Status == "NEW"` in the lead table
(`src/tools/leads_loader/airtable.py:27`). Nothing checks a suppression list
or the CRM lifecycle stage. From `suppressed_prospect` and `existing_customer`:

```
world: suppressed = [marc.dubois@orbit.example (unsubscribed), old.contact@pine.example (bounced)]
seq 5  email_sent  to=old.contact@pine.example      <- hard-bounced before
seq 7  email_sent  to=marc.dubois@orbit.example     <- unsubscribed last month

world: customers = [maria.lopez@globex.example]
seq 5  email_sent  to=Maria.Lopez@Globex.example    <- paying customer, cold email
```

(In direct mode the agent saves a Gmail draft before each send, so drafts
take the even sequence numbers.)

### 4. A revoked key doesn't stop the run, and failed leads are marked contacted

`GmailTools.send_email` catches the error and prints it
(`src/tools/base/gmail_tools.py:32-33`). The pipeline then moves to the next
lead and tries again. With 3 leads that's 3 attempts. With 300 it would be
300 attempts on a dead key.

`update_CRM` (`src/nodes.py:583-599`) then sets `Status: ATTEMPTED_TO_CONTACT`
and `Last Contacted` whether or not the send worked:

```
emails sent: 0, failed with 401: 3
rec000  nina.berg@arc.example      Status=ATTEMPTED_TO_CONTACT   Last Contacted=2026-11-18
rec001  felix.wang@tide.example    Status=ATTEMPTED_TO_CONTACT   Last Contacted=2026-11-18
rec002  amal.kh@sumac.example      Status=ATTEMPTED_TO_CONTACT   Last Contacted=2026-11-18
```

Once the key is fixed, these leads are never emailed, and the CRM says they
were. (Reproduce with
[`check_status_after_401.py`](../benchmarks/kaymen99/check_status_after_401.py).
outbound-check doesn't yet have a built-in rule for CRM writes that
contradict send results.)

### 5. No approval step in direct mode

By design: draft mode is the approval path, and direct mode skips it. Listed
for completeness, since `approval_required` fails in direct mode.

### 6. Leads at companies without a YouTube channel crash the run

`analyze_social_media_content` only assigns `youtube_analysis_report` inside
`if youtube_url:` (`src/nodes.py:193`) but always returns it
(`src/nodes.py:219`). The first lead without a YouTube link raises
`UnboundLocalError` and ends the run for every remaining lead. Our adapter
gives every stub company a YouTube link so the rest of the pipeline could be
tested.

## What passed

- **No repeat emails.** Leads move from `NEW` to `ATTEMPTED_TO_CONTACT`, so a second run doesn't email them again. That includes the lead who asked to stop in `negative_signals`. The agent is single-touch, so follow-up safety mostly isn't exercised.
- **No duplicate CRM records.** It updates existing rows and never creates contacts.
- **Draft mode sends nothing on its own.** A person is always the last step.

## Limits of this test

- **No real model.** We tested the code around the model, which is where every finding above lives. A real model would add its own failure modes, such as unsourced claims, that this run doesn't measure.
- **Every lead was qualified.** Scoring 8/10 for everyone puts every lead through the send path. With real scoring, unqualified leads skip the email step but still go through `save_reports_to_google_docs`, so findings 1 and 2 still apply. And because scoring reads the first lead's research (finding 1), real scores after the first lead mostly reflect that lead.
- **Direct mode isn't the default.** It's a one-line switch the code offers, and we report both modes.
- **Name matching.** `no_cross_prospect_content` looks for another prospect's full name, email address or company as whole words. Short or common-word company names can cause false positives (the threshold is configurable).

## Suggested fixes

1. In `save_reports_to_google_docs`, return `{}` (or only the keys it changes) instead of `state`.
2. Make per-lead reports resettable: key them by lead ID, or use a reducer that treats `None` as "clear" and return `{"reports": None}` from `update_CRM`.
3. Before sending, check a suppression list and skip contacts whose CRM lifecycle stage is `customer`.
4. On a 401 or 403, stop the run. Only set `ATTEMPTED_TO_CONTACT` when the send succeeded.
5. Initialize `youtube_analysis_report` (or return an empty list) when there's no YouTube URL.

## Reproduce

```bash
git clone https://github.com/Sam4592/outbound-check && cd outbound-check
pip install -e .
benchmarks/kaymen99/setup.sh                       # pinned target commit + minimal deps
export TARGET_DIR=.cache/targets/sales-outreach-automation-langgraph
KAYMEN_SEND_DIRECTLY=1 outbound-check run --agent benchmarks/kaymen99/adapter.py:run --out results/direct --max-memory-mb 2048
KAYMEN_SEND_DIRECTLY=0 outbound-check run --agent benchmarks/kaymen99/adapter.py:run --out results/draft  --max-memory-mb 2048
python benchmarks/kaymen99/check_status_after_401.py
```

We haven't opened issues on the upstream repository yet. If you maintain a
fork of this template, the fixes above apply as written.
