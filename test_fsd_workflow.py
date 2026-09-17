"""Deterministic assertions for multi-FSD grouping."""
from fsd_workflow import FSDProfile, group_fsd_profiles, merge_fsd_profiles


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


if __name__ == "__main__":
    test_grouping_uses_system_brand_and_connections()
    test_single_profile_and_merge_remain_compatible()
    print("OK: multi-FSD grouping assertions")
