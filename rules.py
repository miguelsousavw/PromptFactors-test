"""
rules.py - DETERMINISTIC layer.

Every finding produced here comes from a join or a graph traversal. No LLM is
involved, so findings are reproducible, auditable and always traceable back to
source rows. This is deliberate: the AI layer explains findings, it never
invents them.

Findings are derived from patterns, never from hard-coded IDs, so the same
rules fire on a modified copy of the workbook with different IDs.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

import networkx as nx
import pandas as pd

from ingest import EADataset

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}

EOL_MARKERS = ("end of life", "eol", "retired", "sunset", "decommission")
ACTIVE_MARKERS = ("active", "phase-in", "phase in", "production", "live")
INACTIVE_IF_MARKERS = ("inactive", "retired", "deprecated", "decommissioned", "planned")
HIGH_CRIT = ("mission critical", "business critical")
EXPOSED_HOSTING = ("saas", "public cloud")
SENSITIVE = ("confidential", "restricted", "personal", "pii", "secret", "sensitive")


def _finding(rule_id, severity, category, title, entity, evidence, recommendation,
             source_rows=""):
    return {
        "FindingID": f"{rule_id}-{hashlib.sha1('|'.join(map(str, [severity, category, title, entity, source_rows])).encode()).hexdigest()[:10].upper()}",
        "Rule": rule_id,
        "Severity": severity,
        "Category": category,
        "Title": title,
        "Entity": entity,
        "Evidence": evidence,
        "Recommendation": recommendation,
        "SourceRows": source_rows,
        "Origin": "deterministic",
    }


def _s(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def _lower(v) -> str:
    return _s(v).lower()


def _is_blank(v) -> bool:
    return _s(v) == ""


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------

def rule_broken_references(ds: EADataset, g: nx.MultiDiGraph) -> list[dict]:
    """R01 - foreign keys pointing at applications that do not exist."""
    out = []
    known = ds.app_ids()
    checks = [
        ("Relationships", ["SourceApplicationID", "TargetApplicationID"]),
        ("Interfaces", ["ProviderApplicationID", "ConsumerApplicationID"]),
        ("InformationObjects", ["SourceApplicationID", "TargetApplicationID"]),
        ("BusinessProcesses", ["SupportingApplicationID"]),
        ("ApplicationOwnership", ["ApplicationID"]),
    ]
    dangling: dict[str, list[str]] = {}
    for sheet, cols in checks:
        df = ds.df(sheet)
        if df.empty:
            continue
        for col in cols:
            if col not in df.columns:
                continue
            for idx, val in df[col].items():
                v = _s(val)
                if v and v not in known:
                    dangling.setdefault(v, []).append(f"{sheet}.{col} row {idx + 2}")

    for bad_id, refs in sorted(dangling.items()):
        out.append(_finding(
            "R01", "CRITICAL", "Referential integrity",
            "Reference to an application that does not exist",
            bad_id,
            f"'{bad_id}' is referenced {len(refs)} time(s) but has no row in the "
            f"Applications sheet. Any diagram containing it is incomplete.",
            "Either create the missing application factsheet or correct the "
            "referencing rows. Until then, dependency and impact analysis "
            "through this node is unreliable.",
            "; ".join(refs[:8]) + (" ..." if len(refs) > 8 else ""),
        ))
    return out


def rule_missing_ownership(ds: EADataset, g: nx.MultiDiGraph) -> list[dict]:
    """R02 - applications with no accountable owner."""
    out = []
    own = ds.df("ApplicationOwnership")
    owned: dict[str, dict] = {}
    if not own.empty and "ApplicationID" in own.columns:
        for _, row in own.iterrows():
            owned[_s(row.get("ApplicationID"))] = row.to_dict()

    for node, data in g.nodes(data=True):
        if data.get("ghost"):
            continue
        rec = owned.get(node)
        crit = _lower(data.get("criticality"))
        is_critical = any(m in crit for m in HIGH_CRIT)

        if rec is None:
            out.append(_finding(
                "R02", "HIGH" if is_critical else "MEDIUM", "Ownership",
                "Application has no ownership record",
                f"{data.get('name')} ({node})",
                f"No row in ApplicationOwnership. Criticality is "
                f"'{data.get('criticality')}'. Nobody is accountable for change "
                f"approval, incident response or lifecycle decisions.",
                "Assign an owner, a technical custodian and a support group "
                "before this application is used in any governance decision.",
                f"Applications: {node}",
            ))
            continue

        blanks = [f for f in ("Owner", "Custodian", "BusinessOwner", "SupportGroup")
                  if f in rec and _is_blank(rec.get(f))]
        if blanks:
            out.append(_finding(
                "R02", "HIGH" if (is_critical and "Owner" in blanks) else "LOW",
                "Ownership", "Ownership record is incomplete",
                f"{data.get('name')} ({node})",
                f"Ownership row exists but these field(s) are blank: "
                f"{', '.join(blanks)}. Criticality is '{data.get('criticality')}'.",
                "Complete the missing ownership fields so escalation paths resolve.",
                f"ApplicationOwnership: {node}",
            ))
    return out


def rule_lifecycle_risk(ds: EADataset, g: nx.MultiDiGraph) -> list[dict]:
    """R03 - end-of-life or expired applications that still have live consumers."""
    out = []
    today = pd.Timestamp(datetime.now().date())

    for node, data in g.nodes(data=True):
        if data.get("ghost"):
            continue
        status = _lower(data.get("lifecycle"))
        end = data.get("lifecycle_end")
        expired = False
        end_str = ""
        if end is not None and not (isinstance(end, float) and pd.isna(end)):
            try:
                end_ts = pd.to_datetime(end)
                end_str = end_ts.date().isoformat()
                expired = end_ts < today
            except Exception:
                pass

        eol = any(m in status for m in EOL_MARKERS)
        if not (eol or expired):
            continue

        consumers = []
        for _s_, t, d in g.out_edges(node, data=True):
            if d.get("kind") in ("interface", "information_flow", "relationship"):
                tgt = g.nodes[t]
                if any(m in _lower(tgt.get("lifecycle")) for m in ACTIVE_MARKERS):
                    consumers.append(t)
        consumers = sorted(set(consumers))
        if not consumers:
            continue

        crit_consumers = [c for c in consumers
                          if any(m in _lower(g.nodes[c].get("criticality")) for m in HIGH_CRIT)]
        sev = "CRITICAL" if crit_consumers else "HIGH"
        reason = "is marked end-of-life" if eol else f"passed its lifecycle end date ({end_str})"

        out.append(_finding(
            "R03", sev, "Lifecycle risk",
            "Retiring application still feeds active consumers",
            f"{data.get('name')} ({node})",
            f"{data.get('name')} {reason} but still supplies {len(consumers)} active "
            f"application(s)"
            + (f", of which {len(crit_consumers)} are business or mission critical"
               if crit_consumers else "")
            + f": {', '.join(g.nodes[c].get('name', c) for c in consumers[:5])}"
            + (" ..." if len(consumers) > 5 else "") + ".",
            "Confirm a migration path and a cut-over date for each consumer before "
            "decommissioning, or revise the lifecycle status if the retirement has slipped.",
            f"Applications: {node}",
        ))
    return out


def rule_orphan_and_dangling_interfaces(ds: EADataset, g: nx.MultiDiGraph) -> list[dict]:
    """R04 - self-referencing, unused, or contradictory interfaces."""
    out = []
    ifaces = ds.df("Interfaces")
    if ifaces.empty:
        return out

    infos = ds.df("InformationObjects")
    used_ifaces = set()
    if not infos.empty and "InterfaceID" in infos.columns:
        used_ifaces = {_s(v) for v in infos["InterfaceID"].dropna()}

    for idx, row in ifaces.iterrows():
        iid = _s(row.get("InterfaceID"))
        prov = _s(row.get("ProviderApplicationID"))
        cons = _s(row.get("ConsumerApplicationID"))
        status = _lower(row.get("Status"))
        rowref = f"Interfaces row {idx + 2}"

        if prov and prov == cons:
            out.append(_finding(
                "R04", "MEDIUM", "Interface hygiene",
                "Interface points at itself",
                iid or rowref,
                f"Provider and consumer are the same application ({prov}). This is "
                f"either a data entry error or an internal process modelled as an interface.",
                "Correct the provider/consumer pair, or remove it from the "
                "integration inventory if it is an internal process.",
                rowref,
            ))

        if iid and used_ifaces and iid not in used_ifaces:
            out.append(_finding(
                "R04", "LOW", "Interface hygiene",
                "Interface carries no declared information object",
                iid,
                "This interface exists in the inventory but no InformationObject "
                "declares it as the carrier. Either the data flow is undocumented "
                "or the interface is unused.",
                "Document what data this interface actually carries, or retire it "
                "if it is genuinely unused.",
                rowref,
            ))

        # Contradiction: interface is not active but data still flows through it.
        if iid and any(m in status for m in INACTIVE_IF_MARKERS) and iid in used_ifaces:
            out.append(_finding(
                "R04", "HIGH", "Interface hygiene",
                "Inactive interface still carries declared data flows",
                iid,
                f"Interface status is '{_s(row.get('Status'))}' yet InformationObjects "
                f"still route data through it. The architecture record contradicts itself.",
                "Reconcile the interface status with the information flows: either "
                "reactivate the record or reroute/remove the flows.",
                rowref,
            ))
    return out


def rule_duplicate_interfaces(ds: EADataset, g: nx.MultiDiGraph) -> list[dict]:
    """R05 - redundant integrations between the same pair of applications."""
    out = []
    ifaces = ds.df("Interfaces")
    if ifaces.empty or not {"ProviderApplicationID", "ConsumerApplicationID"} <= set(ifaces.columns):
        return out

    grp: dict[tuple[str, str], list[tuple[int, dict]]] = {}
    for idx, row in ifaces.iterrows():
        key = (_s(row.get("ProviderApplicationID")), _s(row.get("ConsumerApplicationID")))
        if not key[0] or not key[1] or key[0] == key[1]:
            continue
        grp.setdefault(key, []).append((idx, row.to_dict()))

    for (prov, cons), rows in grp.items():
        if len(rows) < 2:
            continue
        ids = [_s(r.get("InterfaceID")) for _, r in rows]
        protos = {(_lower(r.get("Protocol")), _lower(r.get("Format"))) for _, r in rows}
        sev = "MEDIUM" if len(protos) == 1 else "LOW"
        detail = ("identical protocol and format" if len(protos) == 1
                  else "differing protocol/format")
        out.append(_finding(
            "R05", sev, "Redundancy",
            "Multiple interfaces between the same application pair",
            f"{g.nodes.get(prov, {}).get('name', prov)} -> {g.nodes.get(cons, {}).get('name', cons)}",
            f"{len(rows)} separate interfaces ({', '.join(i for i in ids if i)}) connect the "
            f"same provider and consumer with {detail}. This is a candidate for consolidation "
            f"and a likely source of duplicated effort and inconsistent data.",
            "Review whether these can be consolidated into one contract, or document "
            "why both must exist (for example different frequency or data domain).",
            "; ".join(f"Interfaces row {i + 2}" for i, _ in rows),
        ))
    return out


def rule_unmapped_and_isolated(ds: EADataset, g: nx.MultiDiGraph) -> list[dict]:
    """R06 - applications with no business context or no connections at all."""
    out = []
    for node, data in g.nodes(data=True):
        if data.get("ghost"):
            continue
        procs = data.get("processes") or []
        degree = g.in_degree(node) + g.out_degree(node)
        crit = _lower(data.get("criticality"))
        is_critical = any(m in crit for m in HIGH_CRIT)

        if degree == 0:
            out.append(_finding(
                "R06", "MEDIUM" if is_critical else "LOW", "Coverage",
                "Application is completely isolated in the model",
                f"{data.get('name')} ({node})",
                f"No relationships, interfaces or information flows reference this "
                f"application, and it supports {len(procs)} business process(es). "
                f"Either it is genuinely standalone or its integrations are undocumented.",
                "Confirm whether the application is truly standalone. If not, its "
                "integrations are missing from the inventory.",
                f"Applications: {node}",
            ))
        elif not procs and is_critical:
            out.append(_finding(
                "R06", "MEDIUM", "Coverage",
                "Business-critical application supports no mapped business process",
                f"{data.get('name')} ({node})",
                f"Criticality is '{data.get('criticality')}' and it participates in "
                f"{degree} connection(s), but no BusinessProcesses row maps to it. "
                f"Its business justification cannot be traced.",
                "Map the application to the business process(es) it supports, so "
                "criticality can be justified and impact assessed in business terms.",
                f"Applications: {node}",
            ))
    return out


def rule_criticality_inversion(ds: EADataset, g: nx.MultiDiGraph) -> list[dict]:
    """R07 - a critical application depending on a much less critical one."""
    out = []
    rank = {"mission critical": 4, "business critical": 3,
            "business operational": 2, "administrative": 1, "unknown": 0}

    def score(v) -> int:
        return rank.get(_lower(v), 0)

    seen: set[tuple[str, str]] = set()
    for s, t, d in g.edges(data=True):
        # Consumer t depends on provider s.
        if (s, t) in seen:
            continue
        sn, tn = g.nodes[s], g.nodes[t]
        if sn.get("ghost") or tn.get("ghost"):
            continue
        cons_score, prov_score = score(tn.get("criticality")), score(sn.get("criticality"))
        if cons_score >= 3 and prov_score and cons_score - prov_score >= 2:
            seen.add((s, t))
            out.append(_finding(
                "R07", "HIGH", "Resilience",
                "Critical application depends on a much lower-tier application",
                f"{tn.get('name')} depends on {sn.get('name')}",
                f"'{tn.get('name')}' is {tn.get('criticality')} but consumes from "
                f"'{sn.get('name')}', which is only {sn.get('criticality')}. The "
                f"upstream application is unlikely to be operated to the "
                f"availability standard the downstream one assumes.",
                "Either raise the criticality and operational SLA of the upstream "
                "application, or introduce a degradation path so the critical "
                "application survives its unavailability.",
                f"Edge {s} -> {t} ({d.get('kind')})",
            ))
    return out


def rule_information_classification(ds: EADataset, g: nx.MultiDiGraph) -> list[dict]:
    """R08 - unclassified data, and sensitive data crossing into exposed hosting."""
    out = []
    infos = ds.df("InformationObjects")
    if infos.empty:
        return out

    name_col = ("InformationObjectName" if "InformationObjectName" in infos.columns
                else "InformationObjectID")

    for idx, row in infos.iterrows():
        src = _s(row.get("SourceApplicationID"))
        tgt = _s(row.get("TargetApplicationID"))
        cls = _s(row.get("Classification"))
        label = _s(row.get(name_col)) or f"row {idx + 2}"
        rowref = f"InformationObjects row {idx + 2}"

        if _is_blank(cls):
            out.append(_finding(
                "R08", "MEDIUM", "Data governance",
                "Information object has no classification",
                label,
                f"Data flowing {src} -> {tgt} carries no classification, so no handling, "
                f"retention or residency rule can be applied to it.",
                "Classify the information object so downstream handling requirements "
                "become enforceable.",
                rowref,
            ))
            continue

        if any(m in cls.lower() for m in SENSITIVE):
            tgt_node = g.nodes.get(tgt, {})
            hosting = _lower(tgt_node.get("hosting"))
            if any(m in hosting for m in EXPOSED_HOSTING):
                out.append(_finding(
                    "R08", "HIGH", "Data governance",
                    "Sensitive data flows into externally hosted application",
                    label,
                    f"'{label}' is classified '{cls}' and flows into "
                    f"'{tgt_node.get('name', tgt)}', which is hosted as "
                    f"'{tgt_node.get('hosting')}'. This crosses a hosting boundary "
                    f"that usually requires an explicit control.",
                    "Confirm a data processing agreement, encryption and residency "
                    "controls exist for this flow, or reroute it.",
                    rowref,
                ))
    return out


ALL_RULES = [
    ("R01", "Broken references", rule_broken_references),
    ("R02", "Ownership gaps", rule_missing_ownership),
    ("R03", "Lifecycle risk", rule_lifecycle_risk),
    ("R04", "Interface hygiene", rule_orphan_and_dangling_interfaces),
    ("R05", "Redundant interfaces", rule_duplicate_interfaces),
    ("R06", "Coverage gaps", rule_unmapped_and_isolated),
    ("R07", "Criticality inversion", rule_criticality_inversion),
    ("R08", "Data classification", rule_information_classification),
]


def run_all(ds: EADataset, g: nx.MultiDiGraph,
            enabled: set[str] | None = None) -> pd.DataFrame:
    """Run every enabled rule and return findings sorted by severity."""
    rows: list[dict] = []
    for rule_id, _name, fn in ALL_RULES:
        if enabled is not None and rule_id not in enabled:
            continue
        try:
            rows.extend(fn(ds, g))
        except Exception as exc:  # a broken rule must not kill the analysis
            rows.append(_finding(
                rule_id, "INFO", "Engine",
                f"Rule {rule_id} could not complete", "-",
                f"The rule raised: {exc}. Remaining rules ran normally.",
                "Check the workbook columns this rule depends on.",
            ))

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["_sev"] = df["Severity"].map(SEVERITY_ORDER).fillna(9)
    df = df.sort_values(["_sev", "Rule", "Entity"]).drop(columns="_sev").reset_index(drop=True)
    return df


def mark_known(findings: pd.DataFrame, ds: EADataset) -> pd.DataFrame:
    """
    Flag which findings were already pre-declared in KnownDataQualityGaps.

    The dataset guide states that sheet is PARTIAL - more gaps exist to be
    discovered. Separating 'already known' from 'newly discovered' is how we
    show the engine finds things the workbook does not already tell you.
    """
    if findings.empty:
        return findings

    known = ds.df("KnownDataQualityGaps")
    blob = ""
    if not known.empty:
        blob = " ".join(
            _s(v).lower() for col in known.columns for v in known[col].dropna()
        )

    def classify(row) -> str:
        if not blob:
            return "NEW"
        ent = _s(row["Entity"]).lower()
        # Match on any identifier-looking token from the entity string.
        tokens = [t.strip("()[],.") for t in ent.replace("->", " ").split()
                  if any(ch.isdigit() for ch in t) and len(t) > 3]
        return "KNOWN" if any(t in blob for t in tokens) else "NEW"

    findings = findings.copy()
    findings["Discovery"] = findings.apply(classify, axis=1)
    return findings


def summarise(findings: pd.DataFrame) -> dict[str, int]:
    if findings.empty:
        return {}
    out = findings["Severity"].value_counts().to_dict()
    if "Discovery" in findings.columns:
        out["Newly discovered"] = int((findings["Discovery"] == "NEW").sum())
    return out
