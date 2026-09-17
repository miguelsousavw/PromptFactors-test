"""
ai_layer.py - THE ONLY FILE THAT CALLS AN LLM.

Design rule for this project: the LLM never decides anything. It receives facts
that were already derived deterministically (graph traversals, rule findings)
and turns them into readable language, or translates a question into filter
parameters that the deterministic layer then executes.

This keeps every number on screen traceable to a source row, and means the app
degrades gracefully to full functionality minus prose if no key is configured.

Responses are cached on disk so repeated Streamlit reruns never re-bill the
same call - important with a fixed LLMaaS budget.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import requests

CACHE_DIR = Path(__file__).parent / ".llm_cache"
CACHE_DIR.mkdir(exist_ok=True)

DEFAULT_BASE_URL = "https://llmaas.ai.vwgroup.com/llm-api/v1"
DEFAULT_MODEL = "claude-sonnet-4"
VW_DEFAULT_BASE_URL = "https://llmapi.ai.vwgroup.com"

SYSTEM_PROMPT = (
    "You are an enterprise architecture analyst. You will be given FACTS that "
    "were computed deterministically from an architecture repository. "
    "Rules you must follow:\n"
    "1. Use ONLY the facts provided. Never invent applications, interfaces, "
    "owners, dates or numbers.\n"
    "2. If the facts are insufficient to answer, say so plainly.\n"
    "3. Be concise and concrete. Write for an architect or a delivery lead.\n"
    "4. Refer to applications by the names given in the facts.\n"
    "5. Do not speculate about systems that are not in the facts."
)


class LLMUnavailable(Exception):
    """Raised when no key is configured or the endpoint cannot be reached."""


class VWResponsesClient:
    """OpenAI Responses API client used only for document fact extraction."""

    def __init__(self, token: str | None = None, virtual_key: str | None = None,
                 base_url: str | None = None, model: str | None = None):
        self.token = (token or os.environ.get("VW_LLM_API_KEY") or "").strip()
        self.virtual_key = ("sk-v1yHh9TrQW9AR0bH3Fwk5w")
        self.base_url = (base_url or os.environ.get("VW_LLM_BASE_URL")
                         or VW_DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("VW_LLM_MODEL") or "gpt-5-mini"

    @property
    def configured(self) -> bool:
        return bool(self.token and self.virtual_key)

    def extract(self, prompt: str) -> str:
        if not self.configured:
            raise LLMUnavailable("VW LLM extraction credentials are not configured.")
        try:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise LLMUnavailable(
                    "The optional openai package is not installed. "
                    "Redeploy after requirements.txt has been installed."
                ) from exc
            client = OpenAI(
                base_url=self.base_url,
                api_key=self.token,
                default_headers={"X-LLM-API-CLIENT-ID": f"Bearer {self.virtual_key}"},
            )
            response = client.responses.create(model=self.model, input=prompt)
            text = getattr(response, "output_text", "") or ""
            if not text:
                raise LLMUnavailable("VW LLM returned an empty extraction response.")
            return text
        except LLMUnavailable:
            raise
        except Exception as exc:
            raise LLMUnavailable(f"VW LLM extraction failed: {exc}") from exc


class LLMClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, use_cache: bool = True):
        self.api_key = (api_key or os.environ.get("LLMAAS_API_KEY") or "").strip()
        self.base_url = (base_url or os.environ.get("LLMAAS_BASE_URL")
                         or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("LLMAAS_MODEL") or DEFAULT_MODEL
        self.use_cache = use_cache
        self.calls_made = 0
        self.cache_hits = 0

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _cache_path(self, payload: dict) -> Path:
        blob = json.dumps(payload, sort_keys=True).encode()
        return CACHE_DIR / f"{hashlib.sha256(blob).hexdigest()[:24]}.json"

    def complete(self, user_prompt: str, max_tokens: int = 700,
                 temperature: float = 0.2) -> str:
        if not self.configured:
            raise LLMUnavailable(
                "No LLMaaS API key configured. Everything else in the app still "
                "works - only the generated prose is unavailable."
            )

        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }

        cache_file = self._cache_path(payload)
        if self.use_cache and cache_file.exists():
            self.cache_hits += 1
            return json.loads(cache_file.read_text())["text"]

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": "Bearer " + self.api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
            )
        except requests.RequestException as exc:
            raise LLMUnavailable(f"Could not reach the LLM endpoint: {exc}") from exc

        if resp.status_code >= 400:
            raise LLMUnavailable(
                f"LLM endpoint returned {resp.status_code}: {resp.text[:300]}"
            )

        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError) as exc:
            raise LLMUnavailable(f"Unexpected response shape: {str(data)[:300]}") from exc

        self.calls_made += 1
        if self.use_cache:
            cache_file.write_text(json.dumps({"text": text}))
        return text


# ---------------------------------------------------------------------------
# Fact builders - deterministic input, handed to the LLM as ground truth
# ---------------------------------------------------------------------------

def facts_for_context(sub, focus: str, findings_here) -> str:
    """Serialise a context subgraph into plain facts."""
    if focus not in sub:
        return "No focus application selected."

    n = sub.nodes[focus]
    lines = [
        f"FOCUS APPLICATION: {n.get('name')} (ID {focus})",
        f"  Business domain: {n.get('domain')}",
        f"  Criticality: {n.get('criticality')}",
        f"  Lifecycle status: {n.get('lifecycle')}",
        f"  Hosting: {n.get('hosting')}  Vendor type: {n.get('vendor_type')}",
        f"  Owner: {n.get('owner') or 'NONE RECORDED'}",
        f"  Business processes supported: "
        f"{', '.join(n.get('processes') or []) or 'none mapped'}",
        "",
        "UPSTREAM (this application consumes from):",
    ]

    ups = []
    for s, _t, d in sub.in_edges(focus, data=True):
        sn = sub.nodes[s]
        ups.append(f"  - {sn.get('name')} ({s}) via {d.get('kind')}"
                   f"{' [' + str(d.get('label')) + ']' if d.get('label') else ''}"
                   f"; criticality {sn.get('criticality')}, lifecycle {sn.get('lifecycle')}")
    lines += ups or ["  (none)"]

    lines += ["", "DOWNSTREAM (consumes from this application):"]
    downs = []
    for _s, t, d in sub.out_edges(focus, data=True):
        tn = sub.nodes[t]
        downs.append(f"  - {tn.get('name')} ({t}) via {d.get('kind')}"
                     f"{' [' + str(d.get('label')) + ']' if d.get('label') else ''}"
                     f"; criticality {tn.get('criticality')}, lifecycle {tn.get('lifecycle')}")
    lines += downs or ["  (none)"]

    if findings_here is not None and len(findings_here):
        lines += ["", "DETERMINISTIC FINDINGS ALREADY RAISED FOR THIS AREA:"]
        for _, f in findings_here.head(12).iterrows():
            lines.append(f"  - [{f['Severity']}] {f['Title']} ({f['Entity']}): {f['Evidence']}")

    return "\n".join(lines)


def prompt_context_summary(facts: str) -> str:
    return (
        "Below are facts about one application and its immediate architecture "
        "context.\n\nWrite a short briefing for an architect with exactly these "
        "three parts:\n"
        "**What this is** - two sentences on the application's role, inferred only "
        "from its domain, processes and connections.\n"
        "**What depends on it** - the concrete blast radius if it became "
        "unavailable, naming the applications and any business processes affected.\n"
        "**What needs attention** - the two or three most important issues from the "
        "findings, in plain language, each with why it matters. If there are no "
        "findings, say the context is clean.\n\n"
        "Do not add a preamble. Do not invent anything.\n\n"
        f"FACTS:\n{facts}"
    )


def facts_for_impact(g, app_id: str, layers: dict) -> str:
    n = g.nodes[app_id]
    lines = [
        f"APPLICATION UNDER ASSESSMENT: {n.get('name')} ({app_id})",
        f"  Criticality: {n.get('criticality')}, lifecycle: {n.get('lifecycle')}, "
        f"hosting: {n.get('hosting')}",
        f"  Supports processes: {', '.join(n.get('processes') or []) or 'none mapped'}",
        "",
        "DOWNSTREAM BLAST RADIUS BY DISTANCE:",
    ]
    if not layers:
        lines.append("  Nothing downstream depends on this application.")
    for depth, nodes in sorted(layers.items()):
        lines.append(f"  Hop {depth} ({len(nodes)} applications):")
        for node in nodes[:25]:
            d = g.nodes[node]
            procs = ", ".join(d.get("processes") or []) or "no mapped process"
            lines.append(f"    - {d.get('name')} ({node}); {d.get('criticality')}; {procs}")
        if len(nodes) > 25:
            lines.append(f"    ... and {len(nodes) - 25} more")
    return "\n".join(lines)


def prompt_impact(facts: str) -> str:
    return (
        "Below is a computed downstream dependency tree for one application.\n\n"
        "Write an impact assessment for a change advisory board covering:\n"
        "1. The scale of impact in one sentence.\n"
        "2. Which business processes are affected and via which applications.\n"
        "3. Which downstream applications are the most severe concerns and why.\n"
        "4. One concrete recommendation for sequencing or de-risking a change.\n\n"
        "Use only the applications named below.\n\n"
        f"FACTS:\n{facts}"
    )


def prompt_findings_digest(findings_facts: str) -> str:
    return (
        "Below is a list of deterministically detected architecture quality "
        "findings.\n\nWrite a management summary with:\n"
        "- One opening sentence stating the overall health of the landscape.\n"
        "- **Themes**: group the findings into three or four themes, each with a "
        "sentence on the underlying cause.\n"
        "- **Act first**: the three findings to fix first and why those three.\n\n"
        "Do not restate every finding. Do not invent counts - use the numbers given.\n\n"
        f"FINDINGS:\n{findings_facts}"
    )


def facts_for_findings(findings) -> str:
    if findings is None or findings.empty:
        return "No findings were raised."
    lines = [f"TOTAL FINDINGS: {len(findings)}"]
    counts = findings["Severity"].value_counts().to_dict()
    lines.append("BY SEVERITY: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    if "Discovery" in findings.columns:
        new = int((findings["Discovery"] == "NEW").sum())
        lines.append(f"NEWLY DISCOVERED (not in KnownDataQualityGaps): {new}")
    lines.append("")
    for _, f in findings.head(45).iterrows():
        lines.append(f"[{f['Severity']}] {f['Rule']} {f['Title']} | {f['Entity']} | {f['Evidence']}")
    if len(findings) > 45:
        lines.append(f"... and {len(findings) - 45} further findings")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Natural language -> deterministic filter parameters
# ---------------------------------------------------------------------------

QUERY_SCHEMA = """Return ONLY a JSON object, no prose, with these optional keys:
{
  "intent": "context" | "impact" | "list" | "unknown",
  "application": "<application name or ID mentioned, or null>",
  "domain": "<business domain mentioned, or null>",
  "process": "<business process mentioned, or null>",
  "filter": {
     "criticality": "<value or null>",
     "lifecycle": "<value or null>",
     "hosting": "<value or null>",
     "missing_owner": true | false
  },
  "explain": "<one sentence describing what you understood>"
}"""


def prompt_parse_question(question: str, apps: list[str], domains: list[str],
                          processes: list[str]) -> str:
    return (
        "Translate the user's question about an architecture landscape into "
        "query parameters. Match names to the closest item in the provided lists; "
        "if nothing matches, use null.\n\n"
        f"{QUERY_SCHEMA}\n\n"
        f"AVAILABLE APPLICATIONS: {', '.join(apps[:160])}\n"
        f"AVAILABLE DOMAINS: {', '.join(domains)}\n"
        f"AVAILABLE PROCESSES: {', '.join(processes[:80])}\n\n"
        f"QUESTION: {question}"
    )


def parse_json_response(text: str) -> dict:
    """Extract the JSON object from a model response, tolerating fences."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1]
        if t.startswith("json"):
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(t[start:end + 1])
    except json.JSONDecodeError:
        return {}


def prompt_extract_fsd(text: str, filename: str) -> str:
    """Request the SAP CPI extraction contract from the VW LLM."""
    return f"""You are an information extraction assistant.

Read the provided SAP CPI Functional Specification Document (FSD) and extract
the information into the JSON format below.

Rules:
- Extract only information explicitly stated in the document.
- Do not infer, assume, or generate values.
- If a value is not explicitly stated, return null.
- If multiple conflicting values exist, return null.
- Preserve the wording used in the document.
- Remove duplicate entries from dataObjects.
- Return only valid JSON.
- Do not return explanations, notes, or markdown.

Output schema:
{{
  "interfaceId": null,
  "interfaceName": null,
  "region": null,
  "country": null,
  "entity": null,
  "sourceSystem": null,
  "middleware": null,
  "targetSystem": null,
  "businessPurpose": null,
  "dataObjects": []
}}

Document: {filename}
DOCUMENT TEXT:
{text[:60000]}"""
