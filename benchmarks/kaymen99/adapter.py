"""Adapter: kaymen99/sales-outreach-automation-langgraph -> outbound-check sandbox.

What runs unmodified (the code under test):
  src/graph.py   the LangGraph workflow and its lead loop
  src/nodes.py   every node, including get_new_leads, generate_personalized_email, update_CRM
  src/tools/base/gmail_tools.py   GmailTools, including its own try/except around sends
  src/tools/leads_loader/lead_loader_base.py

What is replaced (external services only):
  Airtable        -> an in-memory table with Airtable semantics (Status filter, field merge on update)
  Gmail API       -> a fake `service` object; users().messages().send() goes to the sandbox,
                     and a sandbox 401 is raised as an exception like googleapiclient's HttpError
  LLM             -> fixed responses (no API key available); every lead is scored 8/10 so the
                     send path runs for every lead
  Web research    -> fixed text (LinkedIn, Serper, website scraping, YouTube, RAG)
  Google Docs     -> add_document returns placeholder links

Two modes, set with KAYMEN_SEND_DIRECTLY:
  1 (default here)  SEND_EMAIL_DIRECTLY = True, the README's "send directly" option
  0                 the repo default: Gmail drafts only, nothing is sent

Usage:
  TARGET_DIR=/path/to/sales-outreach-automation-langgraph \
    outbound-check run --agent benchmarks/kaymen99/adapter.py:run
"""

from __future__ import annotations

import base64
import os
import sys
import types
from email import message_from_bytes

PINNED_COMMIT = "2e2761c"
YOUTUBE_URL = os.environ.get("KAYMEN_YOUTUBE_URL", "https://www.youtube.com/@stubco")


# --------------------------------------------------------------------------- stubs for imports

def _stub_module(name: str, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    return mod


class _Anything:
    """Placeholder for third-party symbols that are imported but never reached."""

    def __init__(self, *a, **k):
        pass

    def __call__(self, *a, **k):
        return self

    def __getattr__(self, name):
        return self


def _install_import_stubs() -> None:
    _stub_module("googleapiclient")
    _stub_module("googleapiclient.discovery", build=lambda *a, **k: _Anything())
    _stub_module("googleapiclient.http", MediaFileUpload=_Anything)
    _stub_module("google_auth_oauthlib")
    _stub_module("google_auth_oauthlib.flow", InstalledAppFlow=_Anything())
    if "google" not in sys.modules:
        _stub_module("google")
    _stub_module("google.auth")
    _stub_module("google.auth.transport")
    _stub_module("google.auth.transport.requests", Request=_Anything)
    _stub_module("google.oauth2")
    _stub_module("google.oauth2.credentials", Credentials=_Anything())
    _stub_module("src.tools.rag_tool", fetch_similar_case_study=lambda description: "Stub case study.")


_loaded = None


def _load_target():
    global _loaded
    if _loaded:
        return _loaded
    target = os.environ.get("TARGET_DIR")
    if not target or not os.path.isdir(os.path.join(target, "src")):
        raise RuntimeError("Set TARGET_DIR to a checkout of kaymen99/sales-outreach-automation-langgraph")
    sys.path.insert(0, target)
    _install_import_stubs()
    import src.nodes as nodes  # noqa: E402
    import src.tools.base.gmail_tools as gmail_tools  # noqa: E402
    from src.graph import OutReachAutomation  # noqa: E402
    from src.structured_outputs import EmailResponse, WebsiteData  # noqa: E402
    from src.tools.leads_loader.lead_loader_base import LeadLoaderBase  # noqa: E402

    # Research tools: fixed text, no network.
    # A website and a YouTube link are returned so every node runs. With no YouTube link,
    # analyze_social_media_content raises UnboundLocalError (see the report's side findings).
    nodes.research_lead_on_linkedin = lambda name, email: (f"{name} profile (stub).", "Stub Co", "https://stub.example", "")
    nodes.research_lead_company = lambda url: "Stub company profile."
    nodes.generate_company_profile = lambda profile, summary: profile
    nodes.scrape_website_to_markdown = lambda url: ""
    nodes.get_recent_news = lambda company: "No recent news (stub)."
    nodes.get_youtube_stats = lambda url: "No YouTube data (stub)."
    nodes.fetch_similar_case_study = lambda description: "Stub case study."
    nodes.save_reports_locally = lambda reports: None

    import re

    def _subject_of(text):
        # Every stub report names the lead it was written about, so we can see which
        # lead's research ends up in which email.
        m = re.search(r"\[about: ([^\]]+)\]", text or "") or re.search(r"(\S+ \S+) profile \(stub\)", text or "")
        return m.group(1) if m else "unknown"

    def fake_llm(system_prompt, user_message, model=None, llm_provider=None, response_format=None):
        if response_format is EmailResponse:
            return EmailResponse(subject="A quick idea for your team",
                                 email=f"Hi,\n\nNorthwind helps teams like yours. Open to a short chat?\n\nBest,\nAlex\n\n"
                                       f"[research used: {_subject_of(user_message)}]")
        if response_format is WebsiteData:
            return WebsiteData(summary="", blog_url="", youtube=YOUTUBE_URL, twitter="", facebook="")
        if system_prompt == nodes.SCORE_LEAD_PROMPT:
            return "8"
        return f"Stub report. [about: {_subject_of(user_message)}]"

    nodes.invoke_llm = fake_llm
    gmail_tools.get_google_credentials = lambda: None
    import src.tools.google_docs_tools as docs_tools  # noqa: E402
    docs_tools.get_google_credentials = lambda: None
    # generate_custom_outreach_report always saves to Google Docs and needs the links back.
    docs_tools.GoogleDocsManager.add_document = lambda self, *a, **k: {
        "shareable_url": "https://docs.example/outreach-report", "folder_url": "https://drive.example/folder"}
    _loaded = (nodes, gmail_tools, OutReachAutomation, LeadLoaderBase)
    return _loaded


# --------------------------------------------------------------------------- fake services

class FakeGmailService:
    """Mimics service.users().messages().send(...).execute() and drafts().create(...).execute()."""

    def __init__(self, tools, drafts: list):
        self._tools = tools
        self._drafts = drafts

    def users(self):
        return self

    def messages(self):
        self._kind = "send"
        return self

    def drafts(self):
        self._kind = "draft"
        return self

    def send(self, userId, body):
        self._body = body
        return self

    def create(self, userId, body):
        self._body = body["message"]
        return self

    def execute(self):
        msg = message_from_bytes(base64.urlsafe_b64decode(self._body["raw"]))
        to, subject = msg["to"], msg["subject"]
        text = msg.get_payload(decode=True).decode("utf-8", "replace")
        if self._kind == "draft":
            self._drafts.append({"to": to, "subject": subject})
            result = self._tools.create_draft(to, subject, text)
            return {"id": result["draft_id"]}
        result = self._tools.send_email(to, subject, text)
        if not result.get("ok"):
            raise RuntimeError(f"<HttpError {result.get('error_code')}: {result.get('error')}>")
        return {"id": result["message_id"], "threadId": result["thread_id"]}


def _make_loader(LeadLoaderBase, table: dict):
    class InMemoryAirtableLoader(LeadLoaderBase):
        def fetch_records(self, lead_ids=None, status_filter="NEW"):
            if lead_ids:
                return [{"id": i, **table[i]} for i in lead_ids if i in table]
            return [{"id": i, **f} for i, f in table.items() if f.get("Status") == status_filter]

        def update_record(self, lead_id, updates: dict):
            if lead_id not in table:
                raise ValueError(f"Record with ID {lead_id} not found.")
            table[lead_id] = {**table[lead_id], **updates}
            return {"id": lead_id, "fields": table[lead_id]}

    return InMemoryAirtableLoader()


# --------------------------------------------------------------------------- entry point

def run(task, tools):
    nodes, gmail_tools, OutReachAutomation, LeadLoaderBase = _load_target()
    nodes.SEND_EMAIL_DIRECTLY = os.environ.get("KAYMEN_SEND_DIRECTLY", "1") == "1"

    # The lead table persists across phases of one scenario, like a real Airtable base.
    state = tools.__dict__.setdefault("_kaymen", {})
    if "table" not in state:
        state["drafts"] = []
        state["table"] = {
            f"rec{i:03d}": {
                "First Name": p["first_name"], "Last Name": p["last_name"], "Email": p["email"],
                "Phone": "", "Address": "", "Status": "NEW",
            }
            for i, p in enumerate(tools.list_prospects()["prospects"])
        }
    gmail_tools.build = lambda *a, **k: FakeGmailService(tools, state["drafts"])

    app = OutReachAutomation(_make_loader(LeadLoaderBase, state["table"])).app
    app.invoke({"leads_ids": []}, {"recursion_limit": 1000})
