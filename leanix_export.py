"""
leanix_export.py - DETERMINISTIC layer.

Produces LeanIX-shaped import payloads from the graph plus the findings the
user has accepted.

Why this exists: we do not have LeanIX API access during the hackathon. Rather
than block on it, the app emits the exact payload a LeanIX import would consume.
If access lands, this becomes the body of an API call; if it does not, the
export file is the demonstrable deliverable. This is the documented fallback
for our single biggest external dependency.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime

import networkx as nx
import pandas as pd


def factsheets(g: nx.MultiDiGraph) -> pd.DataFrame:
    """Application factsheets in LeanIX import shape."""
    rows = []
    for node, d in g.nodes(data=True):
        rows.append({
            "type": "Application",
            "externalId": node,
            "name": d.get("name", node),
            "description": d.get("description", ""),
            "businessDomain": d.get("domain", ""),
            "businessCriticality": d.get("criticality", ""),
            "lifecycle": d.get("lifecycle", ""),
            "lifecycleEnd": ("" if d.get("lifecycle_end") is None
                             else str(d.get("lifecycle_end"))),
            "hosting": d.get("hosting", ""),
            "vendorType": d.get("vendor_type", ""),
            "owner": d.get("owner", ""),
            "custodian": d.get("custodian", ""),
            "businessOwner": d.get("business_owner", ""),
            "supportGroup": d.get("support_group", ""),
            "supportedProcesses": "; ".join(d.get("processes") or []),
            "resolvedInSource": "no" if d.get("ghost") else "yes",
        })
    return pd.DataFrame(rows).sort_values("externalId").reset_index(drop=True)


def relations(g: nx.MultiDiGraph) -> pd.DataFrame:
    """Relation rows: one per typed edge."""
    kind_map = {
        "relationship": "relApplicationToApplication",
        "interface": "relApplicationToInterface",
        "information_flow": "relApplicationToDataObject",
    }
    rows = []
    for s, t, d in g.edges(data=True):
        kind = d.get("kind", "relationship")
        rows.append({
            "relationType": kind_map.get(kind, kind),
            "sourceExternalId": s,
            "targetExternalId": t,
            "label": d.get("label", ""),
            "interfaceId": d.get("interface_id", ""),
            "protocol": d.get("protocol", ""),
            "format": d.get("fmt", ""),
            "frequency": d.get("frequency", ""),
            "status": d.get("status", ""),
            "classification": d.get("classification", ""),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(["relationType", "sourceExternalId"]).reset_index(drop=True)


def findings_payload(accepted: pd.DataFrame) -> pd.DataFrame:
    """Accepted findings, shaped as LeanIX quality-seal / survey input."""
    if accepted is None or accepted.empty:
        return pd.DataFrame()
    cols = ["FindingID", "Rule", "Severity", "Category", "Title", "Entity",
            "Evidence", "Recommendation", "SourceRows", "Origin"]
    keep = [c for c in cols if c in accepted.columns]
    out = accepted[keep].copy()
    out["reviewedBy"] = "human review in PromptFactors app"
    out["reviewedAt"] = datetime.now().isoformat(timespec="seconds")
    return out.reset_index(drop=True)


def manifest(g: nx.MultiDiGraph, accepted: pd.DataFrame, source_name: str) -> dict:
    return {
        "generatedBy": "PromptFactors - AI + LeanIX Context Intelligence",
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "sourceWorkbook": source_name,
        "counts": {
            "applications": g.number_of_nodes(),
            "relations": g.number_of_edges(),
            "acceptedFindings": 0 if accepted is None or accepted.empty else len(accepted),
        },
        "provenance": (
            "All factsheets and relations are derived deterministically from the "
            "source workbook. Findings are produced by rule evaluation, not by a "
            "language model. Any AI-generated text in the app is explanatory only "
            "and is not included in this payload."
        ),
        "intendedUse": (
            "Import into LeanIX as application factsheets plus relations. Findings "
            "are intended as review tasks against the corresponding factsheets."
        ),
    }


def build_zip(g: nx.MultiDiGraph, accepted: pd.DataFrame, source_name: str) -> bytes:
    """Bundle the whole export as a single downloadable zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("leanix_factsheets.csv", factsheets(g).to_csv(index=False))
        rel = relations(g)
        z.writestr("leanix_relations.csv",
                   rel.to_csv(index=False) if not rel.empty else "")
        fnd = findings_payload(accepted)
        z.writestr("accepted_findings.csv",
                   fnd.to_csv(index=False) if not fnd.empty else "")
        z.writestr("manifest.json",
                   json.dumps(manifest(g, accepted, source_name), indent=2))
    buf.seek(0)
    return buf.read()
