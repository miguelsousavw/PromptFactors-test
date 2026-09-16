"""PromptFactors FSD workspace.

The primary workflow is intentionally one upload control: upload an FSD and
review its deterministic integration profile, context diagram and chat.
"""
from __future__ import annotations

import streamlit as st

import ai_layer
import diagram
import document_ingest
import fsd_workflow

st.set_page_config(page_title="FSD Integration Workspace", page_icon="🔗", layout="wide")


def _init_state() -> None:
    st.session_state.setdefault("fsd_bytes", None)
    st.session_state.setdefault("fsd_name", "")
    st.session_state.setdefault("fsd_profile", None)
    st.session_state.setdefault("fsd_text", "")
    st.session_state.setdefault("chat", [])


_init_state()

with st.sidebar:
    st.title("🔗 FSD workspace")
    st.caption("Single-document integration review")
    upload = st.file_uploader(
        "Upload FSD",
        type=["docx", "pdf", "txt", "md"],
        help="Upload a Functional Specification Document to start the workflow.",
    )
    if upload is not None:
        raw = upload.getvalue()
        if raw != st.session_state["fsd_bytes"] or upload.name != st.session_state["fsd_name"]:
            st.session_state.update(
                fsd_bytes=raw, fsd_name=upload.name, fsd_profile=None,
                fsd_text="", chat=[],
            )


if not st.session_state["fsd_bytes"]:
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
def _extract(data: bytes, filename: str, parser_version: str = "mapping-v2"):
    text = document_ingest.extract_text(data, filename)
    tables = document_ingest.extract_tables(data, filename)
    embedded = document_ingest.extract_embedded_workbooks(data, filename)
    return text, fsd_workflow.parse_fsd(text, tables, filename), embedded


with st.spinner("Extracting FSD and deriving integration profile…"):
    try:
        text, profile, embedded_workbooks = _extract(
            st.session_state["fsd_bytes"], st.session_state["fsd_name"]
        )
        embedded_fields = fsd_workflow.embedded_mapping_fields(embedded_workbooks)
        if embedded_fields:
            profile.mapping_fields = embedded_fields
    except Exception as exc:
        st.error(f"Could not read this FSD: {exc}")
        st.stop()
st.session_state["fsd_text"] = text
st.session_state["fsd_profile"] = profile
graph = fsd_workflow.build_integration_graph(profile)

st.title(profile.integration_name)
st.caption(f"Source document: **{st.session_state['fsd_name']}** · deterministic extraction")
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
                    grouped.setdefault(item["Source entity"] or "Other", []).append(item)
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
                            f"────────</span><span class='mapping-field-copy'>"
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
                    ".mapping-entity-row{display:grid;grid-template-columns:minmax(180px,28%) minmax(0,1fr);"
                    "column-gap:28px;align-items:start;margin:0 0 26px;}"
                    ".mapping-entity{display:flex;align-items:center;gap:10px;font-size:1.05rem;"
                    "font-weight:700;color:#1D2939;padding-top:7px;white-space:nowrap;}"
                    ".mapping-dot{color:#667085;font-size:.8rem;}"
                    ".mapping-fields{display:flex;flex-direction:column;gap:11px;min-width:0;}"
                    ".mapping-field{display:flex;align-items:flex-start;gap:10px;min-width:0;"
                    "font-size:.93rem;color:#344054;line-height:1.35;}"
                    ".mapping-line{color:#98A2B3;letter-spacing:-2px;white-space:nowrap;padding-top:2px;}"
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
    st.caption("Leave the key blank for the deterministic workflow above.")
    key = st.text_input("LLMaaS API key", type="password")
    if st.button("Explain this integration") and key:
        client = ai_layer.LLMClient(api_key=key, base_url=ai_layer.DEFAULT_BASE_URL,
                                    model=ai_layer.DEFAULT_MODEL)
        facts = "\n".join(f"{k}: {v}" for k, v in profile.as_dict().items())
        try:
            st.markdown(client.complete(
                "Explain this integration using only these facts:\n" + facts))
        except ai_layer.LLMUnavailable as exc:
            st.warning(str(exc))
