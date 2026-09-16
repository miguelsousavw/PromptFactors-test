"""
ingest.py - DETERMINISTIC layer.

Loads the LeanIX-style EA workbook, normalises column names, and validates
structure. Nothing here is hard-coded to specific row IDs: every sheet and
every key is resolved by name, so a modified copy of the workbook (different
IDs, extra rows, extra scenarios) loads exactly the same way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

# ---------------------------------------------------------------------------
# Expected workbook shape. Sheets are matched loosely (case/space insensitive)
# so a renamed-but-recognisable sheet still loads.
# ---------------------------------------------------------------------------

SHEET_SPEC: dict[str, dict] = {
    "Applications": {
        "required": ["ApplicationID"],
        "optional": [
            "ApplicationName", "Description", "BusinessDomain",
            "BusinessCriticality", "LifecycleStatus", "LifecycleStartDate",
            "LifecycleEndDate", "Hosting", "VendorType", "OwnerEmployeeID",
            "CostCenter",
        ],
        "role": "Application master data (graph nodes).",
    },
    "Relationships": {
        "required": ["SourceApplicationID", "TargetApplicationID"],
        "optional": ["RelationshipID", "RelationshipType", "Description"],
        "role": "Directed application-to-application dependencies (graph edges).",
    },
    "Interfaces": {
        "required": ["InterfaceID", "ProviderApplicationID", "ConsumerApplicationID"],
        "optional": ["InterfaceName", "Protocol", "Format", "Frequency", "Status"],
        "role": "Provider/consumer integrations.",
    },
    "InformationObjects": {
        "required": ["SourceApplicationID", "TargetApplicationID"],
        "optional": [
            "InformationObjectID", "InformationObjectName", "Classification",
            "InterfaceID",
        ],
        "role": "What data flows source -> target, and via which interface.",
    },
    "BusinessProcesses": {
        "required": ["SupportingApplicationID"],
        "optional": ["BusinessProcessID", "ProcessName", "BusinessDomain"],
        "role": "Business process to supporting application mapping.",
    },
    "ApplicationOwnership": {
        "required": ["ApplicationID"],
        "optional": ["Owner", "Custodian", "BusinessOwner", "SupportGroup"],
        "role": "Ownership and custodianship per application.",
    },
    "KnownDataQualityGaps": {
        "required": [],
        "optional": ["GapID", "GapType", "Description", "AffectedID"],
        "role": "PARTIAL pre-declared gap list. Used only as a baseline to "
                "separate already-known gaps from newly discovered ones.",
    },
}

# Foreign keys -> the sheet/column they must resolve against.
FOREIGN_KEYS: list[tuple[str, str]] = [
    ("Relationships", "SourceApplicationID"),
    ("Relationships", "TargetApplicationID"),
    ("Interfaces", "ProviderApplicationID"),
    ("Interfaces", "ConsumerApplicationID"),
    ("InformationObjects", "SourceApplicationID"),
    ("InformationObjects", "TargetApplicationID"),
    ("BusinessProcesses", "SupportingApplicationID"),
    ("ApplicationOwnership", "ApplicationID"),
]


def _norm(s: str) -> str:
    """Normalise a sheet or column name for fuzzy matching."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


@dataclass
class EADataset:
    """A loaded, validated workbook."""

    sheets: dict[str, pd.DataFrame] = field(default_factory=dict)
    load_report: list[dict] = field(default_factory=list)
    source_name: str = "uploaded workbook"

    def has(self, sheet: str) -> bool:
        return sheet in self.sheets and not self.sheets[sheet].empty

    def df(self, sheet: str) -> pd.DataFrame:
        return self.sheets.get(sheet, pd.DataFrame())

    def app_ids(self) -> set[str]:
        apps = self.df("Applications")
        if apps.empty or "ApplicationID" not in apps.columns:
            return set()
        return set(apps["ApplicationID"].dropna().astype(str))

    def app_name(self, app_id: str) -> str:
        apps = self.df("Applications")
        if apps.empty or "ApplicationName" not in apps.columns:
            return str(app_id)
        hit = apps.loc[apps["ApplicationID"].astype(str) == str(app_id)]
        if hit.empty:
            return str(app_id)
        return str(hit.iloc[0].get("ApplicationName") or app_id)

    def summary(self) -> dict[str, int]:
        return {name: len(df) for name, df in self.sheets.items()}


def load_workbook(file_like, source_name: str = "uploaded workbook") -> EADataset:
    """Read every recognised sheet from an .xlsx file object or path."""
    raw = pd.read_excel(file_like, sheet_name=None, dtype=object)
    ds = EADataset(source_name=source_name)

    norm_lookup = {_norm(k): k for k in raw}

    for canonical, spec in SHEET_SPEC.items():
        actual = norm_lookup.get(_norm(canonical))
        if actual is None:
            ds.load_report.append({
                "Sheet": canonical, "Status": "MISSING", "Rows": 0,
                "Detail": "Sheet not found in workbook.",
            })
            continue

        df = raw[actual].copy()
        # Normalise column names to the canonical spelling where we recognise them.
        known = spec["required"] + spec["optional"]
        col_lookup = {_norm(c): c for c in df.columns}
        rename: dict[str, str] = {}
        for want in known:
            got = col_lookup.get(_norm(want))
            if got is not None and got != want:
                rename[got] = want
        df = df.rename(columns=rename)

        # Strip whitespace on all object columns so joins behave.
        for c in df.columns:
            if df[c].dtype == object:
                df[c] = df[c].apply(lambda v: v.strip() if isinstance(v, str) else v)

        df = df.dropna(how="all")

        missing_req = [c for c in spec["required"] if c not in df.columns]
        status = "OK" if not missing_req else "DEGRADED"
        detail = spec["role"] if not missing_req else (
            f"Missing required column(s): {', '.join(missing_req)}. "
            "Checks depending on them will be skipped."
        )

        ds.sheets[canonical] = df
        ds.load_report.append({
            "Sheet": canonical, "Status": status, "Rows": len(df), "Detail": detail,
        })

    return ds


def validate(ds: EADataset) -> list[dict]:
    """Structural validation, run before any graph is built."""
    issues: list[dict] = []

    if not ds.has("Applications"):
        issues.append({
            "Severity": "BLOCKER",
            "Check": "Applications sheet",
            "Detail": "No Applications sheet or it is empty. Nothing can be built.",
        })
        return issues

    apps = ds.df("Applications")

    dup = apps[apps.duplicated("ApplicationID", keep=False)]
    if not dup.empty:
        issues.append({
            "Severity": "HIGH",
            "Check": "Duplicate ApplicationID",
            "Detail": f"{dup['ApplicationID'].nunique()} ApplicationID value(s) appear more "
                      f"than once ({len(dup)} rows). Later rows may shadow earlier ones.",
        })

    blank = apps["ApplicationID"].isna().sum()
    if blank:
        issues.append({
            "Severity": "HIGH",
            "Check": "Blank ApplicationID",
            "Detail": f"{blank} application row(s) have no ApplicationID and are unusable as nodes.",
        })

    for sheet, col in FOREIGN_KEYS:
        if not ds.has(sheet) or col not in ds.df(sheet).columns:
            continue
        vals = ds.df(sheet)[col].dropna().astype(str)
        unknown = sorted(set(vals) - ds.app_ids())
        if unknown:
            preview = ", ".join(unknown[:6]) + (" ..." if len(unknown) > 6 else "")
            issues.append({
                "Severity": "HIGH",
                "Check": f"{sheet}.{col} -> Applications.ApplicationID",
                "Detail": f"{len(unknown)} referenced ID(s) do not exist in Applications: {preview}",
            })

    if not issues:
        issues.append({
            "Severity": "INFO",
            "Check": "Structural validation",
            "Detail": "All sheets present and all foreign keys resolve.",
        })
    return issues
