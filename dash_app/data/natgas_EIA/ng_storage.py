from dash import html, dcc, Input, Output, callback, dash_table
from dash.dash_table.Format import Format, Scheme
import plotly.express as px
import plotly.io as pio
import plotly.graph_objects as go
import pandas as pd
from datetime import timedelta
from dash_app.data.store import load_storage

# Graph templates
pio.templates.default = "plotly_white"

# ---- Layout ----
layout = html.Div([
    html.H2("US Gas Storage", style={"textAlign": "center"}),
    html.P("Weekly Working Gas in Underground Storage", style={"textAlign": "center", "marginBottom": "24px"}),
    
    html.Div(
        [   # Data Table
            html.Div(
                id='storage-table-container', style={'paddingRight': '12px'}
            )
        ], className="card-surface", style={'display': 'flex', 'flexDirection': 'row', 'alignItems': 'stretch'}
        ),
    html.Hr(),
    
    # State Trends
    html.Div(
        [
            # Box-whisker regional distribution
            html.Div(
                dcc.Graph(id='box-whisker-regional'), style={'flex': '1.0', 'paddingRight': '12px'}
            ),
            # Stacked Regional Plot
            html.Div(
                dcc.Graph(id='wkly-storage-stack'), style={'flex': '1.0'}
            )
        ], className="card-surface", style={'display': 'flex', 'flexDirection': 'row', 'alignItems': 'stretch'}
    ),
    html.Hr(),
    
    # == Row 3 (Additional footnotes) ==
    html.Div([   
            html.P([
                "Additional Definitions and Notes attached here: ",
                html.A(
                    "EIA Definitions",
                    href="https://www.eia.gov/dnav/ng/TblDefs/ng_stor_wkly_tbldef2.asp",
                    target="_blank"
                ),
                html.Br(), html.Br(),
                "1. Working gas is the volume of total natural gas underground capacity available for withdrawal.", html.Br(),
                "2. Total gas = Working gas + Base gas", html.Br(),
                "3. Region definitions follow EIA storage segmentation.", html.Br(), html.Br(),
                "All data exclude forecasts. Accurate up to latest EIA release.", html.Br(),
                "Credits: Titus Lim Jing En"
            ])
        ], className="card-surface", style={"fontSize": "11px", "color": "#6b7280", "lineHeight": "1.6"}
        )
    ])

@callback(
    [Output('wkly-storage-stack', 'figure'),
     Output('box-whisker-regional', 'figure'),
     Output('storage-table-container', 'children')],
    Input('wkly-storage-stack', 'id') # Dummy Input
)

def storage_figs(_):
    storage_df, _ = load_storage()
    
    ### REGIONAL WEEKLY STORAGE STACK VISUAL
    storage_df = storage_df.sort_values(by=['period','Region'], ascending=True, inplace=False).reset_index(drop=True)
    
    storage_pivot_stack = (storage_df.pivot_table(index="period", columns="Region", values="value", aggfunc="sum").sort_index())
    
    total_weekly_storage = storage_pivot_stack.sum(axis=1)

    fig_wkly_stor_stack = px.area(
        storage_pivot_stack,
        title="US Weekly Working Underground Gas",
        labels={"value": "Working Gas in Storage", "period": "Date"}
    )

    fig_wkly_stor_stack.add_scatter(
        x=total_weekly_storage.index,
        y=total_weekly_storage.values,
        mode="lines",
        name="Total Working Gas Storage",
        line=dict(width=3, color="black")
    )
    fig_wkly_stor_stack.update_layout(
        annotations = [
            dict(
                text = "Data Source: Weekly Working Gas in Underground Gas (EIA). Working gas is separate from base gas.",
                xref = 'paper',
                yref = 'paper',
                x = 0,
                y = -0.30,
                showarrow=False,
                align="left",
                font = dict(size= 10, color="black")
            )
        ], margin = dict(l=70, r=30, t=60, b=100), hovermode="x unified"
    )
    fig_wkly_stor_stack.update_xaxes(
        range=[
            storage_pivot_stack.index.values.min() - pd.Timedelta(days=7),
            storage_pivot_stack.index.values.max() - pd.Timedelta(days=7)
        ],
        ticks='outside', ticklen=5
    )
    fig_wkly_stor_stack.update_yaxes(
        ticks='outside', ticklen=5
    )
    
    #### REGIONAL BOX AND WHISKER PLOT DISTRIBUTION
    bw_cutoff_date = storage_df['period'].max() - pd.DateOffset(years=5)
    bw_plot_df = storage_df.loc[storage_df['period']>=(bw_cutoff_date)]
    
    # Compute 3 dots displayed on plot
    latest_dots = (storage_df.sort_values('period').groupby('Region').tail(1))
    one_year_ago_dots = (storage_df.loc[storage_df['period']<=(bw_cutoff_date-pd.DateOffset(years=1))].sort_values('period').groupby('Region').tail(1))
    five_year_avg_dots = (bw_plot_df.groupby('Region', as_index=False)['value'].mean())
    
    box_whisker_fig = px.box(
        bw_plot_df,
        x='Region',
        y='value',
        color='Region',
        points=False
    )
    box_whisker_fig.add_trace(
        go.Scatter(
            x=latest_dots['Region'],
            y=latest_dots['value'],
            mode='markers', name='Latest',
            marker=dict(symbol='circle', size=10, color='black', line=dict(width=1, color='white'))
        )
    )
    box_whisker_fig.add_trace(
        go.Scatter(
            x=one_year_ago_dots['Region'],
            y=one_year_ago_dots['value'],
            mode='markers', name='1 year ago',
            marker=dict(symbol='diamond', size=10, color='red')
        )
    )
    box_whisker_fig.add_trace(
        go.Scatter(
            x=five_year_avg_dots['Region'],
            y=five_year_avg_dots['value'],
            mode='markers', name='5 year average',
            marker=dict(symbol='x', size=12, color='blue')
        )
    )
    box_whisker_fig.update_layout(
        title='Storage Values by Region',
        xaxis_title='Region', yaxis_title='Storage, Weekly frequency (BCF)',
        yaxis=dict(showgrid=True, gridcolor='rgba(67, 71, 79, 0.35)'),
        xaxis=dict(showgrid=False), legend_title_text='Legend', boxmode='overlay',
        margin=dict(t=60, b=90), hovermode="x unified"
    )
    box_whisker_fig.add_annotation(
        text='Data Source: Weekly Working Gas in Underground Gas (EIA). Distribution is based on latest 5 years of data.',
        xref='paper', yref='paper', x=0, y=-0.30, showarrow=False, align='left',
        font=dict(size=10)
    )
    
    #### WEEKLY GAS CHANGE DATA TABLE
    data_table = dash_table.DataTable(
        id='regional-latest-storage',
        columns = [
            {"name": "Region", "id": "Region"},
            {"name": "Date", "id": "Date_Display"},
            {"name": "Storage (BCF)", "id": "value", "type": "numeric", "format": Format(precision=0, scheme=Scheme.fixed)},
            {"name": "WoW Change (BCF)", "id": "WoW_Change", "type": "numeric", "format": Format(precision=0, scheme=Scheme.fixed)},
            {"name": "WoW % Change", "id": "WoW_pctChange", "type": "numeric", "format": Format(precision=2, scheme=Scheme.fixed)},
            {"name": "YoY Change (BCF)", "id": "YoY_Change", "type": "numeric", "format": Format(precision=0, scheme=Scheme.fixed)},
            {"name": "YoY % Change", "id": "YoY_pctChange", "type": "numeric", "format": Format(precision=2, scheme=Scheme.fixed)}
        ],
        data = storage_df[storage_df['period'] == storage_df['period'].max()].to_dict('records'),
        sort_action='native', filter_action='native',
        style_table={"overflowX": "auto"},
        style_cell = {'textAlign': 'center', 'padding': '6px'},
        style_data_conditional=[
            {
                "if": {"filter_query": "{WoW_Change} < 0", 'column_id': ["WoW_Change", "WoW_pctChange"]},
                "color": "red"
            },
            {
                "if": {"filter_query": "{WoW_Change} > 0", 'column_id': ["WoW_Change", "WoW_pctChange"]},
                "color": "green"
            },
            {
                "if": {"filter_query": "{YoY_Change} < 0", 'column_id': ["YoY_Change", "YoY_pctChange"]},
                "color": "red"
            },
            {
                "if": {"filter_query": "{YoY_Change} > 0", 'column_id': ["YoY_Change", "YoY_pctChange"]},
                "color": "green"
            }
        ]
    )
    latest_EIA_update = (storage_df['period'].max()+timedelta(days=7)).strftime("%B %d, %Y")
    next_EIA_update = (storage_df['period'].max()+timedelta(days=14)).strftime("%B %d, %Y")
    
    data_table_annotated = html.Div(
        [
            html.H4("Regional Weekly Gas Storage Snapshot",
                    style={'marginBottom':'8px', 'fontWeight':'300','textAlign':'center'}),
            data_table,
            html.P(
                f"Note: Data is accurate as of latest EIA weekly release on {latest_EIA_update}. Next update on {next_EIA_update}.",
                style={'fontSize':'11px','color':'#6b7280','marginTop':'6px'}
            )
        ]
    )
    
    return fig_wkly_stor_stack, box_whisker_fig, data_table_annotated