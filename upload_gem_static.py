import io
import json
from pathlib import Path
from prep_gogpt import load_units, build_locations, find_path_bothways
from prep_pipelines import process_pipelines, process_lng
from dash_app.r2_cloudflare import s3, BUCKET

gogpt_names = ["plant_units", "plant_locations"]
pipeline_names = ["pipeline_segments", "pipeline_metadata", "no_coord_pipes", "summ_stats"]

current_dir = Path.cwd()
plant_excel_file = find_path_bothways(current_dir, "DATA_BANK/FUNDAMENTALS/GOGPT/Global Oil and Gas Plant Tracker (GOGPT) - August 2026.xlsx")
pipeline_folder = find_path_bothways(current_dir, "DATA_BANK/FUNDAMENTALS/Pipes_geojson_handle")

units = load_units(plant_excel_file)
units_frames = {gogpt_names[0]: units}
locations = build_locations(units)
locations_frames = {gogpt_names[1]: locations}

pipe_no_lng = dict(zip(pipeline_names, process_pipelines(pipeline_folder)))
lng = process_lng(pipeline_folder)
lng_frames = {'lng_terminals': lng}

for fuel, s in pipe_no_lng['summ_stats'].items():
    print(f"{fuel}: {s['features']:,} features, vertices "
            f"{s['raw_vertices']:,} -> {s['kept_vertices']:,} (active only), "
            f"unparseable capacity: {len(s['bad_capacity'])}")
print(f"meta {len(pipe_no_lng['pipeline_metadata']):,} | undrawable {len(pipe_no_lng['no_coord_pipes']):,} | lng {len(lng):,}")

for name, df in units_frames.items():
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    s3.put_object(Bucket=BUCKET, Key=f"gem/{name}.parquet", Body=buf.getvalue())
    print(f"uploaded gem/{name}.parquet ({len(df)} rows)")

for name, df in locations_frames.items():
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    s3.put_object(Bucket=BUCKET, Key=f"gem/{name}.parquet", Body=buf.getvalue())
    print(f"uploaded gem/{name}.parquet ({len(df)} rows)")

for name, df in pipe_no_lng.items():
    if name == 'summ_stats':
        continue
    if name == 'pipeline_segments':
        s3.put_object(Bucket=BUCKET, Key=f"gem/{name}.json", Body=json.dumps(df).encode("utf-8"), ContentType="application/json")
    else:
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        s3.put_object(Bucket=BUCKET, Key=f"gem/{name}.parquet", Body=buf.getvalue())

    if name != 'pipeline_segments':
        print(f"uploaded gem/{name}.parquet ({len(df)} rows)")
    else:
        print(f"uploaded gem/{name}.parquet (pipeline_segments)")

for name, df in lng_frames.items():
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    s3.put_object(Bucket=BUCKET, Key=f"gem/{name}.parquet", Body=buf.getvalue())
    print(f"uploaded gem/{name}.parquet ({len(df)} rows)")