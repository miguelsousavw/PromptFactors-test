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
    "relationship":      {"color": "#8899A6", "dash": "dot",   "name": "Dependency"},
    "interface":         {"color": "#1F6FEB", "dash": "solid", "name": "Interface"},
    "information_flow":  {"color": "#12A150", "dash": "dash",  "name": "Information flow"},
}

CRIT_COLOR = {
    "mission critical":     "#C0392B",
    "business critical":    "#E67E22",
    "business operational": "#2E86C1",
    "administrative":       "#7F8C8D",
}
GHOST_COLOR = "#000000"
FOCUS_RING = "#111111"


def _node_color(data: dict) -> str:
    if data.get("ghost"):
        return GHOST_COLOR
    if data.get("kind") == "middleware":
        return "#8E44AD"
    if data.get("kind") == "information_object":
        return "#16A085"
    return CRIT_COLOR.get(str(data.get("criticality", "")).lower(), "#95A5A6")


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
        f"ID: {node}",
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

    # Deterministic layout: fixed seed + sorted node order.
    simple = nx.Graph()
    simple.add_nodes_from(sorted(sub.nodes()))
    simple.add_edges_from({(s, t) for s, t in sub.edges() if s != t})
    k = 1.9 / max(1, simple.number_of_nodes() ** 0.5)
    pos = nx.spring_layout(simple, seed=42, k=k, iterations=220)

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
        textfont=dict(size=9, color="#2C3E50"),
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
        title=dict(text=title, font=dict(size=15)),
        annotations=annotations,
        height=620,
        margin=dict(l=10, r=10, t=48, b=10),
        hovermode="closest",
        plot_bgcolor="#FFFFFF",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0),
        xaxis=dict(visible=False, showgrid=False, zeroline=False),
        yaxis=dict(visible=False, showgrid=False, zeroline=False),
    )
    return fig


def legend_note() -> str:
    return (
        "**Node colour** = business criticality "
        "(red mission critical, orange business critical, blue operational, "
        "grey administrative, **black = referenced but undefined**). "
        "**Node size** = number of connections. "
        "**Line style** = blue solid interface, green dashed information flow, "
        "grey dotted dependency."
    )
