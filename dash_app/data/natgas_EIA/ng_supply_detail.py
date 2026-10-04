from dash import html, dcc, Input, Output, callback
import plotly.graph_objects as go
import plotly.express as px
import plotly.io as pio
import pandas as pd
from dash_app.data.store import load_ng_data

# Graph templates
pio.templates.default = "plotly_white"

# ---- Layout ----
layout = html.Div([
    html.H2("US Supply Breakdown by State", style={"textAlign": "center"}),
    html.P("Dry gas marketed production & Imports by point of entry (TBC)", style={"textAlign": "center", "marginBottom": "24px"}),
    
    # Treemap
    html.Div([
    dcc.Graph(id="prod-treemap", config={"displayModeBar": False}, style={"aspectRatio": "1.6", "minHeight": "420px"})
    ],
        className="card-surface"),
    html.Hr(),
    
    # Dropdown for individual state time trends
    html.Div(
        [
            html.Label("Select states to display:", style={"fontWeight": "600"}),
            dcc.Dropdown(id="state-selector", options=[],
            value = [], multi=True, placeholder="Select states...")
        ],
        className="card-surface", style={"maxWidth": "600px", "margin": "0 auto"}
    ),
    
    # State Trends
    html.Div(
        id="state-trends-plots",
        className="card-surface",
        style={'display': 'grid', "gridTemplateColumns": "repeat(2, 1fr)", 'gap': '24px'}),
    html.Hr(),
    
    # == Row 3 (Additional footnotes) ==
    html.Div([   
            html.P([
                "Additional Definitions and Notes attached here: ",
                html.A(
                    "EIA Definitions",
                    href="https://www.eia.gov/dnav/ng/TblDefs/ng_prod_sum_tbldef2.asp",
                    target="_blank"
                ),
                html.Br(), html.Br(),
                "1. Marketed Production data are not reported for all states.", html.Br(),
                "2. Region definitions follow EIA storage segmentation.", html.Br(),
                "3. Import Data is aggregated from importers' perspective.", html.Br(), html.Br(),
                "All data exclude forecasts. Accurate up to latest EIA release.", html.Br(),
                "Credits: Titus Lim Jing En"
            ])
        ], className="card-surface", style={"fontSize": "11px", "color": "#6b7280", "lineHeight": "1.6"}
        )
    ])

@callback(
    [Output("prod-treemap", "figure"),
     Output("state-trends-plots", "children"), # list of line plots
     Output("state-selector", "options"),
     Output("state-selector", "value")],
    [Input("prod-treemap", "id"),  # dummy input, runs once
     Input("state-selector", "value")] # dropdown initial input value
)

def update_all(_, selected_states):
    _, _, production_break, *_ = load_ng_data() 
    
    latest = production_break["period"].max()

    latest_treemap = (
        production_break[production_break["period"] == latest]
        .groupby(["Region", "State", "State Name"], as_index=False)["value_PROD"]
        .sum()
    )

    cutoff = 0.01 * latest_treemap["value_PROD"].sum()
    latest_treemap.loc[
        latest_treemap["value_PROD"] < cutoff, "State Name"
    ] = "Others"

    treemap_fig = px.treemap(
        latest_treemap,
        path=["Region", "State Name"],
        values="value_PROD",
        color="State Name",
    )

    treemap_fig.update_traces(
        root_color="lightgray",
        texttemplate="%{label}<br>%{value:.1f}",
        textfont_size=14,
        insidetextfont=dict(color="white"),
        hovertemplate=(
            "<b>%{label}</b><br>"
            "Production: %{value:,.0f} BCF<br>"
            "Region: %{parent}<extra></extra>"
        ),
        tiling=dict(pad=3, packing="squarify"),
        marker=dict(line=dict(width=1, color="white")),
    )

    treemap_fig.update_layout(
        autosize=True,
        title=(
            "<b>US Natural Gas Production Overview</b>"
            f"<br><sup>Total: {latest_treemap['value_PROD'].sum():,.0f} BCF</sup>"
        ),
        margin = dict(t=60, l=10, r=10, b=10)
    )
    
    # Dropdown options
    df = production_break.copy().sort_values(["State", "period"])
    df["roll12"] = (df.groupby("State")["value_PROD"].transform(lambda s: s.rolling(12, min_periods=6).mean()))
    
    top_states = list(df[df['period'] >= (df['period'].max() - pd.DateOffset(months=5))].groupby('State')['roll12'].mean().sort_values(ascending=False).head(10).index.values)
    
    options = [{"label": s, "value": s} for s in top_states]
    
    if not selected_states:
        selected_states = top_states

    if selected_states:
        df = df[df["State"].isin(selected_states)]

    state_graphs = []
    
    for state in selected_states:
        temp_plot_df = df[df['State'] == state]
        state_fig = go.Figure()
        
        state_fig.add_trace(go.Scatter(x=temp_plot_df['period'], y=temp_plot_df['value_PROD'], mode="lines+markers", name="Actual Marketed Production"))
        state_fig.add_trace(go.Scatter(x=temp_plot_df['period'], y=temp_plot_df['roll12'], mode="lines", name="12-M rolling average"))
        
        state_fig.update_layout(
            title=f"Natural Gas Production -- {temp_plot_df['State Name'].unique()[0].capitalize()}, {temp_plot_df['Region'].unique()[0]}",
            margin=dict(l=40, r=20, t=50, b=30),
            annotations=[
            dict(text="Data Source: Marketed Production (EIA). Region Definitions: <a href='https://ir.eia.gov/ngs/notes.html''target=_blank''title=Go to EIA site'>EIA_region_convention</a>", xref = 'paper', yref = 'paper', x = 0, y = -0.15, showarrow=False, align="left", font = dict(size= 12, color="black"))
                ],
            hovermode="x unified"
        )
        state_graphs.append(dcc.Graph(figure=state_fig))
    
    return treemap_fig, state_graphs, options, selected_states