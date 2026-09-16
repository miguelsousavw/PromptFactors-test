"""Deterministic extraction and graph construction for FSD documents."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import networkx as nx


@dataclass
class FSDProfile:
    integration_name: str
    source_system: str
    target_system: str
    middleware: str
    interface_type: str
    criticality: str
    schedule: str
    owner: str
    description: str
    data_objects: list[str]
    encryption: str

    def as_dict(self) -> dict:
        return asdict(self)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n|/")


def _after(text: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        match = re.search(rf"(?im)^\s*{re.escape(label)}\s*[:\-]\s*(.+)$", text)
        if match:
            value = _clean(match.group(1))
            if value and value.lower() not in {"to be filled by integration team", "tbc"}:
                return value
    return ""


def _table_value(tables: list[list[list[str]]], row_label: str) -> str:
    needle = row_label.casefold()
    for table in tables:
        for row in table:
            cells = [_clean(c) for c in row]
            for i, cell in enumerate(cells):
                if needle in cell.casefold() and i + 1 < len(cells):
                    return cells[i + 1]
    return ""


def parse_fsd(text: str, tables: list[list[list[str]]] | None = None,
              filename: str = "") -> FSDProfile:
    """Infer an integration profile using labels and conservative heuristics."""
    tables = tables or []
    lines = [_clean(x) for x in text.splitlines() if _clean(x)]
    compact = "\n".join(lines)
    source = _table_value(tables, "Source System") or _after(compact, ("Source system",))
    target = _table_value(tables, "Target System") or _after(compact, ("Target system",))
    name = _table_value(tables, "Interface Name")
    if not name:
        name = next((x.split("---", 1)[1].strip() for x in lines
                     if x.lower().startswith("fsd template") and "---" in x), "")
    if not name:
        name = _table_value(tables, "Deliverable Name")
    if not name:
        name = re.sub(r"(?i)^fsd[_ -]*", "", filename.rsplit("/", 1)[-1]).rsplit(".", 1)[0]
    name = _clean(name) or "FSD integration"

    middleware = "SAP CPI" if re.search(r"\b(?:SAP\s+)?CPI\b|middleware", compact, re.I) else "Integration middleware"
    if re.search(r"\bSFTP\b", compact, re.I):
        middleware = "SAP CPI + SFTP/RVS"
    if re.search(r"\bAPI\b", compact, re.I):
        interface_type = "API"
    elif re.search(r"\b(?:SFTP|CSV|flat file)\b", compact, re.I):
        interface_type = "File transfer"
    else:
        interface_type = "Integration"

    if re.search(r"mission[- ]critical|business[- ]critical|critical", compact, re.I):
        criticality = "Critical (document signal)"
    else:
        criticality = "Not stated"
    schedule_match = re.search(
        r"\b(?:daily|weekly|monthly|real[- ]time|near[- ]real[- ]time|on[- ]demand|"
        r"scheduled|batch|every\s+\w+)\b", compact, re.I)
    schedule = _clean(schedule_match.group(0)) if schedule_match else "Not stated"
    owner = _table_value(tables, "Business Owner") or _table_value(tables, "Application Owner")
    if not owner:
        owner = "Not stated"
    description = ""
    for marker in ("The purpose of this integration", "This integration will"):
        match = re.search(rf"(?is){re.escape(marker)}(.+?)(?:\n(?:Introduction|General Information|Scope)\b|$)",
                          compact)
        if match:
            description = _clean(marker + match.group(1))
            break
    if not description:
        description = "Integration profile extracted from the supplied FSD."
    data_objects: list[str] = []
    for item in re.findall(r"\b(?:candidate|offer|employee|person|personal information|"
                           r"address|phone|email|employment|job|compensation|"
                           r"national id|employee data)\b", compact, re.I):
        value = item.title()
        if value not in data_objects:
            data_objects.append(value)
    encryption = "Required" if re.search(r"encryption.*(?:required|requires)|PGP", compact, re.I) else "Not stated"
    return FSDProfile(name, source or "Source system not stated", target or "Target system not stated",
                      middleware, interface_type, criticality, schedule, owner,
                      description, data_objects[:8], encryption)


def build_integration_graph(profile: FSDProfile) -> nx.MultiDiGraph:
    """Create a small LeanIX-style context graph for one integration."""
    g = nx.MultiDiGraph()
    source, middleware, target = "source", "middleware", "target"
    g.add_node(source, name=profile.source_system, kind="application",
               criticality="business critical", domain="Source", lifecycle="Active",
               hosting="External", owner=profile.owner, processes=[], ghost=False)
    g.add_node(middleware, name=profile.middleware, kind="application",
               criticality="business operational", domain="Integration", lifecycle="Active",
               hosting="Cloud", owner=profile.owner, processes=[], ghost=False)
    g.add_node(target, name=profile.target_system, kind="application",
               criticality="business critical", domain="Target", lifecycle="Active",
               hosting="External", owner=profile.owner, processes=[], ghost=False)
    g.add_edge(source, middleware, kind="interface", label=profile.interface_type,
               protocol=profile.interface_type, frequency=profile.schedule)
    g.add_edge(middleware, target, kind="interface", label=profile.interface_type,
               protocol=profile.interface_type, frequency=profile.schedule)
    for i, obj in enumerate(profile.data_objects[:5]):
        node = f"data-{i}"
        g.add_node(node, name=obj, kind="application", criticality="administrative",
                   domain="Information object", lifecycle="Active", hosting="Unknown",
                   owner=profile.owner, processes=[], ghost=False)
        g.add_edge(source, node, kind="information_flow", label="extracts")
        g.add_edge(node, target, kind="information_flow", label="delivers")
    return g


def answer_question(question: str, profile: FSDProfile) -> str:
    """Answer common integration questions without an LLM."""
    q = question.casefold()
    if any(x in q for x in ("source", "from where", "upstream")):
        return f"The source system is **{profile.source_system}**."
    if any(x in q for x in ("target", "to where", "downstream")):
        return f"The target system is **{profile.target_system}**."
    if "owner" in q:
        return f"The documented owner is **{profile.owner}**."
    if any(x in q for x in ("schedule", "frequency", "when", "how often")):
        return f"The schedule is **{profile.schedule}** (or not stated in the FSD)."
    if any(x in q for x in ("critical", "risk")):
        return f"Criticality is **{profile.criticality}**."
    if any(x in q for x in ("data", "object", "payload")):
        objects = ", ".join(profile.data_objects) or "not explicitly listed"
        return f"Identified data objects: **{objects}**."
    return (f"This is a **{profile.interface_type}** integration from **{profile.source_system}** "
            f"to **{profile.target_system}** via **{profile.middleware}**. "
            "Try asking about source, target, owner, schedule, criticality, or data.")
