from dash import Dash
from dash_app.cache import cache

app = Dash(
    __name__,
    use_pages=True,
    suppress_callback_exceptions=True,
    title="GeoFlux",
)
server = app.server

cache.init_app(server)