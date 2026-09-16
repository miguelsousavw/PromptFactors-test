"""
PromptFactors - AI + LeanIX Context Intelligence
i.mobilothon 6.0 | Challenge: Automated Context Diagram Generation

Run with:   streamlit run app.py

Architecture principle enforced throughout this app:
  DETERMINISTIC  = ingest, graph, diagrams, rules, export   (always runs)
  AI             = explanations and question parsing only   (optional layer)
Every number on screen traces back to a source row. The LLM never invents data.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import ai_layer
import diagram
import document_ingest
import graph_build
import ingest
import leanix_export
import rules

st.set_page_config(page_title="Documentation Guider",
                   page_icon="🕸️", layout="wide")

DEMO_SUCCESS_CONDITION = (
    "Upload a previously unseen copy of the EA workbook and, within 60 seconds, "
    "produce a correct context diagram for any selected application plus at "
    "least three data-quality findings that are traceable to specific source rows "
    "and are not already listed in KnownDataQualityGaps."
)


# ---------------------------------------------------------------------------
# Cached pipeline steps
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _load(file_bytes: bytes, name: str):
    import io
    ds = ingest.load_workbook(io.BytesIO(file_bytes), source_name=name)
    issues = ingest.validate(ds)
    return ds, issues


@st.cache_data(show_spinner=False)
def _analyse(_ds, enabled: tuple[str, ...]):
    g = graph_build.build_graph(_ds)
    findings = rules.run_all(_ds, g, enabled=set(enabled))
    findings = rules.mark_known(findings, _ds)
    return g, findings


def _init_state():
    for key, val in {
        "ds": None, "issues": None, "graph": None, "findings": None,
        "source_name": "", "ai_output": {}, "rejected": set(),
        "document_candidates": [], "accepted_candidates": [],
    }.items():
        st.session_state.setdefault(key, val)


_init_state()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("🕸️ Documentation Guider")
    st.caption("Documentation Guider · i.mobilothon 6.0")

    st.subheader("1 · Load architecture data")
    up = st.file_uploader(
        "EA workbook (.xlsx)", type=["xlsx"],
        help="The Auriga Motors synthetic EA dataset, or any workbook with the "
             "same sheet structure. Nothing is hard-coded to specific IDs.",
    )

    st.caption("No file to hand? Generate a synthetic one:")
    col_a, col_b = st.columns([2, 1])
    seed = col_a.number_input("seed", value=42, step=1, label_visibility="collapsed")
    if col_b.button("Generate", use_container_width=True):
        import io

        import make_sample_dataset as gen
        sheets = gen.generate(seed=int(seed))
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as xl:
            for nm, df in sheets.items():
                df.to_excel(xl, sheet_name=nm, index=False)
        st.session_state["generated"] = buf.getvalue()
        st.session_state["generated_name"] = f"synthetic_ea_seed{int(seed)}.xlsx"
        st.rerun()

    if st.session_state.get("generated") and not up:
        st.success(f"Using {st.session_state['generated_name']}")
        st.download_button("Download this workbook",
                           st.session_state["generated"],
                           st.session_state["generated_name"],
                           use_container_width=True)

    st.divider()
    st.subheader("2 · Rule engine")
    st.caption("All checks below are deterministic.")
    enabled_rules = []
    for rid, rname, _fn in rules.ALL_RULES:
        if st.checkbox(f"{rid} · {rname}", value=True, key=f"rule_{rid}"):
            enabled_rules.append(rid)

    st.divider()
    st.subheader("3 · AI layer (optional)")
    api_key = st.text_input("LLMaaS API key", type="password",
                            help="Leave empty to run fully deterministic. "
                                 "Everything except generated prose still works.")
    model = st.text_input("Model", value=ai_layer.DEFAULT_MODEL)
    base_url = st.text_input("Base URL", value=ai_layer.DEFAULT_BASE_URL)
    st.caption("Responses are cached on disk, so reruns never re-bill the same call.")
    st.divider()
    st.subheader("4 · Optional documents")
    doc_up = st.file_uploader("Interface/design document (.txt, .md, .docx, .pdf)",
                              type=["txt", "md", "docx", "pdf"])

llm = ai_layer.LLMClient(api_key=api_key, base_url=base_url, model=model)


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

file_bytes, file_name = None, ""
if up is not None:
    file_bytes, file_name = up.getvalue(), up.name
elif st.session_state.get("generated"):
    file_bytes = st.session_state["generated"]
    file_name = st.session_state["generated_name"]

if file_bytes is None:
    st.title("Documentation Guider")
    st.markdown(
        "Turn a LeanIX-style architecture workbook into **living context diagrams, "
        "traceable quality findings and answerable questions**."
    )
    c1, c2, c3 = st.columns(3)
    c1.info("**Deterministic core**\n\nIngest → graph → diagrams → rules. "
            "Runs with no LLM at all.")
    c2.info("**AI layer on top**\n\nExplains findings and answers questions. "
            "Never invents facts.")
    c3.info("**LeanIX-ready output**\n\nExports factsheets and relations even "
            "without live LeanIX access.")
    st.divider()
    st.subheader("Demo success condition")
    st.success(DEMO_SUCCESS_CONDITION)
    st.caption("⬅ Upload a workbook or generate a synthetic one to begin.")
    st.stop()

with st.spinner("Loading and validating workbook…"):
    ds, issues = _load(file_bytes, file_name)

if any(i["Severity"] == "BLOCKER" for i in issues):
    st.error("The workbook could not be processed.")
    st.dataframe(pd.DataFrame(issues), use_container_width=True, hide_index=True)
    st.stop()

with st.spinner("Building architecture graph and running rules…"):
    g, findings = _analyse(ds, tuple(enabled_rules))
if st.session_state["accepted_candidates"]:
    g = graph_build.merge_candidates(g, st.session_state["accepted_candidates"])

stats = graph_build.graph_stats(g)

st.title("Documentation Guider")
st.caption(f"Source: **{file_name}** · analysis is fully re-derived from this file")

m = st.columns(6)
m[0].metric("Applications", stats["Applications"])
m[1].metric("Undefined refs", stats["Undefined (ghost) nodes"])
m[2].metric("Interfaces", stats["Interface edges"])
m[3].metric("Information flows", stats["Information flows"])
m[4].metric("Domains", stats["Business domains"])
new_count = int((findings["Discovery"] == "NEW").sum()) if not findings.empty else 0
m[5].metric("Findings", len(findings), f"{new_count} new")

tab_diagram, tab_findings, tab_impact, tab_ask, tab_doc, tab_export, tab_how = st.tabs([
    "🕸️ Context diagram", "🔍 Quality & risk", "💥 Impact analysis",
    "💬 Ask the architecture", "📄 Document candidates", "📤 LeanIX export",
    "⚙️ How it works",
])


# ---------------------------------------------------------------------------
# Tab 1 - Context diagram
# ---------------------------------------------------------------------------

with tab_diagram:
    apps = sorted(
        [(d.get("name", n), n) for n, d in g.nodes(data=True) if not d.get("ghost")]
    )
    domains = sorted({d.get("domain") for _, d in g.nodes(data=True)})
    processes = sorted({p for _, d in g.nodes(data=True)
                        for p in (d.get("processes") or [])})

    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
    frame = c1.radio("Observation frame",
                     ["Application", "Business domain", "Business process"],
                     horizontal=True)

    focus_id = None
    if frame == "Application":
        label = c2.selectbox("Application", [a[0] for a in apps],
                             index=0 if apps else None)
        focus_id = dict(apps).get(label)
        depth = c3.slider("Hops", 1, 3, 1)
        sub = graph_build.context_subgraph(g, focus_id, depth)
        title = f"Context: {label} ({depth} hop{'s' if depth > 1 else ''})"
    elif frame == "Business domain":
        dom = c2.selectbox("Domain", domains)
        sub = graph_build.domain_subgraph(g, dom)
        title = f"Context: {dom} domain (+1 hop across boundaries)"
    else:
        if processes:
            proc = c2.selectbox("Process", processes)
            sub = graph_build.process_subgraph(g, proc)
            title = f"Context: applications supporting '{proc}'"
        else:
            sub = graph_build.context_subgraph(g, apps[0][1], 1)
            title = "No business processes mapped in this workbook"

    kinds = c4.multiselect("Edge types", list(graph_build.EDGE_KINDS),
                           default=list(graph_build.EDGE_KINDS))
    o1, o2 = st.columns([1, 1])
    show_labels = o1.checkbox("Show application names", value=True)
    label_edges = o2.checkbox("Label connections", value=False)

    if kinds:
        keep_nodes = set(sub.nodes())
        filtered = type(sub)()
        filtered.add_nodes_from((n, sub.nodes[n]) for n in keep_nodes)
        for s, t, d in sub.edges(data=True):
            if d.get("kind") in kinds:
                filtered.add_edge(s, t, **d)
        sub = filtered

    st.plotly_chart(
        diagram.render(sub, focus=focus_id, title=title,
                       show_labels=show_labels, label_edges=label_edges),
        use_container_width=True,
    )
    st.caption(diagram.legend_note())

    if focus_id:
        here = findings[findings["Entity"].str.contains(focus_id, regex=False, na=False)] \
            if not findings.empty else pd.DataFrame()

        st.divider()
        left, right = st.columns([1, 1])

        with left:
            st.subheader("Facts in this view")
            n = g.nodes[focus_id]
            st.markdown(
                f"**{n.get('name')}** · `{focus_id}`  \n"
                f"Domain: {n.get('domain')} · Criticality: {n.get('criticality')}  \n"
                f"Lifecycle: {n.get('lifecycle')} · Hosting: {n.get('hosting')}  \n"
                f"Owner: {n.get('owner') or '_none recorded_'}  \n"
                f"Consumes from **{g.in_degree(focus_id)}**, supplies "
                f"**{g.out_degree(focus_id)}** applications  \n"
                f"Processes: {', '.join(n.get('processes') or []) or '_none mapped_'}"
            )
            if len(here):
                st.warning(f"{len(here)} finding(s) raised in this context.")

        with right:
            st.subheader("AI briefing")
            st.caption("Generated from the facts on the left. Nothing else.")
            if st.button("Explain this context", key="btn_ctx"):
                facts = ai_layer.facts_for_context(sub, focus_id, here)
                try:
                    with st.spinner("Asking the model…"):
                        st.session_state["ai_output"][f"ctx_{focus_id}"] = \
                            llm.complete(ai_layer.prompt_context_summary(facts))
                except ai_layer.LLMUnavailable as exc:
                    st.info(str(exc))
            out = st.session_state["ai_output"].get(f"ctx_{focus_id}")
            if out:
                st.markdown(out)


# ---------------------------------------------------------------------------
# Tab 2 - Quality & risk
# ---------------------------------------------------------------------------

with tab_findings:
    if findings.empty:
        st.success("No findings raised by the enabled rules.")
    else:
        c1, c2, c3 = st.columns(3)
        sev_pick = c1.multiselect("Severity", list(rules.SEVERITY_ORDER),
                                  default=["CRITICAL", "HIGH", "MEDIUM"])
        cat_pick = c2.multiselect("Category", sorted(findings["Category"].unique()),
                                  default=sorted(findings["Category"].unique()))
        disc_pick = c3.multiselect("Discovery", ["NEW", "KNOWN"], default=["NEW", "KNOWN"])

        view = findings[
            findings["Severity"].isin(sev_pick)
            & findings["Category"].isin(cat_pick)
            & findings["Discovery"].isin(disc_pick)
        ]

        s = rules.summarise(findings)
        st.caption(" · ".join(f"**{k}**: {v}" for k, v in s.items()))
        st.info(
            f"**{new_count} of {len(findings)} findings are newly discovered** — they "
            "are not pre-declared in the KnownDataQualityGaps sheet. That sheet is "
            "documented as partial; these are the gaps the workbook does not tell you about."
        )

        st.caption("Human control: untick a finding to exclude it from the export.")
        display = view.copy()
        display.insert(0, "Accept", ~display["FindingID"].isin(st.session_state["rejected"]))

        edited = st.data_editor(
            display[["Accept", "Severity", "Discovery", "Category", "Title",
                     "Entity", "Evidence", "Recommendation", "SourceRows", "FindingID"]],
            use_container_width=True, hide_index=True, height=440,
            disabled=["Severity", "Discovery", "Category", "Title", "Entity",
                      "Evidence", "Recommendation", "SourceRows", "FindingID"],
            column_config={
                "Accept": st.column_config.CheckboxColumn(width="small"),
                "Evidence": st.column_config.TextColumn(width="large"),
                "Recommendation": st.column_config.TextColumn(width="large"),
                "FindingID": None,
            },
        )
        for _, row in edited.iterrows():
            if row["Accept"]:
                st.session_state["rejected"].discard(row["FindingID"])
            else:
                st.session_state["rejected"].add(row["FindingID"])

        st.divider()
        st.subheader("AI management summary")
        st.caption("Summarises the findings above. It cannot add findings of its own.")
        if st.button("Summarise findings", key="btn_digest"):
            try:
                with st.spinner("Asking the model…"):
                    st.session_state["ai_output"]["digest"] = llm.complete(
                        ai_layer.prompt_findings_digest(ai_layer.facts_for_findings(view))
                    )
            except ai_layer.LLMUnavailable as exc:
                st.info(str(exc))
        if st.session_state["ai_output"].get("digest"):
            st.markdown(st.session_state["ai_output"]["digest"])


# ---------------------------------------------------------------------------
# Tab 3 - Impact analysis
# ---------------------------------------------------------------------------

with tab_impact:
    st.subheader("If this application became unavailable, what breaks?")
    apps2 = sorted([(d.get("name", n), n) for n, d in g.nodes(data=True)
                    if not d.get("ghost")])
    pick_label = st.selectbox("Application", [a[0] for a in apps2], key="impact_app")
    pick_id = dict(apps2).get(pick_label)

    layers = graph_build.impact_of(g, pick_id)
    total = sum(len(v) for v in layers.values())

    c1, c2, c3 = st.columns(3)
    c1.metric("Applications affected", total)
    aff_procs = sorted({p for nodes in layers.values() for node in nodes
                        for p in (g.nodes[node].get("processes") or [])})
    c2.metric("Business processes affected", len(aff_procs))
    crit = sum(1 for nodes in layers.values() for node in nodes
               if str(g.nodes[node].get("criticality", "")).lower()
               in ("mission critical", "business critical"))
    c3.metric("Critical applications affected", crit)

    if not layers:
        st.success("Nothing downstream depends on this application.")
    else:
        rows = []
        for depth, nodes in sorted(layers.items()):
            for node in nodes:
                d = g.nodes[node]
                rows.append({
                    "Hop": depth, "Application": d.get("name"), "ID": node,
                    "Criticality": d.get("criticality"), "Domain": d.get("domain"),
                    "Processes": ", ".join(d.get("processes") or []) or "—",
                })
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                     hide_index=True, height=320)
        if aff_procs:
            st.caption("**Business processes in the blast radius:** " + ", ".join(aff_procs))

    st.divider()
    st.subheader("AI impact assessment")
    if st.button("Assess impact", key="btn_impact"):
        facts = ai_layer.facts_for_impact(g, pick_id, layers)
        try:
            with st.spinner("Asking the model…"):
                st.session_state["ai_output"][f"imp_{pick_id}"] = \
                    llm.complete(ai_layer.prompt_impact(facts))
        except ai_layer.LLMUnavailable as exc:
            st.info(str(exc))
    if st.session_state["ai_output"].get(f"imp_{pick_id}"):
        st.markdown(st.session_state["ai_output"][f"imp_{pick_id}"])


# ---------------------------------------------------------------------------
# Tab 4 - Ask the architecture
# ---------------------------------------------------------------------------

with tab_ask:
    st.subheader("Ask a question in plain language")
    st.caption(
        "The model only translates your question into filter parameters. "
        "The answer itself is computed from the graph, so it is always factual."
    )

    examples = [
        "Which systems consume data from the vehicle master?",
        "Show all applications involved in the order to delivery process",
        "Which mission critical applications have no owner?",
        "What is impacted if the payments gateway goes down?",
    ]
    st.caption("Try: " + " · ".join(f"_{e}_" for e in examples))

    q = st.text_input("Your question", placeholder=examples[0])

    if q:
        app_names = [d.get("name", n) for n, d in g.nodes(data=True)]
        domains_all = sorted({d.get("domain") for _, d in g.nodes(data=True)})
        procs_all = sorted({p for _, d in g.nodes(data=True)
                            for p in (d.get("processes") or [])})
        parsed = {}
        try:
            with st.spinner("Interpreting the question…"):
                raw = llm.complete(
                    ai_layer.prompt_parse_question(q, app_names, domains_all, procs_all),
                    max_tokens=300,
                )
            parsed = ai_layer.parse_json_response(raw)
        except ai_layer.LLMUnavailable as exc:
            st.info(f"{exc}\n\nUse the filters below instead.")

        if parsed:
            st.caption(f"Interpreted as: _{parsed.get('explain', '—')}_")
            with st.expander("Query parameters the model produced"):
                st.json(parsed)

        # --- deterministic execution of the parsed query --------------------
        name_to_id = {d.get("name", n): n for n, d in g.nodes(data=True)}
        target = parsed.get("application")
        tid = name_to_id.get(target) if target else None
        if tid is None and target:
            tid = target if target in g else None

        filt = parsed.get("filter") or {}
        result = None

        if tid:
            sub = graph_build.context_subgraph(g, tid, 1)
            st.plotly_chart(
                diagram.render(sub, focus=tid,
                               title=f"Context: {g.nodes[tid].get('name')}"),
                use_container_width=True,
            )
            consumers = [{"Application": g.nodes[t].get("name"), "ID": t,
                          "Via": d.get("kind"), "Criticality": g.nodes[t].get("criticality")}
                         for _s, t, d in g.out_edges(tid, data=True)]
            if consumers:
                st.markdown("**Consumes from this application:**")
                st.dataframe(pd.DataFrame(consumers).drop_duplicates(),
                             use_container_width=True, hide_index=True)
        elif parsed.get("process"):
            sub = graph_build.process_subgraph(g, parsed["process"])
            st.plotly_chart(
                diagram.render(sub, title=f"Applications supporting '{parsed['process']}'"),
                use_container_width=True)
        elif parsed.get("domain"):
            sub = graph_build.domain_subgraph(g, parsed["domain"])
            st.plotly_chart(
                diagram.render(sub, title=f"{parsed['domain']} domain"),
                use_container_width=True)

        if filt:
            rows = []
            for n, d in g.nodes(data=True):
                if d.get("ghost"):
                    continue
                if filt.get("criticality") and \
                        str(filt["criticality"]).lower() not in str(d.get("criticality", "")).lower():
                    continue
                if filt.get("lifecycle") and \
                        str(filt["lifecycle"]).lower() not in str(d.get("lifecycle", "")).lower():
                    continue
                if filt.get("hosting") and \
                        str(filt["hosting"]).lower() not in str(d.get("hosting", "")).lower():
                    continue
                if filt.get("missing_owner") and (d.get("owner") or "").strip():
                    continue
                rows.append({
                    "Application": d.get("name"), "ID": n,
                    "Criticality": d.get("criticality"), "Lifecycle": d.get("lifecycle"),
                    "Hosting": d.get("hosting"), "Owner": d.get("owner") or "— none —",
                })
            if rows:
                st.markdown(f"**{len(rows)} application(s) match:**")
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Tab 5 - Document candidates
# ---------------------------------------------------------------------------

with tab_doc:
    st.subheader("Document-derived architecture candidates")
    st.caption("Text is extracted locally. The optional model proposes candidates; "
               "nothing is merged until a human accepts it.")
    if doc_up is None:
        st.info("Upload a .txt, .md, .docx or .pdf document in the sidebar.")
    else:
        try:
            doc_text = document_ingest.extract_text(doc_up.getvalue(), doc_up.name)
            st.caption(f"Extracted {len(doc_text):,} characters from {doc_up.name}.")
            with st.expander("Preview extracted text"):
                st.text(doc_text[:6000])
            if st.button("Extract candidates with AI", key="extract_candidates"):
                try:
                    names = [d.get("name", n) for n, d in g.nodes(data=True)]
                    raw = llm.complete(document_ingest.candidate_prompt(doc_text, names),
                                       max_tokens=1200)
                    st.session_state["document_candidates"] = document_ingest.parse_candidates(raw)
                except ai_layer.LLMUnavailable as exc:
                    st.warning(str(exc))
        except Exception as exc:
            st.error(f"Could not extract document text: {exc}")

    candidates = st.session_state["document_candidates"]
    if candidates:
        frame = pd.DataFrame(candidates)
        frame.insert(0, "Accept", True)
        edited = st.data_editor(frame, key="candidate_editor", hide_index=True,
                                use_container_width=True)
        if st.button("Merge accepted candidates into graph", key="merge_candidates"):
            st.session_state["accepted_candidates"] = [
                row.drop(labels=["Accept"]).to_dict()
                for _, row in edited.iterrows() if bool(row.get("Accept"))
            ]
            st.success("Accepted candidates merged. Deterministic diagrams and exports "
                       "will include them on the next rerun.")
            st.rerun()

# ---------------------------------------------------------------------------
# Tab 6 - Export
# ---------------------------------------------------------------------------

with tab_export:
    st.subheader("LeanIX-ready output")
    st.markdown(
        "We do not have live LeanIX access during the hackathon, so the app emits "
        "the **exact payload a LeanIX import would consume**. If access lands, this "
        "same payload becomes the body of the API call. This is the documented "
        "fallback for our single biggest external dependency."
    )

    accepted = findings[~findings["FindingID"].isin(st.session_state["rejected"])] \
        if not findings.empty else pd.DataFrame()

    c1, c2, c3 = st.columns(3)
    c1.metric("Factsheets", g.number_of_nodes())
    c2.metric("Relations", g.number_of_edges())
    c3.metric("Accepted findings", len(accepted))

    with st.expander("Preview factsheets"):
        st.dataframe(leanix_export.factsheets(g).head(40),
                     use_container_width=True, hide_index=True)
    with st.expander("Preview relations"):
        rel = leanix_export.relations(g)
        st.dataframe(rel.head(40) if not rel.empty else pd.DataFrame(),
                     use_container_width=True, hide_index=True)

    st.download_button(
        "⬇ Download LeanIX import bundle (.zip)",
        leanix_export.build_zip(g, accepted, file_name),
        file_name="promptfactors_leanix_export.zip",
        mime="application/zip", use_container_width=True,
    )


# ---------------------------------------------------------------------------
# Tab 7 - How it works
# ---------------------------------------------------------------------------

with tab_how:
    st.subheader("AI vs deterministic boundary")
    st.caption("This split is deliberate and is the core design decision of the solution.")
    st.dataframe(pd.DataFrame([
        {"Step": "1 · Ingest & validate workbook", "Logic": "Deterministic",
         "Why": "Parsing and referential integrity must be exact and repeatable."},
        {"Step": "2 · Build architecture graph", "Logic": "Deterministic",
         "Why": "One backbone all views share, so nothing can disagree."},
        {"Step": "3 · Render context diagrams", "Logic": "Deterministic",
         "Why": "Fixed-seed layout: the same input always draws the same picture."},
        {"Step": "4 · Detect quality & risk findings", "Logic": "Deterministic",
         "Why": "Every finding traces to source rows and is auditable."},
        {"Step": "5 · Explain findings and context", "Logic": "AI",
         "Why": "Turning computed facts into readable language for stakeholders."},
        {"Step": "6 · Interpret natural-language questions", "Logic": "AI",
         "Why": "Only maps a question to filter parameters; the graph answers it."},
        {"Step": "7 · Produce LeanIX payload", "Logic": "Deterministic",
         "Why": "Exported architecture data must never contain generated content."},
    ]), use_container_width=True, hide_index=True)

    st.subheader("Failure modes and what the app does about them")
    st.dataframe(pd.DataFrame([
        {"Failure mode": "No LeanIX access",
         "Handling": "Export the LeanIX-shaped payload instead of writing live. "
                     "Demo never blocks on the dependency."},
        {"Failure mode": "No LLM key, or endpoint unreachable",
         "Handling": "Every deterministic feature still runs. Only generated prose "
                     "is unavailable, and the app says so explicitly."},
        {"Failure mode": "Workbook has different IDs / extra scenarios",
         "Handling": "Sheets and columns are matched by name; no row ID is ever "
                     "hard-coded. Generate a second seed to prove it."},
        {"Failure mode": "Broken references in the data",
         "Handling": "Ghost nodes are rendered in black rather than dropped, so "
                     "the gap is visible instead of silently hidden."},
        {"Failure mode": "A rule crashes on unexpected data",
         "Handling": "Each rule is isolated; a failing rule reports itself and the "
                     "remaining rules still run."},
        {"Failure mode": "LLM cost overrun on a fixed budget",
         "Handling": "All responses cached on disk and only fired on explicit "
                     "button press, never on page rerun."},
    ]), use_container_width=True, hide_index=True)

    st.subheader("Trade-off we made")
    st.info(
        "**The workbook remains deterministic; document extraction is review-first.** "
        "The optional model may propose candidates from extracted text, but a human "
        "must accept rows before they are merged into the graph. Explanations and "
        "question parsing likewise receive facts or parameters, never authority "
        "to invent architecture."
    )

    st.subheader("Demo success condition")
    st.success(DEMO_SUCCESS_CONDITION)

    st.subheader("Workbook load report")
    st.dataframe(pd.DataFrame(ds.load_report), use_container_width=True, hide_index=True)
    st.subheader("Structural validation")
    st.dataframe(pd.DataFrame(issues), use_container_width=True, hide_index=True)
