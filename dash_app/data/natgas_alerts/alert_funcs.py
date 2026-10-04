import time
import requests
import pandas as pd
import folium
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from concurrent.futures import ThreadPoolExecutor

# Severity → color intensity mapping
SEVERITY_COLORS = {
    "Minor": "#FFF59D",      # soft yellow
    "Moderate": "#FFB74D",   # orange
    "Severe": "#E53935",     # red
    None: "#B0BEC5"          # default grey
}
BASE_URL = "https://api.weather.gov/alerts/active"
# NWS asks that the User-Agent identify your app plus a contact
HEADERS = {"User-Agent": "FlowGos weather alerts (your-email@example.com)"}

ALERT_CACHE_SECONDS = 120   # how long a fetched alert list is reused
MAX_WORKERS = 8 # parallel zone downloads from NOAA
MIN_FORCE_SECONDS = 30 # prevents user button spamming from overloading NOAA API

_alert_cache = {}  # (event_name, area) -> (time_fetched, DataFrame)
_zone_cache = {}   # zone_url -> geometry dict (zones rarely change, keep forever)

# Keyless basemap: Esri World Light Gray Canvas (closest look to CARTO Positron)
ESRI_GRAY_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
)
ESRI_GRAY_ATTR = "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ"

def make_base_map(location, zoom_start):
    return folium.Map(
        location=location,
        zoom_start=zoom_start,
        tiles=ESRI_GRAY_URL,
        attr=ESRI_GRAY_ATTR,  # folium requires attr when you pass a custom URL
    )

def fetch_zone_geometry(zone_url):
    """Download one zone's polygon. Returns None on failure. Runs inside threads,
    so it does NOT touch the cache; the main thread does that."""
    try:
        resp = requests.get(zone_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        return resp.json().get("geometry")
    except (requests.RequestException, ValueError):
        return None

def prefetch_zones(alerts):
    """Find every unique zone we still need, and download them in parallel."""
    needed = set()
    for alert in alerts:
        if alert.get("geometry"):
            continue  # alert has its own polygon, no zones needed
        for url in alert.get("properties", {}).get("affectedZones", []):
            if url not in _zone_cache:
                needed.add(url)

    if not needed:
        return

    needed = list(needed)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(fetch_zone_geometry, needed))

    # Write to the cache here, in the main thread, after all downloads finish
    for url, geom in zip(needed, results):
        if geom:
            _zone_cache[url] = geom

def get_alert_geometry(alert):
    """Build the alert's shape from its own polygon, or from cached zones."""
    if alert.get("geometry"):
        return shape(alert["geometry"])

    zone_urls = alert.get("properties", {}).get("affectedZones", [])
    shapes = [shape(_zone_cache[url]) for url in zone_urls if url in _zone_cache]

    if not shapes:
        return None
    return unary_union(shapes)

def _download_alerts(event_name=None, area=None):
    params = {}
    if event_name:
        params["event"] = event_name
    if area:
        params["area"] = area

    response = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=20)
    response.raise_for_status()
    alerts = response.json().get("features", [])
    prefetch_zones(alerts)

    records = []
    for alert in alerts:
        props = alert.get("properties", {})

        try:
            merged_geom = get_alert_geometry(alert)
        except Exception:
            merged_geom = None

        lat, lon = None, None
        if merged_geom is not None and not merged_geom.is_empty:
            centroid = merged_geom.centroid
            lon, lat = centroid.x, centroid.y

        records.append({
            "id": props.get("id"),
            "area": props.get("areaDesc"),
            "event": props.get("event"),
            "severity": props.get("severity"),
            "certainty": props.get("certainty"),
            "urgency": props.get("urgency"),
            "effective": props.get("effective"),
            "expires": props.get("expires"),
            "headline": props.get("headline"),
            "description": props.get("description"),
            "instruction": props.get("instruction"),
            "latitude": lat,
            "longitude": lon,
            "geometry": merged_geom.__geo_interface__ if merged_geom is not None else None,
        })

    return pd.DataFrame(records)

def fetch_noaa_alerts(event_name=None, area=None, force_refresh=False):
    """
    Returns alerts from NOAA, reusing a cached copy if it is younger than ALERT_CACHE_SECONDS
    When user clicks the refresh button, if data is younger than ALERT_CACHE_SECONDS it still uses the cache
    otherwise, refresh button skips the normal 2-minute cache held
    """
    key = (event_name, area)
    now = time.time()

    if key in _alert_cache:
        time_fetched, saved_df = _alert_cache[key]
        max_age = MIN_FORCE_SECONDS if force_refresh else ALERT_CACHE_SECONDS
        if now - time_fetched < max_age:
            return saved_df.copy()

    df = _download_alerts(event_name, area)
    _alert_cache[key] = (now, df)

    return df.copy()

# --- Map Visualization ---
# Initialize folium map (centered on continental US)
def create_alert_map(alert_df, zoom_start=5):

    if alert_df.empty:
        return make_base_map([-39.8283, -98.5795], zoom_start=4)
    
    # Compute map center
    lat_center = alert_df["latitude"].dropna().mean()
    lon_center = alert_df["longitude"].dropna().mean()
    if pd.isna(lat_center) or pd.isna(lon_center):
        lat_center, lon_center = 39.8283, -98.5795

    m = make_base_map([lat_center, lon_center], zoom_start=zoom_start)

    # Iterate through alerts
    for _, record in alert_df.iterrows():
        severity = record.get("severity")
        urgency = record.get("urgency")
        latitude = record.get("latitude")
        longitude = record.get("longitude")
        color = SEVERITY_COLORS.get(severity, "#90A4AE")

        # --- Polygon rendering ---
        if record.get("geometry") is not None:
            try:
                geom_obj = shape(record["geometry"])
                opacity = {"Minor": 0.35, "Moderate": 0.55}.get(severity, 0.75)
                
                folium.GeoJson(
                    mapping(geom_obj),
                    style_function=lambda feature, col=color, op=opacity: {
                        "fillColor": col,
                        "color": col,
                        "weight": 1.5,
                        "fillOpacity": op,
                    },
                    tooltip=(
                        f"<b>{record['event']}</b><br>"
                        f"Severity: {severity}<br>"
                        f"Urgency: {urgency}<br>"
                        f"Latitude: {latitude}<br>"
                        f"Longitude: {longitude}<br>"
                        f"Expires: {record['expires']}"
                    )
                ).add_to(m)
            except Exception:
                pass

        # --- Centroid markers ---
        if pd.notnull(record["latitude"]) and pd.notnull(record["longitude"]):
            folium.CircleMarker(
                location=[record["latitude"], record["longitude"]],
                radius=5,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.9,
                tooltip=f"{record['event']} ({severity})"
            ).add_to(m)

    # --- Add a legend ---
    legend_html = """
    <div style="position: fixed; bottom: 50px; left: 50px; z-index:9999; font-size:14px;">
        <b>Severity Legend</b><br>
        <i style="background:#E53935;width:20px;height:10px;display:inline-block;margin-right:5px;"></i> Severe<br>
        <i style="background:#FFB74D;width:20px;height:10px;display:inline-block;margin-right:5px;"></i> Moderate<br>
        <i style="background:#FFF59D;width:20px;height:10px;display:inline-block;margin-right:5px;"></i> Minor
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    return m

if __name__ == "__main__":
    df = fetch_noaa_alerts()
    print(len(df))