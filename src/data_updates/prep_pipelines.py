"""
GEM pipeline + LNG GeoJSON -> light files for the map tab.

Prepares raw GEM pipeline and LNG terminals data, distilled into 4 sources:
1. lines       simplified line geometry, active statuses only, pre-split into one lat/lon array per (fuel, status)
2. meta        one row per pipeline feature: tooltip + midpoint
3. undrawable  features with no route - for you to verify
4. lng         one row per LNG unit

Run: python prep_pipelines.py
Parses the 140 MB of GeoJSON once before passing to parquet on R2 Cloudflare, then to Dash app
"""

import gc
import json
from pathlib import Path

import pandas as pd
from shapely import get_num_coordinates, get_parts, simplify
from shapely.geometry import shape
from shapely.ops import linemerge

FILES = {
    "gas": (Path("GEM-GGIT-Gas-Pipelines-2025-11.geojson"), "CapacityBcm/y", "bcm/y"),
    "oil": (Path("GEM-GOIT-Oil-NGL-Pipelines-2026-07-21.geojson"), "CapacityBOEd", "boe/d"),
}
LNG_FILE = Path("GEM-GGIT-LNG-Terminals-2025-09.geojson")

TOLERANCE = 0.01      # deg, ~1.1 km - measured: 98.6% of oil vertices removed
MIN_PART = 0.002      # deg, ~220 m - drops micro-segments, keeps 99.95% of length
DECIMALS = 3          # ~110 m, finer than the tolerance so nothing is lost

# GEM pipeline/LNG statuses -> the plant vocabulary, so one toggle drives all layers
STATUS_MAP = {
    "operating": "operating",
    "construction": "construction",
    "proposed": "pre-construction",
}
ACTIVE = ["operating", "construction", "pre-construction"]


def to_plant_status(s):
    """Unmapped statuses (cancelled, shelved, retired, mothballed, idle, idled,
    mixed status) keep their own name and fall in the inactive group."""
    return STATUS_MAP.get(str(s).strip().lower(), str(s).strip().lower())


def to_number(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- geometry

def clean_geometry(geom_json):
    """Return a list of simplified LineStrings, or [] if nothing is drawable."""
    if not geom_json:
        return []
    g = shape(geom_json)
    if g.is_empty:                              # the empty GeometryCollections
        return []
    if g.geom_type == "MultiLineString":
        g = linemerge(g)                        # joins touching 2-point segments
    g = simplify(g, TOLERANCE)
    return [p for p in get_parts(g) if p.length >= MIN_PART]


def midpoint(parts):
    """Tooltip anchor: halfway along the longest part."""
    longest = max(parts, key=lambda p: p.length)
    pt = longest.interpolate(0.5, normalized=True)
    return round(pt.y, 4), round(pt.x, 4)


def append_line(bucket, part):
    """Plotly draws many lines in one trace when they are separated by None."""
    xs, ys = part.xy
    bucket["lon"].extend(round(v, DECIMALS) for v in xs)
    bucket["lat"].extend(round(v, DECIMALS) for v in ys)
    bucket["lon"].append(None)
    bucket["lat"].append(None)


# ---------------------------------------------------------------- pipelines

def process_pipelines(folder):
    lines = {}
    meta, undrawable = [], []
    stats = {}

    for fuel, (fname, cap_col, cap_unit) in FILES.items():
        feats = json.load(open(folder / fname, encoding="utf-8"))["features"]
        lines[fuel] = {s: {"lat": [], "lon": []} for s in ACTIVE}
        raw_v = kept_v = 0
        bad_capacity = []

        for f in feats:
            p = f["properties"]
            status = to_plant_status(p.get("Status"))
            row = {
                "layer": f"{fuel} pipeline",
                "fuel": fuel,
                "sub_fuel": p.get("Fuel"),               # Oil / NGL on the oil file
                "project_id": p.get("ProjectID"),
                "name": p.get("PipelineName"),
                "segment": p.get("SegmentName") or None,
                "status_raw": p.get("Status"),
                "status_base": status,
                "status_group": "active" if status in ACTIVE else "inactive",
                "capacity": to_number(p.get(cap_col)),
                "capacity_unit": cap_unit,
                "length_km": to_number(p.get("LengthMergedKm")),
                "diameter": p.get("Diameter") or None,
                "diameter_units": p.get("DiameterUnits") or None,
                "start_year": p.get("StartYear1") or None,
                "countries": p.get("CountriesOrAreas"),
                "owner": p.get("Owner"),
                "parent": p.get("Parent"),
                "parent_entity_ids": p.get("ParentEntityIDs") or p.get("OwnerEntityIDs"),
                "route_accuracy": p.get("RouteAccuracy"),
                # GEM umbrella rows ('SYSTEM/NETWORK INFO' / '... ROUTE') summarise
                # a whole system whose segments are also listed: drawing them is
                # harmless, summing their km or capacity double-counts
                "is_system_record": str(p.get("SegmentName") or "").upper()
                                    .startswith("SYSTEM/NETWORK"),
                "wiki_url": p.get("Wiki"),
            }
            # '--' is GEM's placeholder for unknown, not a data error
            if row["capacity"] is None and p.get(cap_col) not in (None, "", "--"):
                bad_capacity.append((row["project_id"], p.get(cap_col)))

            if f["geometry"]:
                raw_v += get_num_coordinates(shape(f["geometry"]))
            parts = clean_geometry(f["geometry"])

            if not parts:
                row["reason"] = ("empty geometry" if f["geometry"] else "no geometry")
                undrawable.append(row)
                continue

            row["mid_lat"], row["mid_lon"] = midpoint(parts)
            meta.append(row)

            if status in ACTIVE:
                for part in parts:
                    kept_v += get_num_coordinates(part)
                    append_line(lines[fuel][status], part)

        stats[fuel] = dict(features=len(feats), raw_vertices=raw_v,
                           kept_vertices=kept_v, bad_capacity=bad_capacity)
        del feats
        gc.collect()

    return lines, pd.DataFrame(meta), pd.DataFrame(undrawable), stats


# ---------------------------------------------------------------- LNG

def process_lng(folder):
    feats = json.load(open(folder / LNG_FILE, encoding='utf-8'))["features"]
    rows = []
    for f in feats:
        p = f["properties"]
        status = to_plant_status(p.get("Status"))
        lon, lat = f["geometry"]["coordinates"]
        rows.append({
            "layer": "LNG terminal",
            "unit_id": p.get("UnitID"),
            "project_id": p.get("ProjectID"),
            "name": p.get("TerminalName"),
            "unit_name": p.get("UnitName") or None,
            "facility_type": p.get("FacilityType"),
            "status_raw": p.get("Status"),
            "status_base": status,
            "status_group": "active" if status in ACTIVE else "inactive",
            "capacity_mtpa": to_number(p.get("CapacityinMtpa")),
            "capacity_bcmy": to_number(p.get("CapacityinBcm/y")),
            "start_year": to_number(p.get("ActualStartYear")),
            "country": p.get("Country/Area"),
            "owner": p.get("Owner"),
            "parent": p.get("Parent"),
            "parent_entity_ids": p.get("Parent GEM Entity ID"),
            "floating": p.get("Floating") == 1,
            "power_plants_supplied": p.get("PowerPlantsSupplied") or None,
            "location_accuracy": p.get("Accuracy"),
            "lat": lat,
            "lon": lon,
            # properties carry their own lat/long; kept to check they agree
            "prop_lat": to_number(p.get("Latitude")),
            "prop_lon": to_number(p.get("Longitude")),
            "wiki_url": p.get("Wiki"),
        })
    return pd.DataFrame(rows)

def find_path(start_dir, target_name):
    # Convert string path to a Path object
    path = Path(start_dir)
    
    # rglob searches all folders and files recursively
    for match in path.rglob(target_name):
        return str(match.resolve()) # Returns absolute path of first match
        
    return None # Return None if not found

if __name__ == "__main__":
    current_dir = Path.cwd()
    folder = find_path(current_dir, "pipeline_data")

    lines, meta, undrawable, stats = process_pipelines(folder)
    with open(folder / Path("pipelines_lines.json"), "w", encoding='utf-8') as fh:
        json.dump(lines, fh, separators=(",", ":"))
    meta.to_csv(folder / Path("pipelines_meta.csv"), index=False)
    undrawable.to_csv(folder / Path("pipelines_undrawable.csv"), index=False)

    lng = process_lng(folder)
    lng.to_csv(folder / Path("lng_terminals.csv"), index=False)

    for fuel, s in stats.items():
        print(f"{fuel}: {s['features']:,} features, vertices "
              f"{s['raw_vertices']:,} -> {s['kept_vertices']:,} (active only), "
              f"unparseable capacity: {len(s['bad_capacity'])}")
    print(f"meta {len(meta):,} | undrawable {len(undrawable):,} | lng {len(lng):,}")