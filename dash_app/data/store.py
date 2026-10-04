import io
import json
import pandas as pd
from dash_app.cache import cache
from dash_app.r2_cloudflare import s3, BUCKET

@cache.memoize(timeout=6*3600)
def load(key):
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    return pd.read_parquet(io.BytesIO(obj["Body"].read()))

@cache.memoize(timeout=6*3600)
def load_json(key):
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    return json.loads(obj["Body"].read())

def load_ng_data():
    names = ["pipeline", "lease", "production", "consumption", "imports",
             "exports", "prod_share", "demand_share"]
    return tuple(load(f"ng/{n}.parquet") for n in names)

def load_storage():
    return load("ng/storage_regional.parquet"), load("ng/storage_agg.parquet")

def load_gem_data():
    _, locations = "gem/plant_units.parquet", "gem/plant_locations.parquet"
    pipes_main, lng_units = "gem/pipeline_metadata.parquet", "gem/lng_terminals.parquet"
    pipeline_segments = "gem/pipeline_segments.json"

    return load(locations), load(pipes_main), load(lng_units), load_json(pipeline_segments)