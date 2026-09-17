"""PromptFactors FSD workspace.

The primary workflow is intentionally one upload control: upload an FSD and
review its deterministic integration profile, context diagram and chat.
"""
from __future__ import annotations

import hashlib
import os

import streamlit as st

import ai_layer
import diagram
import document_ingest
import fsd_workflow

st.set_page_config(page_title="FSD Integration Workspace", page_icon="🔗", layout="wide")

st.markdown(
    """
    <style>
    :root {
        --vw-deep-blue: #001E50;
        --vw-green: #00B956;
        --vw-neon: #00FF87;
        --vw-ink: #172B4D;
        --vw-muted: #667085;
        --vw-surface: #FFFFFF;
        --vw-background: #F5F7FA;
        --vw-border: #D9E2EC;
    }
    .stApp { background: var(--vw-background); color: var(--vw-ink); }
    [data-testid="stSidebar"] {
        background: var(--vw-deep-blue);
        border-right: 0;
    }
    [data-testid="stSidebar"] * { color: #FFFFFF !important; }
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
        background: rgba(255,255,255,.1);
        border: 1px dashed rgba(255,255,255,.55);
    }
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {
        background: var(--vw-green);
        color: var(--vw-deep-blue) !important;
        border: 0;
    }
    h1, h2, h3 { color: var(--vw-deep-blue); letter-spacing: -0.02em; }
    h1 { font-weight: 750; }
    [data-testid="stMetric"] {
        background: var(--vw-surface);
        border: 1px solid var(--vw-border);
        border-radius: 12px;
        padding: 14px 16px;
        box-shadow: 0 2px 8px rgba(0,30,80,.05);
    }
    [data-testid="stMetricLabel"] { color: var(--vw-muted); }
    [data-testid="stMetricValue"] { color: var(--vw-deep-blue); }
    .stButton > button, [data-testid="stDownloadButton"] button {
        background: var(--vw-deep-blue);
        color: #FFFFFF;
        border: 0;
        border-radius: 8px;
        font-weight: 650;
    }
    .stButton > button:hover, [data-testid="stDownloadButton"] button:hover {
        background: #123B73;
        color: #FFFFFF;
    }
    [data-testid="stAlert"] { border-radius: 10px; }
    [data-testid="stExpander"] {
        background: var(--vw-surface);
        border: 1px solid var(--vw-border);
        border-radius: 12px;
    }
    .mapping-visual {
        background: var(--vw-surface);
        border: 1px solid var(--vw-border);
        border-radius: 12px;
        padding: 22px 24px 10px;
    }
    .mapping-entity { color: var(--vw-deep-blue) !important; }
    .mapping-dot, .mapping-line { color: var(--vw-green) !important; }
    .mapping-target { color: var(--vw-muted) !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _init_state() -> None:
    # Keep the legacy keys: bookmarks from the single-FSD workflow remain
    # readable while the document registry handles any number of uploads.
    st.session_state.setdefault("fsd_bytes", None)
    st.session_state.setdefault("fsd_name", "")
    st.session_state.setdefault("fsd_profile", None)
    st.session_state.setdefault("fsd_text", "")
    st.session_state.setdefault("chat", [])
    st.session_state.setdefault("fsd_documents", {})
    st.session_state.setdefault("fsd_workspace", 0)
    st.session_state.setdefault("fsd_chats", {})
    st.session_state.setdefault("fsd_selection", "group:0")


_init_state()

with st.sidebar:
    st.title("🔗 FSD workspace")
    st.caption("Multi-document integration review")
    upload = st.file_uploader(
        "Upload FSDs",
        type=["docx", "pdf", "txt", "md"],
        accept_multiple_files=True,
        help="Upload one or more Functional Specification Documents.",
    )
    if upload is not None:
        uploaded = {}
        for item in upload:
            raw = item.getvalue()
            digest = hashlib.sha256(raw).hexdigest()
            uploaded[digest] = {"bytes": raw, "name": item.name, "digest": digest}
        old = st.session_state["fsd_documents"]
        if uploaded != old:
            st.session_state["fsd_documents"] = uploaded
            st.session_state["fsd_workspace"] = 0
            st.session_state["fsd_profile"] = None
            st.session_state["fsd_text"] = ""
            st.session_state["chat"] = []
            st.session_state["fsd_chats"] = {}
            st.session_state["fsd_selection"] = "group:0"
    use_llm_extraction = st.checkbox(
        "Use VW LLM for FSD extraction",
        value=bool(os.environ.get("VW_LLM_API_KEY")),
        help="Send extracted FSD text to the configured VW Responses API. "
             "The deterministic parser remains the fallback.",
    )


if not st.session_state["fsd_documents"]:
    st.title("FSD Integration Workspace")
    st.subheader("Upload an FSD to begin")
    st.markdown(
        "Turn a Functional Specification Document into a focused, LeanIX-style "
        "integration view. Text extraction, metadata and the diagram are deterministic "
        "and work without an API key."
    )
    st.info("Use the **Upload FSD** control in the sidebar. Supported: DOCX, PDF, TXT and Markdown.")
    st.stop()


@st.cache_data(show_spinner=False)
def _extract(data: bytes, filename: str, use_llm: bool,
             parser_version: str = "mapping-v3"):
    text = document_ingest.extract_text(data, filename)
    tables = document_ingest.extract_tables(data, filename)
    embedded = document_ingest.extract_embedded_workbooks(data, filename)
    profile = fsd_workflow.parse_fsd(text, tables, filename)
    llm_response = ""
    if use_llm:
        client = ai_layer.VWResponsesClient()
        if client.configured:
            try:
                llm_response = client.extract(
                    ai_layer.prompt_extract_fsd(text, filename)
                )
                result = ai_layer.parse_json_response(llm_response)
                if result:
                    profile = fsd_workflow.profile_from_llm(result, filename)
            except ai_layer.LLMUnavailable:
                # Keep the deterministic parser as an explicit, usable fallback.
                llm_response = ""
    embedded_fields = fsd_workflow.embedded_mapping_fields(embedded)
    if embedded_fields:
        profile.mapping_fields = embedded_fields
    return text, profile, embedded, llm_response

with st.spinner("Extracting FSDs and deriving integration profiles…"):
    documents = []
    try:
        for document in st.session_state["fsd_documents"].values():
            text, profile, embedded, llm_response = _extract(
                document["bytes"], document["name"], use_llm_extraction
            )
            documents.append({
                **document, "text": text, "profile": profile, "embedded": embedded,
                "llm_response": llm_response,
            })
    except ai_layer.LLMUnavailable as exc:
        st.warning(f"LLM extraction unavailable; deterministic extraction was not used for this run: {exc}")
        st.stop()
    except Exception as exc:
        st.error(f"Could not read this FSD: {exc}")
        st.stop()

groups = fsd_workflow.group_fsd_profiles([item["profile"] for item in documents])
with st.sidebar:
    if len(documents) > 1:
        st.subheader("Choose an uploaded FSD")
        st.caption("Switch directly between uploaded documents, or review connected FSDs together.")
        document_options = [
            (
                f"document:{index}",
                f"FSD · {document['name']}",
            )
            for index, document in enumerate(documents)
        ]
        workspace_options = [
            (
                f"group:{index}",
                "Combined workspace · " + " · ".join(
                    documents[[x["profile"] for x in documents].index(profile)]["name"]
                    for profile in group
                ),
            )
            for index, group in enumerate(groups)
            if len(group) > 1
        ]
        options = document_options + workspace_options
        option_keys = [key for key, _ in options]
        if st.session_state["fsd_selection"] not in option_keys:
            st.session_state["fsd_selection"] = option_keys[0]
        selected_key = st.selectbox(
            "FSD view",
            option_keys,
            index=option_keys.index(st.session_state["fsd_selection"]),
            format_func=lambda key: dict(options)[key],
        )
        st.session_state["fsd_selection"] = selected_key

selection = st.session_state["fsd_selection"]
if selection.startswith("document:"):
    selected_document_index = int(selection.split(":", 1)[1])
    active_group = [documents[selected_document_index]["profile"]]
    active_workspace_index = next(
        index for index, group in enumerate(groups)
        if documents[selected_document_index]["profile"] in group
    )
else:
    active_workspace_index = int(selection.split(":", 1)[1])
    active_group = groups[active_workspace_index]
st.session_state["fsd_workspace"] = active_workspace_index
active_profiles = list(active_group)
active_documents = [
    document for document in documents if document["profile"] in active_profiles
]
profile = fsd_workflow.merge_fsd_profiles(active_profiles)
text = "\n\n".join(document["text"] for document in active_documents)
embedded_workbooks = [
    workbook for document in active_documents for workbook in document["embedded"]
]
graph = fsd_workflow.build_combined_graph(active_profiles)
workspace_key = "|".join(document["digest"] for document in active_documents)
st.session_state["fsd_text"] = text
st.session_state["fsd_profile"] = profile
st.session_state["fsd_name"] = ", ".join(document["name"] for document in active_documents)
st.session_state["chat"] = st.session_state["fsd_chats"].setdefault(workspace_key, [])

st.title(profile.integration_name)
st.caption(f"Source document(s): **{st.session_state['fsd_name']}** · deterministic extraction")
llm_responses = [
    (document["name"], document["llm_response"])
    for document in active_documents
    if document.get("llm_response")
]
if llm_responses:
    with st.expander(
        f"LLM response received · {len(llm_responses)} request"
        f"{'s' if len(llm_responses) != 1 else ''}",
        expanded=True,
    ):
        st.success("The FSD extraction request completed successfully.")
        for filename, response in llm_responses:
            st.markdown(f"**Response for `{filename}`**")
            st.text_area(
                "Raw JSON returned by the LLM",
                response,
                height=280,
                key=f"llm-response-{hashlib.sha256(filename.encode()).hexdigest()[:12]}",
                disabled=True,
                label_visibility="collapsed",
            )
if len(active_documents) > 1:
    st.success(f"Combined workspace: {len(active_documents)} connected FSDs")
if len(documents) > 1:
    with st.expander("Uploaded FSD waterfall", expanded=len(groups) > 1):
        for index, group in enumerate(groups, 1):
            names = [
                document["name"] for document in documents
                if document["profile"] in group
            ]
            marker = " ← current" if any(profile in active_group for profile in group) else ""
            st.write(f"**Workspace {index}**{marker}: " + " · ".join(names))
st.markdown(profile.description)

cards = st.columns(4)
cards[0].metric("Criticality", profile.criticality)
cards[1].metric("Schedule", profile.schedule)
cards[2].metric("Interface", profile.interface_type)
cards[3].metric("Owner", profile.owner)

st.divider()
left, right = st.columns([1, 2])
with left:
    st.subheader("Integration at a glance")
    st.write(f"**Source**  \n{profile.source_system}")
    st.write(f"**Target**  \n{profile.target_system}")
    st.write(f"**Middleware**  \n{profile.middleware}")
    st.write(f"**Encryption**  \n{profile.encryption}")
    st.write(f"**Data objects**  \n{', '.join(profile.data_objects) or 'Not explicitly listed'}")
    with st.expander("Extracted FSD text"):
        st.text(text[:12000])

with right:
    st.subheader("How this integration works")
    st.caption("Follow the arrows from left to right: the source sends information "
               "through each integration service to the target.")
    diagram_mode = st.radio(
        "Diagram mode",
        ["Architectural/Interface", "Information flow"],
        horizontal=True,
        help="Architectural/Interface shows applications, middleware and interfaces. "
             "Information flow shows data objects and their information-flow edges.",
    )
    visible_graph = fsd_workflow.diagram_subgraph(graph, diagram_mode)
    mode_copy = (
        "Systems and middleware: the solid blue path shows the connection route."
        if diagram_mode == "Architectural/Interface"
        else "Information being moved: the dashed green paths show what is extracted and delivered."
    )
    st.info(mode_copy)
    st.plotly_chart(
        diagram.render(visible_graph, focus="middleware-0",
                       title=f"{profile.source_system}  →  {profile.target_system}",
                       show_labels=True, label_edges=True),
        use_container_width=True,
    )
    st.caption(
        "Hover over a node for the documented owner and context. "
        "The diagram is derived deterministically from this FSD."
    )
    st.caption(diagram.legend_note())

with st.expander("Mapping sheet", expanded=True):
    if embedded_workbooks:
        st.caption(
            "A visual view of the Excel mapping workbook embedded in this FSD."
        )
        for workbook in embedded_workbooks:
            if workbook.get("mapping"):
                grouped: dict[str, list[dict]] = {}
                for item in workbook["mapping"]:
                    entity = fsd_workflow.normalize_mapping_entity(item["Source entity"])
                    grouped.setdefault(entity, []).append(item)
                visual_rows = []
                for entity, fields in grouped.items():
                    field_lines = []
                    for field in fields:
                        source_field = field["Source field"] or "Unnamed source field"
                        target_field = field["Target field"] or ""
                        required = "required" if field["Required"] else ""
                        detail = (
                            f"<span class='mapping-target'>{target_field}"
                            f"{' · ' if required else ''}{required}</span>"
                            if target_field else ""
                        )
                        field_lines.append(
                            f"<div class='mapping-field'><span class='mapping-line'>"
                            f"●</span><span class='mapping-field-copy'>"
                            f"<b>{source_field}</b>{detail}</span></div>"
                        )
                    visual_rows.append(
                        f"<div class='mapping-entity-row'>"
                        f"<div class='mapping-entity'><span class='mapping-dot'>●</span>"
                        f"<span>{entity}</span></div>"
                        f"<div class='mapping-fields'>{''.join(field_lines)}</div>"
                        f"</div>"
                    )
                st.markdown(
                    "<style>"
                    ".mapping-visual{padding:18px 10px 8px;overflow-x:auto;}"
                    ".mapping-entity-row{display:grid;grid-template-columns:minmax(140px,18%) minmax(0,1fr);"
                    "column-gap:4px;align-items:start;margin:0 0 22px;}"
                    ".mapping-entity{display:flex;align-items:center;gap:10px;font-size:1.05rem;"
                    "font-weight:700;color:#1D2939;padding-top:7px;white-space:nowrap;}"
                    ".mapping-dot{color:#667085;font-size:.8rem;}"
                    ".mapping-fields{display:flex;flex-direction:column;gap:11px;min-width:0;}"
                    ".mapping-field{display:flex;align-items:flex-start;gap:10px;min-width:0;"
                    "font-size:.93rem;color:#344054;line-height:1.35;}"
                    ".mapping-line{color:#667085;white-space:nowrap;padding-top:2px;font-size:.58rem;}"
                    ".mapping-field-copy{min-width:0;overflow-wrap:anywhere;}"
                    ".mapping-target{display:block;color:#667085;font-size:.78rem;font-weight:400;margin-top:3px;}"
                    "@media(max-width:700px){.mapping-entity-row{grid-template-columns:1fr;row-gap:8px;"
                    "margin-bottom:20px}.mapping-fields{padding-left:10px}}"
                    "</style><div class='mapping-visual'>"
                    + "".join(visual_rows)
                    + "</div>",
                    unsafe_allow_html=True,
                )
            else:
                for sheet_name, rows in workbook["sheets"].items():
                    st.markdown(f"**Worksheet: {sheet_name}**")
                    st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No embedded Excel mapping workbook was found in this FSD.")

st.divider()
st.subheader("Ask about this integration")
st.caption(
    "Ask a question in plain language. Answers use only facts extracted from "
    "this FSD, so they remain traceable and safe to review."
)

if not st.session_state["chat"]:
    st.info(
        "Try asking: **What is the source system?** · **What data is exchanged?** · "
        "**How often does it run?** · **Who owns it?**"
    )

with st.container(border=True):
    for item in st.session_state["chat"]:
        with st.chat_message(item["role"]):
            st.markdown(item["content"])

    question = st.chat_input(
        "Ask about the source, target, middleware, data, schedule or owner…"
    )
    if question:
        st.session_state["chat"].append({"role": "user", "content": question})
        answer = fsd_workflow.answer_question(question, profile)
        st.session_state["chat"].append({"role": "assistant", "content": answer})
        st.rerun()

with st.expander("Optional AI phrasing"):
    st.caption(
        "Leave the key blank for the deterministic workflow above. "
        "Open WebUI must expose its OpenAI-compatible API to this app."
    )
    ai_base_url = st.text_input(
        "Open WebUI API base URL",
        value=os.environ.get("LLMAAS_BASE_URL", ai_layer.DEFAULT_BASE_URL),
        help="Use the Open WebUI server URL ending in /api, for example "
             "https://openwebui.example.com/api. The app adds /chat/completions.",
    )
    ai_model = st.text_input(
        "Model",
        value=os.environ.get("LLMAAS_MODEL", ai_layer.DEFAULT_MODEL),
        help="The model identifier configured in Open WebUI.",
    )
    key = st.text_input(
        "Open WebUI API key",
        value=os.environ.get("LLMAAS_API_KEY", ""),
        type="password",
        help="Create this in Open WebUI under Settings → Account → API Keys.",
    )
    if st.button("Explain this integration") and key:
        client = ai_layer.LLMClient(
            api_key=key,
            base_url=ai_base_url,
            model=ai_model,
        )
        facts = "\n".join(f"{k}: {v}" for k, v in profile.as_dict().items())
        try:
            st.markdown(client.complete(
                "Explain this integration using only these facts:\n" + facts))
        except ai_layer.LLMUnavailable as exc:
            st.warning(str(exc))
