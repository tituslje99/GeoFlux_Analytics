from dash import html, dcc, register_page, Input, Output, callback
import plotly.express as px
import pandas as pd

# Register this page
register_page(
    __name__,
    path="/crude_window",
    name="Crude Oil",
    title="Crude Oil Monitoring"
)

# Dummy data
df = pd.DataFrame({
    "Date": pd.date_range("2024-01-01", periods=10, freq="W"),
    "Inventory": [320, 330, 315, 340, 350, 360, 370, 355, 345, 335]
})

# Page layout
def layout():
    return html.Div([
        html.H2("Crude Oil Dashboard"),
        html.P("Monitoring inventories, flows, and spreads."),
        
        dcc.Tabs(id="crude-tabs", value="inventories", children=[
            dcc.Tab(label="Inventories", value="inventories"),
            dcc.Tab(label="Pricing", value="pricing"),
            dcc.Tab(label="Flows", value="flows")
        ]),
        
        html.Div(id="crude-content")
    ])

@callback(
    Output("crude-content", "children"),
    Input("crude-tabs", "value")
)
def update_tab(tab_value):
    if tab_value == "inventories":
        fig = px.line(df, x="Date", y="Inventory", title="Crude Inventories (MMbbl)")
        return html.Div(dcc.Graph(figure=fig), className="card-surface")
    elif tab_value == "pricing":
        return html.Div("Pricing data and charts will go here.", className="card-surface")
    elif tab_value == "flows":
        return html.Div("Trade flow maps and balances will go here.", className="card-surface")