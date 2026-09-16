"""Fast deterministic smoke test; does not call an LLM or Streamlit."""
import io
import pandas as pd
import ingest, graph_build, rules, leanix_export, document_ingest
import make_sample_dataset

sheets = make_sample_dataset.generate(seed=42, n_apps=20)
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as w:
    for name, df in sheets.items(): df.to_excel(w, sheet_name=name, index=False)
ds = ingest.load_workbook(io.BytesIO(buf.getvalue()), "smoke.xlsx")
assert not any(x["Severity"] == "BLOCKER" for x in ingest.validate(ds))
g = graph_build.build_graph(ds)
f = rules.mark_known(rules.run_all(ds, g), ds)
assert len(g) >= 20 and not f.empty
assert b"manifest.json" in leanix_export.build_zip(g, f, "smoke.xlsx")
assert document_ingest.extract_text(b"hello", "note.txt") == "hello"
known_name = next(d["name"] for _, d in g.nodes(data=True) if not d.get("ghost"))
candidate_graph = graph_build.merge_candidates(g, [
    {"candidate_type": "relationship", "source_application": "New app",
     "target_application": known_name, "name": "document link"},
    {"candidate_type": "application", "name": "New app",
     "description": "reviewed candidate"},
    {"candidate_type": "application", "name": "Existing app"},
])
assert any(d.get("candidate") for _, d in candidate_graph.nodes(data=True))
assert any(d.get("candidate") for _, _, d in candidate_graph.edges(data=True))
print(f"OK: {len(g)} graph nodes, {len(g.edges)} edges, {len(f)} findings")
