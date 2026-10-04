from dash import html, dcc, register_page, Input, Output, callback
from dash.exceptions import PreventUpdate
from dash_app.data.store import load_ng_data
from dash_app.data.natgas_EIA import ng_supply_detail, ng_demand_detail, ng_storage
from dash_app.data.natgas_alerts import ng_alerts
import plotly.express as px
import plotly.io as pio
import pandas as pd

PAGE_META = {
    "author": "Titus Lim Jing En",
    "last_reviewed": "2026-10-04",
    "remarks": [
        "Edited connection to cloudflare R2 object storage",
        "production, consumption dataframes contain state-level data with regions marked.",
        "Growth-rate NAN interpolation for NG consumption assumes linear growth rates, and sacrifices recency for seasonal data behaviour (annual).",
        "Common code issues surface due to wrong state abbreviations, confusion when filtering state-region into region only data, or forgetting to filter out aggregate US data (region==Unknown)"
    ]
}

# Register this page
register_page(
    __name__,
    path="/natty_window",
    name="Natural Gas",
    title="Natural Gas Monitoring"
)

# Page layout
layout = html.Div([
        html.H2("Natural Gas Section", style={"textAlign": "center"}),
        html.P("Monitoring inventories, flows, and spreads.", style={"textAlign": "center"}),
        
        dcc.Tabs(id="natty-tabs", value="inventories", children=[
            dcc.Tab(label="Historical S&D Overview", value="fundamentals"),
            dcc.Tab(label="Production Breakdown", value='supply_detail'),
            dcc.Tab(label="Demand Breakdown", value="demand_detail"),
            dcc.Tab(label="Storages", value="storage"),
            dcc.Tab(label="Weather Alerts", value="live-alerts")
        ]),
        
        html.Div(id="natty-content")
    ])

# Graph Templates
pio.templates.default = "plotly_white"

@callback(
    Output("natty-content", "children"),
    Input("natty-tabs", "value"),
    prevent_initial_call = False
)

def update_tab(tab_value):
    if tab_value == "fundamentals":
        _, _, production, consumption, _, _, prod_share, demand_share = load_ng_data()
        
        ### REGIONAL PRODUCTION STACK VISUAL
        region_trends = production.sort_values(by=['Region','period'], ascending=True).copy()

        region_trends['roll12'] = (region_trends.groupby('Region')['value_PROD'].transform(lambda s: s.rolling(12, min_periods=6).mean()))
        region_weights = (region_trends[region_trends['period'] >=(region_trends['period'].max() - pd.DateOffset(months=5))].groupby('Region')['roll12'].mean().sort_values(ascending=False))
        
        pivot_stack = (region_trends.pivot_table(index="period", columns="Region", values="value_PROD", aggfunc="sum").sort_index())
        pivot_stack = pivot_stack[region_weights.index]
        total_prod = pivot_stack.sum(axis=1)

        fig_prod_stack = px.area(
            pivot_stack,
            title="US NG Production by Region",
            labels={"value": "Natural Gas Production (MMCF)", "period": "Date"}
        )

        fig_prod_stack.add_scatter(
            x=total_prod.index,
            y=total_prod.values,
            mode="lines",
            name="Total Production",
            line=dict(width=3, color="black")
        )
        
        fig_prod_stack.update_layout(
            annotations = [
                dict(
                    text = "Data Source: Marketed Production (EIA). Production Regions ranked with most recent 6 month values of the 12-M rolling average.",
                    xref = 'paper',
                    yref = 'paper',
                    x = 0,
                    y = -0.30,
                    showarrow=False,
                    align="left",
                    font = dict(size= 10, color="black")
                )
            ], margin = dict(b=90)
        ),
        
        ### REGIONAL CONSUMPTION STACK VISUAL
        region_trends_dmd = consumption.sort_values(by=['Region','period'], ascending=True).copy()

        region_trends_dmd['roll12'] = (region_trends_dmd.groupby('Region')['value_DEMAND'].transform(lambda s: s.rolling(12, min_periods=6).mean()))
        region_weights_dmd = (region_trends_dmd[region_trends_dmd['period'] >=(region_trends_dmd['period'].max() - pd.DateOffset(months=5))].groupby('Region')['roll12'].mean().sort_values(ascending=False))
        
        demand_pivot_stack = (region_trends_dmd.pivot_table(index="period", columns="Region", values="value_DEMAND", aggfunc="sum").sort_index())
        demand_pivot_stack = demand_pivot_stack[region_weights_dmd.index]
        total_demand = demand_pivot_stack.sum(axis=1)

        fig_demand_stack = px.area(
            demand_pivot_stack,
            title="US NG Consumption by Region",
            labels={"value": "Total NG Delivered to Consumers", "period": "Date"}
        )

        fig_demand_stack.add_scatter(
            x=total_demand.index,
            y=total_demand.values,
            mode="lines",
            name="Total Consumption",
            line=dict(width=3, color="black")
        )
        
        fig_demand_stack.update_layout(
            annotations = [
                dict(
                    text = "Data Source: Volumes Delivered to Consumers (EIA). Consumption Regions ranked with most recent 6 month values of the 12-M rolling average.",
                    xref = 'paper',
                    yref = 'paper',
                    x = 0,
                    y = -0.30,
                    showarrow=False,
                    align="left",
                    font = dict(size= 10, color="black")
                )
            ], margin = dict(b=90)
        )
        
        ### CHOROPLETH MAP LATEST PRODUCTION BY STATE
        latest_production_state = (
        production[production["period"] == production["period"].max()]
        .groupby("State", as_index=False)["value_PROD"]
        .sum()
        )

        # Remove all states with 0 production so only producing states are visualized.
        latest_production_state = latest_production_state[latest_production_state['value_PROD'] != 0]

        # If animation needed, animation_frame='period', replace dataframe with a time-period variable
        fig_prod_state_choropleth = px.choropleth(
            latest_production_state,
            locations="State",
            locationmode="USA-states",
            color="value_PROD",
            scope="usa",
            color_continuous_scale="Viridis",
            title="Latest Monthly NG Production by State"
        )
        fig_prod_state_choropleth.update_layout(
            annotations = [
                dict(
                    text="Data Source: Marketed Production (EIA). Region segmentations are aligned with EIA storage definitions:  <a href='https://ir.eia.gov/ngs/notes.html''target=_blank''title=Go to EIA site'>EIA_region_convention</a>",
                    xref = 'paper',
                    yref = 'paper',
                    x = 0,
                    y = -0.15,
                    showarrow=False,
                    align="left",
                    font = dict(size= 12, color="black"), 
                    captureevents=True
                )
            ],
            autosize=True, 
            margin=dict(l=0,r=0,t=40,b=80))

        ### CHOROPLETH MAP LATEST CONSUMPTION BY STATE
        latest_consumption_state = (
        consumption[consumption["period"] == consumption["period"].max()]
        .groupby("State", as_index=False)["value_DEMAND"]
        .sum()
        )

        # Remove all states with 0 production so only producing states are visualized.
        latest_consumption_state = latest_consumption_state[latest_consumption_state['value_DEMAND'] != 0]

        # If animation needed, animation_frame='period', replace dataframe with a time-period variable
        fig_demand_state_choropleth = px.choropleth(
            latest_consumption_state,
            locations="State",
            locationmode="USA-states",
            color="value_DEMAND",
            scope="usa",
            color_continuous_scale="Plasma",
            title="Latest Monthly NG Consumption by State"
        )
        fig_demand_state_choropleth.update_layout(
            annotations = [
                dict(
                    text="Data Source: Volumes Delivered to Consumers (EIA). Region segmentations are aligned with EIA storage definitions:  <a href='https://ir.eia.gov/ngs/notes.html''target=_blank''title=Go to EIA site'>EIA_region_convention</a>",
                    xref = 'paper',
                    yref = 'paper',
                    x = 0,
                    y = -0.15,
                    showarrow=False,
                    align="left",
                    font = dict(size= 12, color="black")
                )
            ],
            autosize=True, 
            margin=dict(l=0,r=0,t=40,b=80))
        
        return html.Div([
            html.Div([
                html.H4("Regional Reliance Snapshot"),
                html.Div([
                    html.Div([
                        html.P("Production Share", style={'fontWeight': '600', 'fontSize': '14px', 'marginBottom': '10px', 'color': '#111827'}),
                        html.Ul([html.Li(f"{r}: {v:.1f}%") for r,v in 
                                zip(prod_share['Region'], prod_share['prod_pctshare'])],
                                style= {'listStyleType': 'none', 'paddingLeft': '0', 'margin': '0', 'fontSize': '13px', 'lineHeight': '1.6', 'color': '#374151'})
                    ], className="card-surface"),

                    html.Div([
                        html.P("Consumption Share", style={'fontWeight': '600', 'fontSize': '14px', 'marginBottom': '10px', 'color': '#111827'}),
                        html.Ul([html.Li(f"{r}: {v:.1f}%") for r,v in 
                                zip(demand_share['Region'], demand_share['demand_pctshare'])],
                                style= {'listStyleType': 'none', 'paddingLeft': '0', 'margin': '0', 'fontSize': '13px', 'lineHeight': '1.6', 'color': '#374151'})
                    ], className="card-surface"),
                ], style={"display":"grid","gap":"32px", "gridTemplateColumns": "repeat(2, minmax(260px, 1fr))", "maxwidth": "700px", "margin": "0 auto"}
                        ),
                    ], className="card-surface"),
            html.Hr(),

            html.Div([
                dcc.Graph(figure=fig_prod_state_choropleth, style={"aspectRatio": "1.6", "minHeight": "420px"}),
                dcc.Graph(figure=fig_demand_state_choropleth, style={"aspectRatio": "1.6", "minHeight": "420px"})
            ], className="card-surface", style={'display': 'grid', "gridTemplateColumns": "1fr 1fr", 'gap': '24px'}),

            html.Div([
                dcc.Graph(figure=fig_prod_stack),
                dcc.Graph(figure=fig_demand_stack)
            ], className="card-surface", style={'display': 'grid', "gridTemplateColumns": "1fr 1fr", 'gap': '24px'}),
            
            html.Hr(),
            html.Div([
                dcc.Dropdown(
                    id={'type': 'region-dropdown', 'index': 'fundamentals'},
                    options=[{'label':r, 'value':r} for r in production['Region'].unique()],
                    value=consumption['Region'].unique()[0]
                ),
            ], className="card-surface"),
            html.Hr(),
            # === Row 1 ===
            html.Div([
                dcc.Graph(id={"type": "prod-line", "index": "fundamentals"}),
                dcc.Graph(id={"type": "demand-line", "index": "fundamentals"}),
            ], className="card-surface", style={'display': 'grid', "gridTemplateColumns": "1fr 1fr", 'gap': '24px'}),

            # === Row 2 ===
            html.Div([
                dcc.Graph(id={"type": "imp-line", "index": "fundamentals"}),
                dcc.Graph(id={"type": "exp-line", "index": "fundamentals"}),
            ], className="card-surface", style={'display': 'grid', "gridTemplateColumns": "1fr 1fr", 'gap': '24px'}),
            
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
                        "2. Consumption NaN values are interpolated using seasonal growth rates.", html.Br(),
                        "3. Consumption excludes pipeline and distribution use, & lease and plant fuel consumption", html.Br(),
                        "4. Regional reliance snapshots use latest reported EIA data.", html.Br(),
                        "5. Region definitions follow EIA storage segmentation.", html.Br(), html.Br(),
                        "All data exclude forecasts. Accurate up to latest EIA release.", html.Br(),
                        "Credits: Titus Lim Jing En"
                    ])
                ], className="card-surface", style={"fontSize": "11px", "color": "#6b7280", "lineHeight": "1.6"}
                )
        ])
    elif tab_value == 'supply_detail':
        return ng_supply_detail.layout
    elif tab_value == 'demand_detail':
        return ng_demand_detail.layout
    elif tab_value == 'storage':
        return ng_storage.layout
    elif tab_value == 'live-alerts':
        return ng_alerts.layout
    else:
        raise PreventUpdate

@callback(
    [Output({"type": "prod-line", "index": "fundamentals"}, "figure"),
     Output({"type": "demand-line", "index": "fundamentals"}, "figure"),
     Output({"type": "imp-line", "index": "fundamentals"}, "figure"),
     Output({"type": "exp-line", "index": "fundamentals"}, "figure")],
    Input({'type': 'region-dropdown', 'index': 'fundamentals'},'value'),
)

def update_prod(region):
    if not region:
        raise PreventUpdate
    _, _, US_prod, US_demand, US_imports, US_exports, _, _ = load_ng_data()
    
    US_imports = US_imports.sort_values(by=['period', 'Region'], ascending=True)
    US_exports = US_exports.sort_values(by=['period', 'Region'], ascending=True)
    
    # Multiple states present in prod and consumption, group by
    prod_df = US_prod.groupby(['period', 'Region']).agg({'value_PROD': 'sum', 'process-name': 'first'}).reset_index()
    demand_df = US_demand.groupby(['period', 'Region']).agg({'value_DEMAND': 'sum', 'process-name': 'first'}).reset_index()
    prod_df = prod_df.sort_values(by=['period', 'Region'], ascending=True)
    demand_df = demand_df.sort_values(by=['period', 'Region'], ascending=True)
    
    prod_df = prod_df[prod_df['Region'] == region]
    demand_df = demand_df[demand_df['Region'] == region]
    import_df = US_imports[US_imports['Region'] == region]
    export_df = US_exports[US_exports['Region'] == region]

    prod_fig = px.line(prod_df, x='period', y='value_PROD',
                  title=f"Natural Gas Production - {region}",
                  labels={'value_PROD':'Bcf','period':'Date'})
    prod_fig.update_layout(
        annotations=[
            dict(text="Data Source: Marketed Production (EIA).", xref = 'paper', yref = 'paper', x = 0, y = -0.30, showarrow=False, align="left", font = dict(size= 12, color="black"))
                ], margin=dict(l=70, r=30, t=60, b=90), hovermode="x unified"
    )
    prod_fig.update_xaxes(ticklabelmode="period",ticks="outside",ticklen=6,showgrid=False,rangebreaks=None, automargin=True)
    prod_fig.update_yaxes(ticks="outside",ticklen=6,gridcolor="rgba(0,0,0,0.08)",zeroline=False,automargin=True)
    
    demand_fig = px.line(demand_df, x='period', y='value_DEMAND',
                  title=f"Natural Gas Consumption - {region}",
                  labels={'value_DEMAND':'Bcf','period':'Date'})
    demand_fig.update_layout(
        annotations=[
            dict(text="Data Source: Volumes Delivered to Consumers (EIA).", xref = 'paper', yref = 'paper',x = 0,y = -0.30,showarrow=False,align="left",font = dict(size= 12, color="black"))
            ], margin=dict(l=70, r=30, t=60, b=90), hovermode="x unified"
    )
    demand_fig.update_xaxes(ticklabelmode="period",ticks="outside",ticklen=6,showgrid=False,rangebreaks=None, automargin=True)
    demand_fig.update_yaxes(ticks="outside",ticklen=6,gridcolor="rgba(0,0,0,0.08)",zeroline=False,automargin=True)
    
    imp_fig = px.line(import_df, x='period', y='value_IMPORTS',
                  title=f"Natural Gas Imports - {region}",
                  labels={'value_IMPORTS':'Bcf','period':'Date'})
    imp_fig.update_layout(
        annotations=[
            dict(text="Data Source: Imports by point of entry (EIA). Data is aggregated from the importer's perspective.",xref = 'paper',yref = 'paper',x = 0,y = -0.30,  
                showarrow=False,
                align="left",
                font = dict(size= 12, color="black")
            )
        ], margin=dict(l=70, r=30, t=60, b=90), hovermode="x unified"
    )
    imp_fig.update_xaxes(ticklabelmode="period",ticks="outside",ticklen=6,showgrid=False,rangebreaks=None, automargin=True)
    imp_fig.update_yaxes(ticks="outside",ticklen=6,gridcolor="rgba(0,0,0,0.08)",zeroline=False,automargin=True)
    
    exp_fig = px.line(export_df, x='period', y='value_EXPORTS',
                  title=f"Natural Gas Exports - {region}",
                  labels={'value_EXPORTS':'Bcf','period':'Date'})
    exp_fig.update_layout(
        annotations=[
            dict(
                text="Data Source: Exports by point of exit (EIA). Data is aggregated from the exporter's perspective.",
                xref = 'paper',
                yref = 'paper',
                x = 0,
                y = -0.30,
                showarrow=False,
                align="left",
                font = dict(size= 12, color="black")
            )
        ], margin=dict(l=70, r=30, t=60, b=90), hovermode="x unified"
    )
    exp_fig.update_xaxes(ticklabelmode="period",ticks="outside",ticklen=6,showgrid=False,rangebreaks=None, automargin=True)
    exp_fig.update_yaxes(ticks="outside",ticklen=6,gridcolor="rgba(0,0,0,0.08)",zeroline=False,automargin=True)
    
    return prod_fig, demand_fig, imp_fig, exp_fig