"""
Oil & gas infrastructure map - a self-contained Dash tab.

Layers: power plants (GOGPT), gas pipelines (GGIT), oil & NGL pipelines (GOIT),
LNG terminals (GGIT). One STATUS toggle drives every layer; GEM's pipeline/LNG
'proposed' is mapped to 'pre-construction' in prep_pipelines.py.

Merge into an existing app:

    app = Dash(__name__, suppress_callback_exceptions=True)
    from plant_map_tab import layout, register_callbacks
    # render layout() from your tab callback, then:
    register_callbacks(app)

Performance design: the full figure (incl. ~172k pipeline vertices) is sent
ONCE when the tab renders. Every later interaction sends a dash.Patch holding
only what changed - visibility flags, colours, or the plant markers - never
the pipeline geometry again.
"""

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, Patch, ctx, dcc, html, register_page, callback
from dash_app.data.store import load_gem_data

# Register as page under main app
register_page(
    __name__,
    path="/global_assets_tracker",
    name="Oil and Gas",
    title="Oil & Gas Assets Tracker"
)

# ---------------------------------------------------------------- palette

BG, PANEL, GRID = "#0b0b0c", "#141416", "#2a2a2e"
TEXT, MUTED, AMBER = "#d8d8d2", "#7a7a80", "#ff9e1b"
FONT = "Bergoom, 'Source Sans 3', system-ui, sans-serif"

STATUS_ORDER = ["operating", "construction", "pre-construction"]
PIPE_FUELS = ["gas", "oil"]

# Plants: fill colour by fuel class. Scattermap markers have no border, so the
# light-basemap palette darkens the same hues until they hold against white.
PLANT = {
    "dark":  {"Gas": "#00a3e0", "LNG only": "#7ad7f0", "Oil": "#ff5c35",
              "Multi Fuel": AMBER, "Byproduct gas": "#9a6bd6"},
    "light": {"Gas": "#00527a", "LNG only": "#0e7fa3", "Oil": "#c22e0d",
              "Multi Fuel": "#a35c00", "Byproduct gas": "#5b2f8f"},
}
PLANT_OPACITY = {"operating": 0.85, "construction": 0.65, "pre-construction": 0.45}

# Pipelines: Scattermap lines support only colour and width (no dashes), so
# status is carried by alpha and width, mirroring the plant opacity ladder.
PIPE_RGB = {
    "dark":  {"gas": (64, 160, 255), "oil": (255, 110, 64)},
    "light": {"gas": (0, 82, 122),   "oil": (170, 50, 20)},
}
PIPE_ALPHA = {"dark":  {"operating": 0.80, "construction": 0.55, "pre-construction": 0.30},
              "light": {"operating": 0.85, "construction": 0.60, "pre-construction": 0.40}}
PIPE_WIDTH = {"operating": 1.4, "construction": 1.4, "pre-construction": 1.0}

LNG = {"dark":  {"import": "#f2f2f2", "export": "#ffd400", None: "#9a9a9a"},
       "light": {"import": "#1a1a1a", "export": "#b38f00", None: "#555555"}}

BASEMAPS = {"dark": ("carto-darkmatter", "dark"),
            "detail": ("carto-voyager", "light"),
            "sat": ("satellite", "light")}


def rgba(rgb, a):
    return f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{a})"

def find_path(start_dir, target_name):
    # Convert string path to a Path object
    path = Path(start_dir)
    
    # rglob searches all folders and files recursively
    for match in path.rglob(target_name):
        return str(match.resolve()) # Returns absolute path of first match
        
    return None # Return None if not found

# ---------------------------------------------------------------- data

def _txt(s, n=48):
    return s.fillna("n/a").astype(str).str.slice(0, n)


@lru_cache(maxsize=1)
def load_all():
    """Read every file once per process; layout() and callbacks share it."""
    plants, meta, lng, lines = load_gem_data()

    # plants --------------------------------------------------------------
    plants = plants[plants.status_group == "active"].copy()
    plants["fuel_key"] = plants.fuel_class.fillna("").str.split(" | ", regex=False).str[0]
    plants.loc[~plants.burns_oil_or_gas, "fuel_key"] = "Byproduct gas"
    plants["size"] = (plants.capacity_mw.clip(lower=1) ** 0.5).clip(4, 34)
    plants["hover"] = (
        "<b>" + _txt(plants.plant_name) + "</b><br>"
        + plants.country.fillna("") + "<br>"
        + plants.capacity_mw.round(0).astype(int).astype(str) + " MW / "
        + plants.n_units.astype(str) + " units<br>"
        + "status: " + plants.status_base + "<br>"
        + "fuel: " + plants.fuel_class.fillna("n/a") + "<br>"
        + "tech: " + _txt(plants.technologies, 40) + "<br>"
        + "parent: " + _txt(plants.parent)
        + "<extra>POWER PLANT</extra>"
    )

    # pipelines -----------------------------------------------------------
    meta = meta[meta.status_group == "active"].copy()

    cap = np.where(meta.capacity.notna(),
                   meta.capacity.round(2).astype(str) + " " + meta.capacity_unit,
                   "n/a")
    seg = np.where(meta.segment.notna(), _txt(meta.segment) + "<br>", "")
    meta["hover"] = (
        "<b>" + _txt(meta.name) + "</b><br>" + seg
        + _txt(meta.countries) + "<br>"
        + "status: " + meta.status_base + "  ·  " + meta.sub_fuel.fillna("") + "<br>"
        + "capacity: " + cap + "<br>"
        + "length: " + meta.length_km.round(0).astype("Int64").astype(str) + " km<br>"
        + "owner: " + _txt(meta.owner) + "<br>"
        + "parent: " + _txt(meta.parent)
        + "<extra>" + meta.fuel.str.upper() + " PIPELINE</extra>"
    )

    # LNG -----------------------------------------------------------------
    lng = lng[lng.status_group == "active"].copy()
    lng["facility_type"] = lng.facility_type.where(lng.facility_type.isin(["import", "export"]))
    lng["size"] = (6 + 3 * np.sqrt(lng.capacity_mtpa.fillna(0))).clip(6, 20)
    lcap = np.where(lng.capacity_mtpa.notna(),
                    lng.capacity_mtpa.round(2).astype(str) + " Mtpa", "n/a")
    unit = np.where(lng.unit_name.notna(), " — " + _txt(lng.unit_name, 30), "")
    supplies = np.where(lng.power_plants_supplied.notna(),
                        "<br>supplies: " + _txt(lng.power_plants_supplied), "")
    lng["hover"] = (
        "<b>" + _txt(lng.name) + "</b>" + unit + "<br>"
        + lng.country.fillna("") + "<br>"
        + lng.facility_type.fillna("type n/a") + "  ·  " + lng.status_base + "<br>"
        + "capacity: " + lcap + np.where(lng.floating, "  (floating)", "") + "<br>"
        + "parent: " + _txt(lng.parent) + supplies
        + "<extra>LNG TERMINAL</extra>"
    )

    return plants, lines, meta, lng


# ---------------------------------------------------------------- trace index
# Fixed positions let Patch address traces by index. Order is also draw order:
# pipelines at the bottom, LNG on top so terminals are never hidden by plants.

IDX = {}
_i = 0
for _f in PIPE_FUELS:
    for _s in STATUS_ORDER:
        IDX[("line", _f, _s)] = _i; _i += 1
for _f in PIPE_FUELS:
    for _s in STATUS_ORDER:
        IDX[("mid", _f, _s)] = _i; _i += 1
for _s in STATUS_ORDER:
    IDX[("plant", _s)] = _i; _i += 1
for _s in STATUS_ORDER:
    IDX[("lng", _s)] = _i; _i += 1


def _visible(layer, status, statuses, layers):
    return layer in layers and status in statuses


# ---------------------------------------------------------------- trace builders

def plant_trace(plants, status, fuels, min_mw, tone, visible):
    s = plants[(plants.status_base == status) & plants.fuel_key.isin(fuels)
               & (plants.capacity_mw >= min_mw)]
    return go.Scattermap(
        lat=s.lat, lon=s.lon, mode="markers", name=f"plants {status}",
        marker=dict(size=s["size"], color=s.fuel_key.map(PLANT[tone]),
                    opacity=PLANT_OPACITY[status]),
        hovertemplate=s.hover, showlegend=False, visible=visible,
    )


def line_trace(lines, fuel, status, tone, visible):
    b = lines[fuel][status]
    return go.Scattermap(
        lat=b["lat"], lon=b["lon"], mode="lines",
        line=dict(width=PIPE_WIDTH[status],
                  color=rgba(PIPE_RGB[tone][fuel], PIPE_ALPHA[tone][status])),
        hoverinfo="skip", showlegend=False, visible=visible,
    )


def mid_trace(meta, fuel, status, tone, visible):
    # hover lives here: Scattermap only fires hover on vertices, and repeating
    # the tooltip on every line vertex would multiply the payload
    s = meta[(meta.fuel == fuel) & (meta.status_base == status)]
    return go.Scattermap(
        lat=s.mid_lat, lon=s.mid_lon, mode="markers",
        marker=dict(size=4, color=rgba(PIPE_RGB[tone][fuel], 0.9)),
        hovertemplate=s.hover, showlegend=False, visible=visible,
    )


def lng_trace(lng, status, tone, visible):
    s = lng[lng.status_base == status]
    colours = [LNG[tone].get(t if isinstance(t, str) else None) for t in s.facility_type]
    return go.Scattermap(
        lat=s.lat, lon=s.lon, mode="markers",
        marker=dict(size=s["size"], color=colours,
                    opacity=PLANT_OPACITY[status]),
        hovertemplate=s.hover, showlegend=False, visible=visible,
    )


def initial_figure(statuses, pipe_statuses, fuels, min_mw, basemap, layers):
    plants, lines, meta, lng = load_all()
    style, tone = BASEMAPS[basemap]
    traces = [None] * len(IDX)
    for f in PIPE_FUELS:
        for s in STATUS_ORDER:
            vis = _visible(f, s, pipe_statuses, layers)
            traces[IDX[("line", f, s)]] = line_trace(lines, f, s, tone, vis)
            traces[IDX[("mid", f, s)]] = mid_trace(meta, f, s, tone, vis)
    for s in STATUS_ORDER:
        traces[IDX[("plant", s)]] = plant_trace(
            plants, s, fuels, min_mw, tone, _visible("plants", s, statuses, layers))
        traces[IDX[("lng", s)]] = lng_trace(
            lng, s, tone, _visible("lng", s, statuses, layers))

    fig = go.Figure(traces)
    fig.update_layout(
        map=dict(style=style, center=dict(lat=25, lon=15), zoom=1.15),
        margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor=BG,
        font=dict(family=FONT, color=TEXT, size=12),
        hoverlabel=dict(bgcolor=PANEL, bordercolor=AMBER,
                        font=dict(family=FONT, color=TEXT, size=11)),
        uirevision="keep",
    )
    return fig


# ---------------------------------------------------------------- readout

def readout(statuses, pipe_statuses, fuels, min_mw, layers):
    plants, _, meta, lng = load_all()
    rows = []

    if "plants" in layers:
        p = plants[plants.status_base.isin(statuses) & plants.fuel_key.isin(fuels)
                   & (plants.capacity_mw >= min_mw)]
        rows += [("PLANTS", f"{len(p):,} sites · {p.n_units.sum():,} units"),
                 ("", f"{p.capacity_mw.sum()/1000:,.1f} GW · {p.country.nunique()} countries")]

    for f, label in [("gas", "GAS PIPE"), ("oil", "OIL/NGL PIPE")]:
        if f in layers:
            m = meta[(meta.fuel == f) & meta.status_base.isin(pipe_statuses)]
            # umbrella rows overlap their own segments: count them out of km
            km = m.loc[~m.is_system_record, "length_km"].sum()
            rows.append((label, f"{len(m):,} segments · {km:,.0f} km"))

    if "lng" in layers:
        g = lng[lng.status_base.isin(statuses)]
        imp = g.loc[g.facility_type == "import", "capacity_mtpa"].sum()
        exp = g.loc[g.facility_type == "export", "capacity_mtpa"].sum()
        rows.append(("LNG", f"{len(g):,} units · imp {imp:,.0f} / exp {exp:,.0f} Mtpa"))

    return [html.Div([html.Span(k, style={"color": AMBER, "display": "inline-block",
                                          "width": "78px", "fontSize": "9.5px",
                                          "letterSpacing": "0.06em"}),
                      html.Span(v, className="pm-num")])
            for k, v in rows]


# ---------------------------------------------------------------- layout

LABEL_STYLE = {"display": "block", "marginBottom": "5px", "color": TEXT,
               "fontSize": "12px", "cursor": "pointer"}
INPUT_STYLE = {"marginRight": "7px", "accentColor": AMBER}

DEFAULTS = dict(statuses=["operating"], pipe_statuses = ["operating"], min_mw=0, basemap="dark",
                layers=["plants", "gas", "oil", "lng"])


def _control(label, child):
    return html.Div([
        html.Div(label, style={"color": AMBER, "fontSize": "10px", "fontWeight": 600,
                               "letterSpacing": "0.09em", "marginBottom": "6px"}),
        child,
    ], style={"marginBottom": "18px"})


def _swatch(colour, text, line=False):
    shape = ({"width": "14px", "height": "2px", "marginTop": "6px"} if line
             else {"width": "8px", "height": "8px", "borderRadius": "50%", "marginTop": "3px"})
    return html.Div([
        html.Div(style={**shape, "backgroundColor": colour, "flex": "0 0 auto",
                        "marginRight": "8px"}),
        html.Span(text),
    ], style={"display": "flex", "fontSize": "11px", "color": TEXT, "marginBottom": "3px"})


def layout():
    plants, *_ = load_all()
    fuels = sorted(plants.fuel_key.unique())
    d = DEFAULTS

    key = html.Div(
        [_swatch(c, f) for f, c in PLANT["dark"].items()]
        + [_swatch(rgba(PIPE_RGB["dark"]["gas"], 1), "gas pipeline", line=True),
           _swatch(rgba(PIPE_RGB["dark"]["oil"], 1), "oil / NGL pipeline", line=True),
           _swatch(LNG["dark"]["import"], "LNG import"),
           _swatch(LNG["dark"]["export"], "LNG export")])

    controls = html.Div([
        html.Div("OIL & GAS INFRASTRUCTURE", style={
            "color": AMBER, "fontSize": "13px", "fontWeight": 600,
            "letterSpacing": "0.11em", "marginBottom": "2px"}),
        html.Div("GEM · GOGPT Aug 26 · GGIT · GOIT Jul 26", style={
            "color": MUTED, "fontSize": "10px", "marginBottom": "22px"}),

        _control("STATUS  (PLANTS & LNG)", dcc.Checklist(
            id="pm-status", value=d["statuses"],
            options=[{"label": s, "value": s} for s in STATUS_ORDER],
            labelStyle=LABEL_STYLE, inputStyle=INPUT_STYLE)),

        _control("LAYERS", dcc.Checklist(
            id="pm-layers", value=d["layers"],
            options=[{"label": "power plants", "value": "plants"},
                     {"label": "gas pipelines", "value": "gas"},
                     {"label": "oil & NGL pipelines", "value": "oil"},
                     {"label": "LNG terminals", "value": "lng"}],
            labelStyle=LABEL_STYLE, inputStyle=INPUT_STYLE)),

        _control("PIPELINE_STATUS", dcc.Checklist(
            id = "pm-pipe-status", value=d["pipe_statuses"],
            options = [{"label": s, "value": s} for s in STATUS_ORDER],
            labelStyle=LABEL_STYLE, inputStyle = INPUT_STYLE
        )),

        _control("PLANT FUEL CLASS", dcc.Checklist(
            id="pm-fuel", value=fuels,
            options=[{"label": f, "value": f} for f in fuels],
            labelStyle=LABEL_STYLE, inputStyle=INPUT_STYLE)),

        _control("MIN PLANT CAPACITY (MW)", dcc.Slider(
            id="pm-minmw", min=0, max=11000, value=d["min_mw"], step=None,
            marks={m: {"label": lab, "style": {"color": MUTED, "fontSize": "9px"}}
                   for m, lab in [(0, "0"), (100, ""), (250, ""), (500, "500"),
                                  (1000, "1k"), (2000, "2k"), (4000, "4k"),
                                  (6000, ""), (11000, "max")]})),

        _control("BASEMAP", dcc.RadioItems(
            id="pm-basemap", value=d["basemap"],
            options=[{"label": "dark", "value": "dark"},
                     {"label": "street detail", "value": "detail"},
                     {"label": "satellite", "value": "sat"}],
            labelStyle=LABEL_STYLE, inputStyle=INPUT_STYLE)),

        html.Div(id="pm-readout",
                 children=readout(d["statuses"], d["pipe_statuses"], fuels, d["min_mw"], d["layers"]),
                 style={"fontSize": "11px", "color": TEXT, "lineHeight": "1.75",
                        "borderTop": f"1px solid {GRID}", "paddingTop": "14px",
                        "marginBottom": "18px"}),

        _control("KEY", key),
    ], style={"width": "250px", "flex": "0 0 250px", "padding": "20px",
              "backgroundColor": PANEL, "borderRight": f"1px solid {GRID}",
              "overflowY": "auto"})

    fig = initial_figure(d["statuses"], d["pipe_statuses"], fuels, d["min_mw"], d["basemap"], d["layers"])

    return html.Div([
        controls,
        html.Div(dcc.Graph(id="pm-map", figure=fig, style={"height": "100%"},
                           config={"displayModeBar": False, "scrollZoom": True}),
                 style={"flex": "1 1 auto", "minWidth": 0}),
    ], style={"display": "flex", "height": "calc(100vh - 120px)",
              "backgroundColor": BG, "fontFamily": FONT})


# ---------------------------------------------------------------- callbacks

def build_patch(trigger, statuses, pipe_statuses, fuels, min_mw, basemap, layers):
    """Only what changed goes over the wire. Separated from the callback so it
    can be tested without a running server."""
    plants, lines, meta, lng = load_all()
    style, tone = BASEMAPS.get(basemap, BASEMAPS["dark"])
    p = Patch()

    # visibility is cheap: always refresh every flag
    for f in PIPE_FUELS:
        for s in STATUS_ORDER:
            vis = _visible(f, s, pipe_statuses, layers)
            p["data"][IDX[("line", f, s)]]["visible"] = vis
            p["data"][IDX[("mid", f, s)]]["visible"] = vis
    for s in STATUS_ORDER:
        p["data"][IDX[("lng", s)]]["visible"] = _visible("lng", s, statuses, layers)

    # plant markers: resend the points only when the point set changes
    if trigger in ("pm-fuel", "pm-minmw"):
        for s in STATUS_ORDER:
            p["data"][IDX[("plant", s)]] = plant_trace(
                plants, s, fuels, min_mw, tone, _visible("plants", s, statuses, layers))
    else:
        for s in STATUS_ORDER:
            p["data"][IDX[("plant", s)]]["visible"] = _visible("plants", s, statuses, layers)
            if trigger == "pm-basemap":
                # same filter as plant_trace, so colours line up point-for-point
                sub = plants[(plants.status_base == s) & plants.fuel_key.isin(fuels)
                             & (plants.capacity_mw >= min_mw)]
                p["data"][IDX[("plant", s)]]["marker"]["color"] = (
                    sub.fuel_key.map(PLANT[tone]).tolist())

    # basemap: swap style and recolour - colours only, never geometry
    if trigger == "pm-basemap":
        p["layout"]["map"]["style"] = style
        for f in PIPE_FUELS:
            for s in STATUS_ORDER:
                p["data"][IDX[("line", f, s)]]["line"]["color"] = rgba(
                    PIPE_RGB[tone][f], PIPE_ALPHA[tone][s])
                p["data"][IDX[("mid", f, s)]]["marker"]["color"] = rgba(PIPE_RGB[tone][f], 0.9)
        for s in STATUS_ORDER:
            t = lng[lng.status_base == s].facility_type
            p["data"][IDX[("lng", s)]]["marker"]["color"] = [
                LNG[tone].get(x if isinstance(x, str) else None) for x in t]
    return p


@callback(
    Output("pm-map", "figure"),
    Output("pm-readout", "children"),
    Input("pm-status", "value"),
    Input("pm-fuel", "value"),
    Input("pm-minmw", "value"),
    Input("pm-basemap", "value"),
    Input("pm-layers", "value"),
    Input("pm-pipe-status", "value"),
    prevent_initial_call=True,       # layout() already drew the first frame
)
def update(statuses, fuels, min_mw, basemap, layers, pipe_statuses):
    statuses, fuels, layers = statuses or [], fuels or [], layers or []
    pipe_statuses = pipe_statuses or []
    min_mw = min_mw or 0
    patch = build_patch(ctx.triggered_id, statuses, pipe_statuses, fuels, min_mw, basemap, layers)
    return patch, readout(statuses, pipe_statuses, fuels, min_mw, layers)