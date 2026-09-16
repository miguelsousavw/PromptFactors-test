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
def _extract(data: bytes, filename: str):
    text = document_ingest.extract_text(data, filename)
    tables = document_ingest.extract_tables(data, filename)
    return text, fsd_workflow.parse_fsd(text, tables, filename)


with st.spinner("Extracting FSD and deriving integration profile…"):
    try:
        text, profile = _extract(st.session_state["fsd_bytes"], st.session_state["fsd_name"])
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
    st.subheader("LeanIX-style integration context")
    diagram_mode = st.radio(
        "Diagram mode",
        ["Architectural/Interface", "Information flow"],
        horizontal=True,
        help="Architectural/Interface shows applications, middleware and interfaces. "
             "Information flow shows data objects and their information-flow edges.",
    )
    visible_graph = fsd_workflow.diagram_subgraph(graph, diagram_mode)
    st.plotly_chart(
        diagram.render(visible_graph, focus="middleware-0",
                       title=f"{profile.source_system} → {profile.target_system} · {diagram_mode}",
                       show_labels=True, label_edges=True),
        use_container_width=True,
    )
    st.caption(
        "Architectural/Interface: applications + middleware with interface edges. "
        "Information flow: participants + data objects with information-flow edges."
    )

st.divider()
st.subheader("Ask about this integration")
st.caption("Answers are computed from extracted facts. Optional AI can improve phrasing, but never supplies facts.")
for item in st.session_state["chat"]:
    with st.chat_message(item["role"]):
        st.markdown(item["content"])
question = st.chat_input("e.g. What is the source system, schedule or owner?")
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
