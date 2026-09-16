# PromptFactors — AI + LeanIX Context Intelligence

**i.mobilothon 6.0 · Challenge: Automated Context Diagram Generation**

Turns a LeanIX-style enterprise architecture workbook into interactive context
diagrams, traceable data-quality findings, and answerable questions.

---

## Quick start

```bash
pip install -r requirements.txt
python -m streamlit run app.py
```

Or use the included launcher:

```bash
./run.sh
```

Then either:
- upload the organisers' `Auriga_Motors_Synthetic_EA_Dataset.xlsx`, or
- click **Generate** in the sidebar to create a synthetic workbook and explore immediately.

No LLMaaS key is required to run the app. Without a key every deterministic
feature still works — only the generated prose is unavailable.

## Run it in the cloud

### Recommended: Streamlit Community Cloud

Streamlit Community Cloud hosts this app for free from a GitHub repository:

1. Create a GitHub repository and upload this project.
2. Go to <https://share.streamlit.io> and sign in with GitHub.
3. Select the repository, branch, and `app.py` as the main file.
4. Click **Deploy**.
5. If using the optional AI layer, add `LLMAAS_API_KEY`, `LLMAAS_BASE_URL`, and
   `LLMAAS_MODEL` under the app's **Settings → Secrets**. Do not commit keys
   to the repository.

The app will receive a permanent HTTPS URL and will keep running without your
computer being on. The workbook and document are uploaded through the browser
when someone uses the app; they are processed in the hosted app session.

### Docker hosts: Render, Railway, Fly.io, or an internal server

This repository includes a `Dockerfile`. Create a web service from the
repository and configure:

```text
Build:  docker build -t promptfactors .
Start:  docker run -p $PORT:8501 -e PORT=$PORT promptfactors
```

For platforms that run the Dockerfile directly, use the container's default
command and map the service port to `8501` (or set the platform's `PORT`
environment variable to `8501`). This option is useful when you need private
networking, persistent storage, or enterprise authentication.

---

## The core design decision

| Step | Logic | Why |
|---|---|---|
| 1 · Ingest & validate workbook | **Deterministic** | Parsing and referential integrity must be exact and repeatable |
| 2 · Build architecture graph | **Deterministic** | One backbone all views share, so nothing can disagree |
| 3 · Render context diagrams | **Deterministic** | Fixed-seed layout — same input always draws the same picture |
| 4 · Detect quality & risk findings | **Deterministic** | Every finding traces to source rows and is auditable |
| 5 · Explain findings and context | **AI** | Turning computed facts into readable language for stakeholders |
| 6 · Interpret natural-language questions | **AI** | Only maps a question to filter parameters; the graph answers it |
| 7 · Produce LeanIX payload | **Deterministic** | Exported architecture data must never contain generated content |

**The LLM never decides anything.** It receives facts already derived
deterministically and turns them into language, or translates a question into
filter parameters the deterministic layer then executes. Every number on screen
traces back to a source row.

### The trade-off we made

The obvious approach is to let an LLM read the workbook and infer the
architecture. **We rejected that**: it cannot be audited, it is not reproducible
against a modified workbook, and it burns a fixed budget on work a join does
better. For free-text specifications, the MVP now offers a deliberately separate,
review-first candidate path (see Document ingestion below); the workbook remains
the authoritative deterministic source of record.

---

## Demo success condition

> Upload a previously unseen copy of the EA workbook and, within 60 seconds,
> produce a correct context diagram for any selected application plus at least
> three data-quality findings that are traceable to specific source rows and are
> not already listed in `KnownDataQualityGaps`.

---

## Proving nothing is hard-coded

The dataset guide warns that judges *"may score your solution against a MODIFIED
copy of this workbook with different IDs and additional scenarios"* and to
*"NOT hard-code to these row IDs"*.

Every sheet and column is resolved **by name**, and every finding is derived from
a join or a traversal. To demonstrate this live:

```bash
python make_sample_dataset.py --seed 42  --out sample_ea_seed42.xlsx
python make_sample_dataset.py --seed 777 --out sample_ea_seed777.xlsx
```

Load each in turn. Two completely different sets of IDs, applications and seeded
scenarios — all 8 rules fire on both:

| | seed 42 | seed 777 |
|---|---|---|
| Applications | 64 | 64 |
| Undefined (ghost) references | 4 | 3 |
| Findings raised | 191 | 187 |
| Newly discovered (not pre-declared) | 188 | 183 |

---

## The rule engine

All checks are deterministic, pattern-derived, and produce a severity, evidence
and a source-row reference.

| Rule | Check | Catches |
|---|---|---|
| **R01** | Broken references | FKs pointing at applications that don't exist (the ghost `APP-9xxx` scenario, generically) |
| **R02** | Ownership gaps | Missing ownership rows, blank owner/custodian fields |
| **R03** | Lifecycle risk | End-of-life or expired applications still feeding active consumers |
| **R04** | Interface hygiene | Self-referencing interfaces, interfaces carrying no data, inactive interfaces that still carry flows |
| **R05** | Redundant interfaces | Multiple interfaces between the same application pair |
| **R06** | Coverage gaps | Isolated applications; critical applications supporting no mapped process |
| **R07** | Criticality inversion | Mission-critical applications depending on far lower-tier ones |
| **R08** | Data classification | Unclassified information objects; sensitive data flowing into SaaS/public-cloud targets |

`KnownDataQualityGaps` is documented as **partial**. The app separates
**KNOWN** from **NEW** findings, so you can show exactly what the engine
discovered that the workbook does not already tell you.

---

## Failure modes and handling

| Failure mode | Handling |
|---|---|
| No LeanIX access | Export the LeanIX-shaped payload instead of writing live — the demo never blocks on the dependency |
| No LLM key / endpoint unreachable | Every deterministic feature still runs; the app says explicitly what is unavailable |
| Workbook with different IDs or extra scenarios | Sheets and columns matched by name; no row ID hard-coded |
| Broken references in the data | Ghost nodes rendered in **black** rather than dropped, so gaps stay visible |
| A rule crashes on unexpected data | Each rule is isolated; a failing rule reports itself and the rest still run |
| LLM cost overrun on fixed budget | All responses cached to disk; calls fire only on explicit button press, never on page rerun |

---

## The LeanIX dependency

We do not have live LeanIX access. Rather than block on it, the app emits the
**exact payload a LeanIX import would consume**:

```
promptfactors_leanix_export.zip
├── leanix_factsheets.csv     # Application factsheets
├── leanix_relations.csv      # Typed relations (app↔app, app↔interface, app↔data)
├── accepted_findings.csv     # Only findings a human accepted in the review tab
└── manifest.json             # Provenance: what was computed vs generated
```

If access lands, this payload becomes the body of the API call. If it does not,
the export file is the demonstrable deliverable. **The dependency became a named
risk with a working fallback, not a blocker.**

---

## Human control

The **Quality & risk** tab is a review surface, not a dump. Every finding has an
Accept checkbox; only accepted findings reach the export, and the manifest
records that a human reviewed them. AI-generated text is never exported.

---

## Files

```
app.py                    Streamlit UI — 6 tabs
ingest.py                 Workbook loading, column normalisation, validation
graph_build.py            Typed directed multigraph + subgraph/impact traversals
rules.py                  The 8 deterministic rules
diagram.py                Plotly interactive context diagrams
ai_layer.py               The only file that calls an LLM — cached, degradable
leanix_export.py          LeanIX-shaped export bundle
make_sample_dataset.py    Synthetic workbook generator (seeded)
```

---

## Configuring LLMaaS

Enter the key in the sidebar, or set environment variables:

```bash
export LLMAAS_API_KEY="sk-..."
export LLMAAS_BASE_URL="https://llmaas.ai.vwgroup.com/llm-api/v1"
export LLMAAS_MODEL="claude-sonnet-4"
```

The client assumes an OpenAI-compatible `/chat/completions` endpoint. **Verify
the exact base URL and model identifier against the LLMaaS getting-started page
before the demo** — if the path differs, change `DEFAULT_BASE_URL` in
`ai_layer.py`. This is the one thing in the app that has not been tested against
the live endpoint.

---

*Team PromptFactors · Digital Solutions PT*

## Document ingestion (MVP)

The sidebar accepts `.txt`, `.md`, `.docx`, and `.pdf` design documents. Text is
extracted locally, then (only after an explicit button press) sent to the optional
LLM as bounded text. The model returns architecture candidates in JSON. Candidates
are shown in an editable acceptance table; only checked rows are merged into the
same deterministic graph. AI candidates are never silently exported as facts.

## Smoke checks

```bash
python3 smoke_test.py
python3 make_sample_dataset.py --seed 42 --out sample_ea.xlsx
streamlit run app.py
```
