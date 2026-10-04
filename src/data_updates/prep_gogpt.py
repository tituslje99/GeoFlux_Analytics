"""
GOGPT August 2026 -> two tidy tables for the map.

1. units      one row per generating unit  (the tooltip / detail table)
2. locations  one row per plant site       (the map markers)
"""

import re
from pathlib import Path
import pandas as pd

SHEETS = ["Gas & Oil Units", "IRP Units", "Sub-Threshold Units"]

# statuses that go on the primary map layer
ACTIVE = {"operating", "construction", "pre-construction"}

COLUMNS = {
    "GEM unit ID": "unit_id",
    "GEM location ID": "location_id",
    "Plant name": "plant_name",
    "Unit name": "unit_name",
    "Country/Area": "country",
    "State/Province": "state",
    "City": "city",
    "Subregion": "subregion",
    "Region": "region",
    "Latitude": "lat",
    "Longitude": "lon",
    "Location accuracy": "location_accuracy",
    "Capacity (MW)": "capacity_mw",
    "Status": "status",
    "Turbine/Engine Technology": "technology",
    "Fuel": "fuel_raw",
    "Fuel classification": "fuel_class",
    "CHP": "chp",
    "CCS attachment?": "ccs",
    "Captive industry use": "captive_use",
    "Captive industry type": "captive_type",
    "Start year": "start_year",
    "Planned retire": "planned_retire",
    "Retired year": "retired_year",
    "Operator(s)": "operator",
    "Owner(s)": "owner",
    "Owner(s) GEM Entity ID": "owner_entity_id",
    "Parent(s)": "parent",
    "Parent GEM Entity ID": "parent_entity_id",
    "Wiki URL": "wiki_url",
}


# ---------------------------------------------------------------- fuel parsing

SHARE = re.compile(r"\[(\d+)%\]\s*$")


def parse_fuel(text):
    """'fossil gas: natural gas [80%], fossil liquids: fuel oil [20%]'
    -> [('fossil gas', 'natural gas', 80.0), ('fossil liquids', 'fuel oil', 20.0)]"""
    if not isinstance(text, str) or not text.strip():
        return []

    out = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue

        share = None
        m = SHARE.search(token)
        if m:
            share = float(m.group(1))
            token = SHARE.sub("", token).strip()

        if ":" in token:
            category, fuel = token.split(":", 1)
        else:
            category, fuel = token, ""

        category, fuel = category.strip(), fuel.strip()
        if not fuel:          # e.g. 'fossil gas: natural gas, fossil gas:'
            fuel = "unspecified"
        out.append((category, fuel, share))
    return out


def fuel_columns(text):
    parts = parse_fuel(text)
    categories = list(dict.fromkeys(c for c, _, _ in parts))
    fuels = list(dict.fromkeys(f"{c}: {f}" for c, f, _ in parts))
    shares = [s for _, _, s in parts if s is not None]
    n_unlabelled = len(parts) - len(shares)
    labelled_sum = sum(shares) if shares else None

    # GEM labels only the minority/blended fuel and leaves the remainder
    # implied, so "sums to 100" is the wrong test. A row is only suspect if
    # every fuel carries a share and they still miss 100, or they exceed 100.
    share_issue = bool(shares) and (
        (n_unlabelled == 0 and labelled_sum != 100) or labelled_sum > 100
    )

    return pd.Series({
        "fuel_categories": " | ".join(categories),
        "fuel_list": " | ".join(fuels),
        "primary_fuel": fuels[0] if fuels else "",
        "n_fuels": len(fuels),
        # flags rather than filters - decide later what to keep
        "burns_oil_or_gas": any(c in ("fossil gas", "fossil liquids") for c in categories),
        "burns_byproduct_gas": "industrial by-product" in categories,
        "labelled_share_sum": labelled_sum,
        "share_issue": share_issue,
    })


# ------------------------------------------------------------------ status

def status_group(status):
    """'cancelled - inferred 4 y' -> 'cancelled'; then bucket."""
    base = base_status(status)
    if base in ACTIVE:
        return "active"
    if base == "planning":
        return "planning"          # IRP sheet only
    return "inactive"              # announced, shelved, cancelled, mothballed, retired


def base_status(status):
    """Strip only the ' - inferred N y' suffix.
    Not a bare '-' split: that would turn 'pre-construction' into 'pre'."""
    return str(status).split(" - ")[0].strip().lower()


# ------------------------------------------------------------------ pipeline

def load_units(path):
    frames = []
    for sheet in SHEETS:
        df = pd.read_excel(path, sheet_name=sheet)
        df = df[list(COLUMNS)].rename(columns=COLUMNS)
        df["source_sheet"] = sheet
        df["sub_threshold"] = sheet == "Sub-Threshold Units"
        df["is_irp"] = sheet == "IRP Units"
        frames.append(df)

    units = pd.concat(frames, ignore_index=True)

    units = units.join(units["fuel_raw"].apply(fuel_columns))
    units["status_base"] = units["status"].apply(base_status)
    units["status_group"] = units["status"].apply(status_group)

    for col in ["start_year", "planned_retire", "retired_year"]:
        units[col] = units[col].astype("Int64")

    return units


def build_locations(units):
    """Collapse to plant sites - what the map actually draws."""

    def join_unique(s):
        return " | ".join(dict.fromkeys(str(x) for x in s.dropna()))

    # keyed by individual status, not by bucket: the app sums whichever
    # statuses are toggled on, so filtering never needs a re-aggregation
    loc = units.groupby(["location_id", "status_base"], as_index=False).agg(
        status_group=("status_group", "first"),
        plant_name=("plant_name", "first"),
        country=("country", "first"),
        state=("state", "first"),
        city=("city", "first"),
        region=("region", "first"),
        subregion=("subregion", "first"),
        lat=("lat", "median"),
        lon=("lon", "median"),
        location_accuracy=("location_accuracy", "first"),
        capacity_mw=("capacity_mw", "sum"),
        n_units=("unit_id", "count"),
        statuses=("status", join_unique),
        n_sites=("location_id", "nunique"),
        fuel_class=("fuel_class", join_unique),
        fuel_categories=("fuel_categories", join_unique),
        technologies=("technology", join_unique),
        owner=("owner", join_unique),
        owner_entity_id=("owner_entity_id", join_unique),
        parent=("parent", join_unique),
        parent_entity_id=("parent_entity_id", join_unique),
        start_year_min=("start_year", "min"),
        start_year_max=("start_year", "max"),
        burns_oil_or_gas=("burns_oil_or_gas", "any"),
        burns_byproduct_gas=("burns_byproduct_gas", "any"),
        n_planned_retire=("planned_retire", "count"),
        sub_threshold=("sub_threshold", "all"),
        is_irp=("is_irp", "all"),
        wiki_url=("wiki_url", "first"),
    )
    return loc

def find_downwards(start_dir, target_name):
    # Convert string path to a Path object
    path = Path(start_dir).resolve()
    
    # rglob searches all folders and files recursively
    for match in path.rglob(target_name):
        return str(match.resolve()) # Returns absolute path of first match
        
    return None # Return None if not found

def find_upwards(start_dir, target_name):
    path = Path(start_dir).resolve()

    for folder in [path] + list(path.parents):
        candidate = folder / target_name
        if candidate.exists():
            return str(candidate)

    return None

def find_path_bothways(start_dir, target_name):
    result = find_downwards(start_dir, target_name)
    if result is not None:
        return result
    return find_upwards(start_dir, target_name)