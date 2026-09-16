"""
make_sample_dataset.py - test-data generator.

Produces a synthetic LeanIX-style workbook with the same sheet and column
structure documented in the i.mobilothon dataset guide.

Why this is in the repo: the judges said they may score the solution against a
MODIFIED copy of the workbook, with different IDs and additional scenarios.
Running this with two different seeds produces two structurally identical but
completely different workbooks - which is how we prove nothing is hard-coded.

    python make_sample_dataset.py --seed 42  --out sample_ea_seed42.xlsx
    python make_sample_dataset.py --seed 777 --out sample_ea_seed777.xlsx

NOTE: this is generated stand-in data for testing the app. On the day, load the
real Auriga_Motors_Synthetic_EA_Dataset.xlsx from the organisers' ZIP.
"""

from __future__ import annotations

import argparse
import random

import pandas as pd

DOMAINS = [
    "Sales & Ordering", "Dealer Management", "Customer Service",
    "Aftersales & Warranty", "Connected Vehicle", "Manufacturing",
    "Supply Chain & Logistics", "Finance", "Marketing", "Data & Analytics",
    "HR & Workplace",
]
CRITICALITY = ["Mission Critical", "Business Critical", "Business Operational",
               "Administrative"]
LIFECYCLE = ["Active", "Active", "Active", "Active", "Phase-in", "End of Life"]
HOSTING = ["SaaS", "Public Cloud", "Private Cloud", "On-Prem"]
VENDOR = ["COTS", "Custom"]
PROTOCOLS = ["REST", "SOAP", "SFTP", "JDBC", "Kafka", "IDoc", "OData"]
FORMATS = ["JSON", "XML", "CSV", "Avro", "EDIFACT", "Parquet"]
FREQUENCY = ["Real-time", "Hourly", "Daily", "Weekly", "On-demand"]
IF_STATUS = ["Active", "Active", "Active", "Planned", "Deprecated"]
CLASSIFICATION = ["Public", "Internal", "Confidential", "Restricted", "Personal"]

NOUNS = ["Platform", "Hub", "Engine", "Portal", "Service", "Manager", "Gateway",
         "Suite", "System", "Tracker", "Console", "Workbench", "Registry"]
ADJS = ["Customer", "Vehicle", "Dealer", "Order", "Parts", "Warranty", "Telematics",
        "Billing", "Supplier", "Quality", "Campaign", "Fleet", "Inventory",
        "Payment", "Logistics", "Production", "Pricing", "Claims", "Identity",
        "Document", "Workforce", "Analytics", "Compliance", "Charging"]
PROCESS_NAMES = [
    "Order to Delivery", "Lead to Cash", "Hire to Retire", "Procure to Pay",
    "Idea to Product", "Issue to Resolution", "Plan to Produce",
    "Warranty Claim Handling", "Vehicle Homologation", "Dealer Onboarding",
    "Customer Complaint Handling", "Spare Parts Replenishment",
    "Connected Services Activation", "Campaign to Lead", "Record to Report",
]


def generate(seed: int = 42, n_apps: int = 64) -> dict[str, pd.DataFrame]:
    rnd = random.Random(seed)

    # --- Applications --------------------------------------------------------
    used_names: set[str] = set()
    apps = []
    for i in range(1, n_apps + 1):
        while True:
            name = f"{rnd.choice(ADJS)} {rnd.choice(NOUNS)}"
            if name not in used_names:
                used_names.add(name)
                break
        lifecycle = rnd.choice(LIFECYCLE)
        start_year = rnd.randint(2014, 2024)
        end = ""
        if lifecycle == "End of Life":
            end = f"{rnd.randint(2024, 2026)}-{rnd.randint(1, 12):02d}-15"
        elif rnd.random() < 0.10:
            end = f"{rnd.randint(2026, 2029)}-{rnd.randint(1, 12):02d}-15"

        apps.append({
            "ApplicationID": f"APP-{i:04d}",
            "ApplicationName": name,
            "Description": f"{name} supporting {rnd.choice(DOMAINS).lower()} operations.",
            "BusinessDomain": rnd.choice(DOMAINS),
            "BusinessCriticality": rnd.choices(
                CRITICALITY, weights=[15, 35, 35, 15])[0],
            "LifecycleStatus": lifecycle,
            "LifecycleStartDate": f"{start_year}-{rnd.randint(1, 12):02d}-01",
            "LifecycleEndDate": end,
            "Hosting": rnd.choice(HOSTING),
            "VendorType": rnd.choice(VENDOR),
            "OwnerEmployeeID": f"E{rnd.randint(20000, 29999)}",
            "CostCenter": f"CC-{1000 + i * 7}",
        })
    app_ids = [a["ApplicationID"] for a in apps]

    # Ghost IDs: referenced below but deliberately absent from Applications.
    ghosts = [f"APP-9{rnd.randint(100, 999):03d}" for _ in range(rnd.randint(3, 5))]
    ghosts = sorted(set(ghosts))

    def pick(exclude=None):
        while True:
            c = rnd.choice(app_ids)
            if c != exclude:
                return c

    # --- Relationships -------------------------------------------------------
    rels, seen = [], set()
    for i in range(int(n_apps * 2.3)):
        s, t = pick(), None
        t = pick(exclude=s)
        if (s, t) in seen:
            continue
        seen.add((s, t))
        rels.append({
            "RelationshipID": f"REL-{i + 1:04d}",
            "SourceApplicationID": s,
            "TargetApplicationID": t,
            "RelationshipType": rnd.choice(
                ["depends on", "sends data to", "authenticates via", "extends"]),
            "Description": "",
        })
    # Seeded scenario: a handful of edges point at non-existent applications.
    for i, gh in enumerate(ghosts[:3]):
        rels.append({
            "RelationshipID": f"REL-9{i + 1:03d}",
            "SourceApplicationID": pick(),
            "TargetApplicationID": gh,
            "RelationshipType": "depends on",
            "Description": "",
        })

    # --- Interfaces ----------------------------------------------------------
    ifaces = []
    for i in range(int(n_apps * 1.6)):
        p = pick()
        c = pick(exclude=p)
        ifaces.append({
            "InterfaceID": f"IF-{i + 1:04d}",
            "InterfaceName": f"{p} to {c} feed",
            "ProviderApplicationID": p,
            "ConsumerApplicationID": c,
            "Protocol": rnd.choice(PROTOCOLS),
            "Format": rnd.choice(FORMATS),
            "Frequency": rnd.choice(FREQUENCY),
            "Status": rnd.choice(IF_STATUS),
        })

    n = len(ifaces)
    # Seeded scenario: duplicate interface between an existing pair.
    for i in range(3):
        src = ifaces[rnd.randrange(n)]
        dup = dict(src)
        dup["InterfaceID"] = f"IF-8{i + 1:03d}"
        dup["InterfaceName"] = src["InterfaceName"] + " (secondary)"
        ifaces.append(dup)
    # Seeded scenario: self-referencing interface.
    self_app = pick()
    ifaces.append({
        "InterfaceID": "IF-8900", "InterfaceName": "internal sync",
        "ProviderApplicationID": self_app, "ConsumerApplicationID": self_app,
        "Protocol": "REST", "Format": "JSON", "Frequency": "Hourly", "Status": "Active",
    })
    # Seeded scenario: interface hanging off a ghost application.
    if ghosts:
        ifaces.append({
            "InterfaceID": "IF-8901", "InterfaceName": "legacy extract",
            "ProviderApplicationID": ghosts[-1], "ConsumerApplicationID": pick(),
            "Protocol": "SFTP", "Format": "CSV", "Frequency": "Daily", "Status": "Active",
        })

    # --- InformationObjects --------------------------------------------------
    infos = []
    data_names = ["Customer Record", "Vehicle Master", "Order Header", "Invoice",
                  "Warranty Claim", "Telematics Event", "Parts Price",
                  "Employee Record", "Dealer Profile", "Payment Instruction",
                  "Production Order", "Service Booking", "Campaign Response"]
    for i in range(int(n_apps * 1.4)):
        carrier = rnd.choice(ifaces)
        blank_class = rnd.random() < 0.12          # seeded: unclassified data
        infos.append({
            "InformationObjectID": f"IO-{i + 1:04d}",
            "InformationObjectName": rnd.choice(data_names),
            "SourceApplicationID": carrier["ProviderApplicationID"],
            "TargetApplicationID": carrier["ConsumerApplicationID"],
            "Classification": "" if blank_class else rnd.choice(CLASSIFICATION),
            "InterfaceID": carrier["InterfaceID"],
        })

    # --- BusinessProcesses ---------------------------------------------------
    procs = []
    for i, app_id in enumerate(rnd.sample(app_ids, k=int(n_apps * 0.75))):
        procs.append({
            "BusinessProcessID": f"BP-{i + 1:04d}",
            "ProcessName": rnd.choice(PROCESS_NAMES),
            "BusinessDomain": rnd.choice(DOMAINS),
            "SupportingApplicationID": app_id,
        })

    # --- ApplicationOwnership ------------------------------------------------
    owners = []
    # Seeded scenario: ~12% of applications have no ownership row at all.
    owned_apps = rnd.sample(app_ids, k=int(n_apps * 0.88))
    first = ["Ana", "Bruno", "Clara", "Diogo", "Eva", "Filipe", "Gita", "Henrik",
             "Ines", "Jonas", "Karin", "Luis", "Marta", "Nuno", "Olga", "Pedro"]
    last = ["Almeida", "Braun", "Costa", "Dias", "Engel", "Ferreira", "Gomes",
            "Hoffmann", "Iyer", "Jansen", "Klein", "Lopes", "Meier", "Novak"]
    for app_id in owned_apps:
        blank_owner = rnd.random() < 0.10          # seeded: incomplete ownership
        owners.append({
            "ApplicationID": app_id,
            "Owner": "" if blank_owner else f"{rnd.choice(first)} {rnd.choice(last)}",
            "Custodian": f"{rnd.choice(first)} {rnd.choice(last)}",
            "BusinessOwner": ("" if rnd.random() < 0.08
                              else f"{rnd.choice(first)} {rnd.choice(last)}"),
            "SupportGroup": f"TEAM-{rnd.randint(100, 999)}",
        })

    # --- KnownDataQualityGaps (deliberately PARTIAL) -------------------------
    gaps = [{
        "GapID": "GAP-0001", "GapType": "Broken reference",
        "AffectedID": ghosts[0] if ghosts else "",
        "Description": "Referenced application does not exist in the inventory.",
    }]
    no_owner = [a for a in app_ids if a not in owned_apps][:2]
    for j, app_id in enumerate(no_owner, start=2):
        gaps.append({
            "GapID": f"GAP-{j:04d}", "GapType": "Missing ownership",
            "AffectedID": app_id,
            "Description": "No ownership record for this application.",
        })

    return {
        "Applications": pd.DataFrame(apps),
        "Relationships": pd.DataFrame(rels),
        "Interfaces": pd.DataFrame(ifaces),
        "InformationObjects": pd.DataFrame(infos),
        "BusinessProcesses": pd.DataFrame(procs),
        "ApplicationOwnership": pd.DataFrame(owners),
        "KnownDataQualityGaps": pd.DataFrame(gaps),
    }


def write(sheets: dict[str, pd.DataFrame], path: str) -> str:
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        for name, df in sheets.items():
            df.to_excel(xl, sheet_name=name, index=False)
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate a synthetic EA workbook.")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--apps", type=int, default=64)
    ap.add_argument("--out", default="sample_ea_dataset.xlsx")
    args = ap.parse_args()

    data = generate(seed=args.seed, n_apps=args.apps)
    write(data, args.out)
    print(f"Wrote {args.out} (seed={args.seed})")
    for k, v in data.items():
        print(f"  {k:<22} {len(v):>5} rows")
