from dash import html, dcc, Input, Output, callback, ALL
from dash_app.app import app
import dash

server = app.server

NAV_ITEMS = [
    ("Crude Tracker", "/crude_window"),
    ("NG Tracker", "/natty_window"),
    ("Global Assets Tracker", "/global_assets_tracker")
]

app.layout = html.Div(
    [
        html.Header(
            [
                html.Div(className="header-bg", **{"aria-hidden": "true"}),
                html.Div(
                    [
                        html.Div(
                            [
                                html.H1("GeoFlux Analytics", className="brand-title"),
                                html.P("Commodity flow intelligence", className="brand-tagline"),
                            ],
                            className="brand-bar",
                        ),
                        html.Nav(
                            [
                                dcc.Link(
                                    label,
                                    href=href,
                                    id={"type": "nav-link", "index": href},
                                    className="nav-link",
                                )
                                for label, href in NAV_ITEMS
                            ],
                            className="nav-bar",
                        ),
                    ],
                    className="header-content",
                ),
            ],
            className="app-header",
        ),
        html.Main(dash.page_container, className="app-content"),
    ],
    className="app-shell",
)


@callback(
    Output({"type": "nav-link", "index": ALL}, "className"),
    Input("_pages_location", "pathname"),
)
def highlight_active_nav(pathname):
    base = "nav-link"
    active = f"{base} nav-link--active"
    return [active if href == pathname else base for _, href in NAV_ITEMS]


""" if __name__ == "__main__":
    app.run(debug=True, use_reloader=False) """