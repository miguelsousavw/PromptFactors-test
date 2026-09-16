"""
diagram.py - DETERMINISTIC layer.

Renders a context subgraph as an interactive Plotly figure. Layout is a
deterministic spring layout with a fixed seed, so the same input always
produces the same picture (important when a judge re-runs your demo).

No LLM is involved in drawing anything.
"""

from __future__ import annotations

import networkx as nx
import plotly.graph_objects as go

EDGE_STYLE = {
    "relationship": {"color": "#64748B", "dash": "dot", "name": "Dependency"},
    "interface": {"color": "#155EEF", "dash": "solid", "name": "Interface"},
    "information_flow": {"color": "#087443", "dash": "dash", "name": "Information flow"},
}

CRIT_COLOR = {
    "mission critical": "#B42318",
    "business critical": "#D97706",
    "business operational": "#175CD3",
    "administrative": "#667085",
}
GHOST_COLOR = "#344054"
FOCUS_RING = "#101828"


def _node_color(data: dict) -> str:
    if data.get("ghost"):
        return GHOST_COLOR
    if data.get("kind") == "middleware":
        return "#7F56D9"
    if data.get("kind") == "information_object":
        return "#0086C9"
    return CRIT_COLOR.get(str(data.get("criticality", "")).lower(), "#98A2B3")


def _node_size(g: nx.MultiDiGraph, node: str, focus: str | None) -> int:
    if node == focus:
        return 34
    deg = g.in_degree(node) + g.out_degree(node)
    return int(min(30, 13 + deg * 1.6))


def _hover(node: str, data: dict, g: nx.MultiDiGraph) -> str:
    procs = data.get("processes") or []
    owner = data.get("owner") or ""
    lines = [
        f"<b>{data.get('name', node)}</b>",
        f"Domain: {data.get('domain', 'n/a')}",
        f"Criticality: {data.get('criticality', 'n/a')}",
        f"Lifecycle: {data.get('lifecycle', 'n/a')}",
        f"Hosting: {data.get('hosting', 'n/a')}",
        f"Owner: {owner if owner else '<i>none recorded</i>'}",
        f"Consumes from: {g.in_degree(node)} | Supplies: {g.out_degree(node)}",
    ]
    if procs:
        shown = ", ".join(procs[:3]) + (" ..." if len(procs) > 3 else "")
        lines.append(f"Processes: {shown}")
    if data.get("ghost"):
        lines.append("<b>UNDEFINED - referenced but not in Applications</b>")
    return "<br>".join(lines)


def _linear_positions(sub: nx.MultiDiGraph) -> dict[str, tuple[float, float]]:
    """Place the integration backbone left-to-right and data on a middle rail."""
    nodes = sorted(sub.nodes())
    apps = [n for n in nodes if sub.nodes[n].get("kind") == "application"]
    middleware = [n for n in nodes if sub.nodes[n].get("kind") == "middleware"]
    data = [n for n in nodes if sub.nodes[n].get("kind") == "information_object"]
    positions: dict[str, tuple[float, float]] = {}
    source = next((n for n in apps if sub.in_degree(n) == 0), apps[0] if apps else None)
    target = next((n for n in reversed(apps) if sub.out_degree(n) == 0),
                  apps[-1] if apps else None)
    if source is not None:
        positions[source] = (0.0, 0.0)
    if target is not None and target != source:
        positions[target] = (1.0, 0.0)

    ordered: list[str] = []
    current = source
    while current is not None:
        nxt = next((t for _, t, d in sub.out_edges(current, data=True)
                    if d.get("kind") == "interface"
                    and sub.nodes[t].get("kind") == "middleware"
                    and t not in ordered), None)
        if nxt is None:
            break
        ordered.append(nxt)
        current = nxt
    ordered.extend(n for n in middleware if n not in ordered)
    step = 1.0 / (len(ordered) + 1) if ordered else 1.0
    for i, node in enumerate(ordered, 1):
        positions[node] = (i * step, 0.0)
    for i, node in enumerate(data):
        positions[node] = (0.5, (i - (len(data) - 1) / 2) * 0.34)

    # Keep future node types visible without reintroducing a force-directed layout.
    missing = [n for n in nodes if n not in positions]
    for i, node in enumerate(missing):
        positions[node] = (0.5, (i - (len(missing) - 1) / 2) * 0.34)
    return positions


def render(sub: nx.MultiDiGraph, focus: str | None = None,
           title: str = "", show_labels: bool = True,
           label_edges: bool = False) -> go.Figure:
    """Build the interactive context diagram."""
    fig = go.Figure()

    if sub.number_of_nodes() == 0:
        fig.add_annotation(text="No applications match the current filters.",
                           showarrow=False, font=dict(size=15, color="#666"))
        fig.update_layout(height=560, xaxis=dict(visible=False), yaxis=dict(visible=False))
        return fig

    # Explicit stages make direction understandable without knowing graph IDs.
    pos = _linear_positions(sub)

    # --- edges, grouped by kind so the legend is meaningful ------------------
    drawn: dict[str, list] = {kind: [] for kind in EDGE_STYLE}
    seen_pairs: dict[tuple[str, str, str], int] = {}
    edge_label_pts = []

    for s, t, data in sub.edges(data=True):
        kind = data.get("kind", "relationship")
        if kind not in drawn or s == t:
            continue
        key = (s, t, kind)
        seen_pairs[key] = seen_pairs.get(key, 0) + 1
        drawn[kind].append((s, t))
        if label_edges and data.get("label"):
            x0, y0 = pos[s]
            x1, y1 = pos[t]
            edge_label_pts.append(((x0 + x1) / 2, (y0 + y1) / 2, str(data["label"])[:28]))

    for kind, pairs in drawn.items():
        if not pairs:
            continue
        xs, ys = [], []
        for s, t in pairs:
            x0, y0 = pos[s]
            x1, y1 = pos[t]
            xs += [x0, x1, None]
            ys += [y0, y1, None]
        style = EDGE_STYLE[kind]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines", name=f"{style['name']} ({len(pairs)})",
            line=dict(width=1.5, color=style["color"], dash=style["dash"]),
            hoverinfo="skip", opacity=0.75,
        ))

    # --- arrowheads for direction -------------------------------------------
    annotations = []
    for kind, pairs in drawn.items():
        style = EDGE_STYLE[kind]
        for s, t in pairs[:400]:  # cap so very large views stay responsive
            x0, y0 = pos[s]
            x1, y1 = pos[t]
            annotations.append(dict(
                ax=x0 + (x1 - x0) * 0.72, ay=y0 + (y1 - y0) * 0.72,
                x=x0 + (x1 - x0) * 0.86, y=y0 + (y1 - y0) * 0.86,
                xref="x", yref="y", axref="x", ayref="y",
                showarrow=True, arrowhead=2, arrowsize=1.1,
                arrowwidth=1.2, arrowcolor=style["color"], opacity=0.8,
            ))

    if label_edges:
        for x, y, lab in edge_label_pts[:120]:
            annotations.append(dict(x=x, y=y, text=lab, showarrow=False,
                                    font=dict(size=8, color="#5A6570"),
                                    bgcolor="rgba(255,255,255,0.65)"))

    # --- nodes ---------------------------------------------------------------
    nodes = sorted(sub.nodes())
    fig.add_trace(go.Scatter(
        x=[pos[n][0] for n in nodes],
        y=[pos[n][1] for n in nodes],
        mode="markers+text" if show_labels else "markers",
        name="Participants / objects",
        text=[sub.nodes[n].get("name", n) if show_labels else "" for n in nodes],
        textposition="bottom center",
        textfont=dict(size=12, color="#101828"),
        hovertext=[_hover(n, sub.nodes[n], sub) for n in nodes],
        hoverinfo="text",
        marker=dict(
            size=[_node_size(sub, n, focus) for n in nodes],
            color=[_node_color(sub.nodes[n]) for n in nodes],
            line=dict(
                width=[3 if n == focus else 1.2 for n in nodes],
                color=[FOCUS_RING if n == focus else "#FFFFFF" for n in nodes],
            ),
        ),
        showlegend=False,
    ))

    fig.update_layout(
        title=dict(text=title, font=dict(size=18, color="#101828")),
        annotations=annotations,
        height=540,
        margin=dict(l=24, r=24, t=58, b=24),
        hovermode="closest",
        plot_bgcolor="#FFFFFF",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    font=dict(size=11, color="#344054")),
        xaxis=dict(visible=False, showgrid=False, zeroline=False, range=[-0.12, 1.12]),
        yaxis=dict(visible=False, showgrid=False, zeroline=False, range=[-1.0, 1.0]),
        autosize=True,
    )
    return fig


def legend_note() -> str:
    return (
        "**Colours:** applications use business criticality; purple = middleware; "
        "teal = information objects; dark grey = referenced but undefined. "
        "**Read left to right:** arrows show what connects or moves. "
        "Solid blue = interface; dashed green = information flow."
    )
