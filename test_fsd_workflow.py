"""Deterministic assertions for multi-FSD grouping."""
from pathlib import Path

import networkx as nx

from document_ingest import extract_tables, extract_text
from fsd_workflow import (
    FSDProfile,
    build_combined_graph,
    group_fsd_profiles,
    merge_fsd_profiles,
    parse_fsd,
)


def profile(name, source, target, middleware="SAP CPI"):
    return FSDProfile(
        name, source, target, middleware, "API", "Not stated", "Daily",
        "Owner", "Description", [], "Not stated",
        middleware_components=[middleware],
    )


def test_grouping_uses_system_brand_and_connections():
    # Same brand (SAP) groups even with different systems.
    sap_a = profile("A", "SAP S/4HANA", "SAP CPI")
    sap_b = profile("B", "SAP SuccessFactors", "SAP CPI")
    # Connected transitively through the target/source relationship.
    connected = profile("C", "SAP CPI", "Warehouse")
    unrelated = profile("D", "Shopify", "Stripe", "Shopify Flow")
    groups = group_fsd_profiles([sap_a, unrelated, sap_b, connected])
    assert [[item.integration_name for item in group] for group in groups] == [
        ["A", "B", "C"], ["D"]
    ]


def test_single_profile_and_merge_remain_compatible():
    item = profile("One", "Source", "Target", "RVS")
    assert group_fsd_profiles([item]) == [[item]]
    assert merge_fsd_profiles([item]) is item


def test_supplied_dummy_fsds_share_logical_system_nodes():
    paths = [
        Path("/Users/sc5vrup/.copilot/workspaces/e1c4802a-4fb7-484d-b3d7-4e3584206bd7/attachments/"
             "d6a5aa99-bfce-4294-9364-39d54025abf5-Dummy_FSD_Employees_NZ.docx"),
        Path("/Users/sc5vrup/.copilot/workspaces/e1c4802a-4fb7-484d-b3d7-4e3584206bd7/attachments/"
             "60b30f4f-0fd9-4856-b106-83063cd7fc1c-Dummy_FSD_Recruitment.docx"),
    ]
    if not all(path.exists() for path in paths):
        return

    profiles = [
        parse_fsd(
            extract_text(path.read_bytes(), path.name),
            extract_tables(path.read_bytes(), path.name),
            path.name,
        )
        for path in paths
    ]
    graph = build_combined_graph(profiles)
    systems = {
        data["name"]: node
        for node, data in graph.nodes(data=True)
        if data.get("kind") in {"application", "middleware"}
    }
    assert [name for name in systems if name == "SAP CPI"] == ["SAP CPI"]
    assert [name for name in systems if name == "SAP SuccessFactors"] == [
        "SAP SuccessFactors"
    ]
    assert not any(
        name.upper().endswith(("TEST", "PROD10", "PREV10", "QUALITY", "PRODUCTION"))
        for name in systems
    )
    assert len(graph.edges) == 22
    assert nx.has_path(graph, systems["Nimbus HR Cloud"], systems["SAP SuccessFactors"])
    assert len(group_fsd_profiles(profiles)) == 1


if __name__ == "__main__":
    test_grouping_uses_system_brand_and_connections()
    test_single_profile_and_merge_remain_compatible()
    print("OK: multi-FSD grouping assertions")
