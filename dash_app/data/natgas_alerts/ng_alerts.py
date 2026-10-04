from dash import html, dcc, Input, Output, callback, ctx
import dash_bootstrap_components as dbc
from dash import dash_table

from dash_app.data.natgas_alerts.alert_funcs import fetch_noaa_alerts, create_alert_map

# --- Layout ---
layout = html.Div([
    html.H4("🌪️ NOAA Weather Alerts", className="text-center mb-3"),

    html.Div([
        dbc.Row([
            dbc.Col([
                html.Label("Alert Type"),
                dcc.Dropdown(
                    id="alert-type",
                    options=[{"label": t, "value": t} for t in [
                        "Winter Storm Warning", "Hurricane Warning", "Extreme Heat Warning",
                        "Freeze Warning", "Frost Advisory"
                    ]],
                    value="Winter Storm Warning",
                    clearable=False
                ),
            ], md=6),

            dbc.Col([
                html.Label("Region (NOAA Area Code)"),
                dcc.Dropdown(
                    id="alert-region",
                    options=[{"label": r, "value": r} for r in
                             ["All", "NY", "TX", "LA", "FL", "CA", "OK", "PA", "MA", "GA"]],
                    value="All",
                    clearable=False
                ),
            ], md=6),
        ], className="mb-3"),
    ], className="card-surface alert-filters-panel"),

    dbc.Spinner(html.Div(id="alert-status", className="mb-2")),
    html.Div(
        dbc.Button("🔄 Refresh alerts", id="alert-refresh-btn",
                   n_clicks=0, color="secondary", size="sm"),
        className="d-flex justify-content-end mb-2",
    ),
    html.Div(
        html.Iframe(id="alert-map", style={"width": "100%", "height": "500px", "border": "none"}),
        className="card-surface alert-map-panel",
    ),
    html.Div(id="alert-table", className="card-surface mt-3"),
])

# --- Callback ---
@callback(
    [Output("alert-status", "children"),
     Output("alert-map", "srcDoc"),
     Output("alert-table", "children")],
    [Input("alert-type", "value"),
     Input("alert-region", "value"),
     Input("alert-refresh-btn", "n_clicks")]
)

def update_alerts(event_type, region, n_intervals):
    event_name = None if event_type == "All" else event_type
    area = None if region == "All" else region
    force = ctx.triggered_id == "alert-refresh-btn"

    try:
        alerts_df = fetch_noaa_alerts(event_name=event_name, area=area, force_refresh=force)
    except Exception as e:
        return f"❌ Error fetching data: {e}", None, None

    if alerts_df.empty:
        return "ℹ️ No active alerts found for the selected filters.", None, None

    # Create folium map
    alert_map = create_alert_map(alerts_df)
    map_html = alert_map._repr_html_()

    # Only keep scalar columns for display
    display_cols = ["event", "severity", "certainty", "urgency", "effective", "expires"]
    table = dash_table.DataTable(
        columns=[{"name": i.capitalize(), "id": i} for i in display_cols],
        data=alerts_df[display_cols].to_dict("records"),
        style_cell = {'textAlign': 'left'},
        style_cell_conditional = [{'if': {'column_id': 'event'}, 'textAlign': 'left'}]
    )

    return f"✅ Found {len(alerts_df)} active alerts.", map_html, table