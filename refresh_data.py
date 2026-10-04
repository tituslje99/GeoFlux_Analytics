import io
from dash_app.APIs import EIA_data_generator, update_storage
from dash_app.r2_cloudflare import s3, BUCKET

names = ["pipeline", "lease", "production", "consumption", "imports", "exports",
         "prod_share", "demand_share"]

frames = dict(zip(names, EIA_data_generator()))
frames["storage_regional"], frames["storage_agg"] = update_storage()

for name, df in frames.items():
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    s3.put_object(Bucket=BUCKET, Key=f"ng/{name}.parquet", Body=buf.getvalue())
    print(f"uploaded ng/{name}.parquet ({len(df)} rows)")