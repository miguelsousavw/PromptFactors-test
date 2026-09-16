"""
graph_build.py - DETERMINISTIC layer.

Turns the validated workbook into a typed, directed multigraph. This is the
single backbone every other component reads from: diagrams, rules and the AI
question layer all traverse this same graph, so they can never disagree.

No LLM is involved anywhere in this file.
"""

from __future__ import annotations

import hashlib

import networkx as nx
import pandas as pd

from ingest import EADataset

EDGE_KINDS = ("relationship", "interface", "information_flow")


def build_graph(ds: EADataset) -> nx.MultiDiGraph:
    """Build the architecture knowledge graph from the dataset."""
    g = nx.MultiDiGraph()

    apps = ds.df("Applications")
    for _, row in apps.iterrows():
        app_id = row.get("ApplicationID")
        if pd.isna(app_id):
            continue
        app_id = str(app_id)
        g.add_node(
            app_id,
            kind="application",
            name=str(row.get("ApplicationName") or app_id),
            domain=str(row.get("BusinessDomain") or "Unassigned"),
            criticality=str(row.get("BusinessCriticality") or "Unknown"),
            lifecycle=str(row.get("LifecycleStatus") or "Unknown"),
            lifecycle_end=row.get("LifecycleEndDate"),
            hosting=str(row.get("Hosting") or "Unknown"),
            vendor_type=str(row.get("VendorType") or "Unknown"),
            description=str(row.get("Description") or ""),
            ghost=False,
        )

    # Ghost nodes: referenced anywhere but absent from Applications. We add them
    # explicitly rather than dropping the edge, so broken references stay
    # visible in the diagram instead of silently disappearing.
    def ensure(node_id) -> str | None:
        if pd.isna(node_id):
            return None
        node_id = str(node_id)
        if node_id not in g:
            g.add_node(
                node_id, kind="application", name=f"{node_id} (undefined)",
                domain="UNRESOLVED", criticality="Unknown", lifecycle="Unknown",
                lifecycle_end=None, hosting="Unknown", vendor_type="Unknown",
                description="Referenced but not present in the Applications sheet.",
                ghost=True,
            )
        return node_id

    rels = ds.df("Relationships")
    if not rels.empty and {"SourceApplicationID", "TargetApplicationID"} <= set(rels.columns):
        for idx, row in rels.iterrows():
            s = ensure(row.get("SourceApplicationID"))
            t = ensure(row.get("TargetApplicationID"))
            if s and t:
                g.add_edge(s, t, kind="relationship",
                           label=str(row.get("RelationshipType") or "depends on"),
                           row=int(idx))

    ifaces = ds.df("Interfaces")
    if not ifaces.empty and {"ProviderApplicationID", "ConsumerApplicationID"} <= set(ifaces.columns):
        for idx, row in ifaces.iterrows():
            s = ensure(row.get("ProviderApplicationID"))
            t = ensure(row.get("ConsumerApplicationID"))
            if s and t:
                g.add_edge(s, t, kind="interface",
                           interface_id=str(row.get("InterfaceID") or ""),
                           label=str(row.get("InterfaceName")
                                     or row.get("InterfaceID") or "interface"),
                           protocol=str(row.get("Protocol") or ""),
                           fmt=str(row.get("Format") or ""),
                           frequency=str(row.get("Frequency") or ""),
                           status=str(row.get("Status") or ""),
                           row=int(idx))

    infos = ds.df("InformationObjects")
    if not infos.empty and {"SourceApplicationID", "TargetApplicationID"} <= set(infos.columns):
        for idx, row in infos.iterrows():
            s = ensure(row.get("SourceApplicationID"))
            t = ensure(row.get("TargetApplicationID"))
            if s and t:
                g.add_edge(s, t, kind="information_flow",
                           label=str(row.get("InformationObjectName")
                                     or row.get("InformationObjectID") or "data"),
                           classification=str(row.get("Classification") or ""),
                           interface_id=str(row.get("InterfaceID") or ""),
                           row=int(idx))

    # Business process support is attached as a node attribute rather than an
    # edge, so process context travels with the application in every view.
    procs = ds.df("BusinessProcesses")
    if not procs.empty and "SupportingApplicationID" in procs.columns:
        name_col = "ProcessName" if "ProcessName" in procs.columns else "BusinessProcessID"
        for _, row in procs.iterrows():
            app_id = row.get("SupportingApplicationID")
            if pd.isna(app_id):
                continue
            node = ensure(app_id)
            if node:
                g.nodes[node].setdefault("processes", [])
                label = str(row.get(name_col) or "").strip()
                if label and label not in g.nodes[node]["processes"]:
                    g.nodes[node]["processes"].append(label)

    own = ds.df("ApplicationOwnership")
    if not own.empty and "ApplicationID" in own.columns:
        for _, row in own.iterrows():
            app_id = row.get("ApplicationID")
            if pd.isna(app_id) or str(app_id) not in g:
                continue
            n = g.nodes[str(app_id)]
            n["owner"] = str(row.get("Owner") or "").strip()
            n["custodian"] = str(row.get("Custodian") or "").strip()
            n["business_owner"] = str(row.get("BusinessOwner") or "").strip()
            n["support_group"] = str(row.get("SupportGroup") or "").strip()

    return g


def context_subgraph(g: nx.MultiDiGraph, focus: str, depth: int = 1,
                     kinds: tuple[str, ...] = EDGE_KINDS) -> nx.MultiDiGraph:
    """Neighbourhood of `focus` out to `depth` hops, following both directions."""
    if focus not in g:
        return nx.MultiDiGraph()

    keep = {focus}
    frontier = {focus}
    for _ in range(max(1, depth)):
        nxt: set[str] = set()
        for node in frontier:
            for _, t, data in g.out_edges(node, data=True):
                if data.get("kind") in kinds:
                    nxt.add(t)
            for s, _, data in g.in_edges(node, data=True):
                if data.get("kind") in kinds:
                    nxt.add(s)
        nxt -= keep
        keep |= nxt
        frontier = nxt
        if not frontier:
            break

    sub = nx.MultiDiGraph()
    sub.add_nodes_from((n, g.nodes[n]) for n in keep)
    for s, t, data in g.edges(data=True):
        if s in keep and t in keep and data.get("kind") in kinds:
            sub.add_edge(s, t, **data)
    return sub


def domain_subgraph(g: nx.MultiDiGraph, domain: str,
                    kinds: tuple[str, ...] = EDGE_KINDS) -> nx.MultiDiGraph:
    keep = {n for n, d in g.nodes(data=True) if d.get("domain") == domain}
    # Include one hop out, so cross-domain dependencies are visible.
    border: set[str] = set()
    for n in keep:
        border |= {t for _, t, d in g.out_edges(n, data=True) if d.get("kind") in kinds}
        border |= {s for s, _, d in g.in_edges(n, data=True) if d.get("kind") in kinds}
    keep |= border

    sub = nx.MultiDiGraph()
    sub.add_nodes_from((n, g.nodes[n]) for n in keep)
    for s, t, data in g.edges(data=True):
        if s in keep and t in keep and data.get("kind") in kinds:
            sub.add_edge(s, t, **data)
    return sub


def process_subgraph(g: nx.MultiDiGraph, process: str,
                     kinds: tuple[str, ...] = EDGE_KINDS) -> nx.MultiDiGraph:
    keep = {n for n, d in g.nodes(data=True) if process in (d.get("processes") or [])}
    border: set[str] = set()
    for n in keep:
        border |= {t for _, t, d in g.out_edges(n, data=True) if d.get("kind") in kinds}
        border |= {s for s, _, d in g.in_edges(n, data=True) if d.get("kind") in kinds}
    keep |= border

    sub = nx.MultiDiGraph()
    sub.add_nodes_from((n, g.nodes[n]) for n in keep)
    for s, t, data in g.edges(data=True):
        if s in keep and t in keep and data.get("kind") in kinds:
            sub.add_edge(s, t, **data)
    return sub


def impact_of(g: nx.MultiDiGraph, app_id: str, max_depth: int = 4) -> dict[int, list[str]]:
    """Downstream blast radius: who consumes from `app_id`, by hop distance."""
    if app_id not in g:
        return {}
    seen = {app_id}
    layers: dict[int, list[str]] = {}
    frontier = {app_id}
    for depth in range(1, max_depth + 1):
        nxt: set[str] = set()
        for node in frontier:
            for _, t, _d in g.out_edges(node, data=True):
                if t not in seen:
                    nxt.add(t)
        if not nxt:
            break
        seen |= nxt
        layers[depth] = sorted(nxt)
        frontier = nxt
    return layers


def graph_stats(g: nx.MultiDiGraph) -> dict[str, int]:
    kinds = {k: 0 for k in EDGE_KINDS}
    for _, _, d in g.edges(data=True):
        kinds[d.get("kind", "relationship")] = kinds.get(d.get("kind", "relationship"), 0) + 1
    return {
        "Applications": sum(1 for _, d in g.nodes(data=True) if not d.get("ghost")),
        "Undefined (ghost) nodes": sum(1 for _, d in g.nodes(data=True) if d.get("ghost")),
        "Dependency edges": kinds["relationship"],
        "Interface edges": kinds["interface"],
        "Information flows": kinds["information_flow"],
        "Business domains": len({d.get("domain") for _, d in g.nodes(data=True)}),
    }


def merge_candidates(g: nx.MultiDiGraph, candidates: list[dict]) -> nx.MultiDiGraph:
    """Merge only human-accepted document candidates into a graph copy."""
    out = g.copy()
    by_name = {str(d.get("name", "")).casefold(): n for n, d in out.nodes(data=True)}
    # Create application candidates first so accepted relationships work
    # regardless of the order in which the reviewer leaves rows in the table.
    for c in candidates:
        typ = str(c.get("candidate_type", "")).lower()
        if typ == "application" and c.get("name"):
            name = str(c["name"]).strip()
            if name.casefold() not in by_name:
                fingerprint = "|".join([
                    typ, name, str(c.get("description", "")).strip(),
                ]).encode("utf-8")
                node = f"DOC-{hashlib.sha256(fingerprint).hexdigest()[:12].upper()}"
                out.add_node(node, kind="application", name=name,
                             domain="Document candidate", criticality="Unknown",
                             lifecycle="Unknown", hosting="Unknown",
                             vendor_type="Unknown", description=c.get("description", ""),
                             ghost=False, candidate=True, processes=[])
                by_name[name.casefold()] = node
    for c in candidates:
        typ = str(c.get("candidate_type", "")).lower()
        source = str(c.get("source_application", "")).strip()
        target = str(c.get("target_application", "")).strip()
        if typ in {"interface", "relationship", "information_object"} and source and target:
            s, t = by_name.get(source.casefold()), by_name.get(target.casefold())
            if s and t:
                kind = {"interface": "interface", "relationship": "relationship",
                        "information_object": "information_flow"}[typ]
                out.add_edge(s, t, kind=kind, label=c.get("name") or "document candidate",
                             candidate=True, row="document")
    return out
