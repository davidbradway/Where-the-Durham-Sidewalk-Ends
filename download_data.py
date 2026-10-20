"""Download the public datasets used by sidewalk_gaps.py into ./data.

Usage:  python download_data.py [--data-dir data] [--force]

Uses only the Python standard library. Sources (City/County of Durham open data):
  parcels.gpkg       Parcels (ArcGIS Hub GeoPackage export, EPSG:2264)
  sidewalks.geojson  Public Works sidewalk inventory (ArcGIS REST, reprojected to EPSG:2264)
  streets.geojson    Street centerlines / maintenance responsibility (ArcGIS REST, EPSG:2264)
"""
import argparse
import json
import shutil
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

PARCELS_URL = ("https://live-durhamnc.opendata.arcgis.com/api/download/v1/items/"
               "da3d194d1e2e4c37afa851b46e29a3f6/geoPackage?layers=0")
REST_LAYERS = {
    "sidewalks.geojson": "https://webgis2.durhamnc.gov/server/rest/services/"
                         "PublicWorksServices/Sidewalks/MapServer/120",
    "streets.geojson": "https://services2.arcgis.com/G5vR3cOjh6g2Ed8E/arcgis/rest/services/"
                       "Street_Maintenance_Responsibility/FeatureServer/0",
}
OUT_SR = 2264  # NC State Plane, US feet
BATCH = 500
UA = {"User-Agent": "durham-sidewalk-gaps/1.0"}


def fetch(url, data=None, retries=4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=UA)
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read()
        except OSError as e:
            if attempt == retries - 1:
                raise
            print(f"  retry after error: {e}")
            time.sleep(2 ** attempt)


def query(layer_url, **params):
    body = urllib.parse.urlencode({"f": "json", **params}).encode()
    out = json.loads(fetch(f"{layer_url}/query", data=body))  # POST: long objectIds lists
    if "error" in out:
        raise RuntimeError(f"{layer_url}: {out['error']}")
    return out


def download_rest_layer(layer_url, dest):
    ids = sorted(query(layer_url, where="1=1", returnIdsOnly="true")["objectIds"])
    print(f"  {len(ids):,} features")
    features = []
    for s in range(0, len(ids), BATCH):
        chunk = query(layer_url, objectIds=",".join(map(str, ids[s:s + BATCH])),
                      outFields="*", outSR=OUT_SR, f="geojson")
        features += chunk["features"]
        print(f"  {len(features):,}/{len(ids):,}", end="\r")
    print()
    fc = {"type": "FeatureCollection",
          "crs": {"type": "name", "properties": {"name": f"EPSG:{OUT_SR}"}},
          "features": features}
    tmp = dest.with_suffix(".part")
    tmp.write_text(json.dumps(fc), encoding="utf-8")
    tmp.replace(dest)


def download_file(url, dest):
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, length=1 << 20)
    with open(tmp, "rb") as f:
        if f.read(16) != b"SQLite format 3\x00":
            raise RuntimeError(f"{url} did not return a GeoPackage (export may still be generating; retry later)")
    tmp.replace(dest)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default="data", type=Path)
    ap.add_argument("--force", action="store_true", help="re-download files that already exist")
    args = ap.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)

    jobs = [("parcels.gpkg", lambda d: download_file(PARCELS_URL, d))]
    jobs += [(name, lambda d, u=url: download_rest_layer(u, d)) for name, url in REST_LAYERS.items()]
    for name, job in jobs:
        dest = args.data_dir / name
        if dest.exists() and not args.force:
            print(f"{dest} exists, skipping (use --force to refresh)")
            continue
        print(f"downloading {dest} ...")
        job(dest)
        print(f"  wrote {dest.stat().st_size / 1e6:,.1f} MB")


if __name__ == "__main__":
    sys.exit(main())
