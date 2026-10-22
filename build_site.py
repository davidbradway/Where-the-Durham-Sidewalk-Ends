"""Build the static outreach site from sidewalk_gaps.py outputs.

Usage:  python build_site.py [outputs_dir=outputs] [site_dir=site] [data_dir=data]

Writes site/index.html (copied from web/index.html) plus site/data/*.json|csv, and
site/data/sidewalks.geojson (the full sidewalk inventory, for the "Show all sidewalks" toggle).
Only organisations (companies, institutions, governments, associations) are named;
parcels owned by individuals are shown on the map without a name.
"""
import json, re, shutil, sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely

outputs = Path(sys.argv[1] if len(sys.argv) > 1 else "outputs")
site = Path(sys.argv[2] if len(sys.argv) > 2 else "site")
data_dir = Path(sys.argv[3] if len(sys.argv) > 3 else "data")
TOP_N = 100

ENTITY = re.compile(
    r"\b(LLC|L L C|INC|INCORPORATED|CORP|CORPORATION|COMPANY|CO|LP|LLP|LTD|ASSOC|ASSOCIATION|ASSOCIATES|"
    r"ASSOCI|TRUST|TRUSTEES|CHURCH|MINISTRIES|UNIVERSITY|COLLEGE|SCHOOLS?|ACADEMY|CITY|COUNTY|STATE|"
    r"UNITED STATES|AUTHORITY|DEPARTMENT|BOARD|CLUB|PARTNERSHIP|PARTNERS|FOUNDATION|RAILROAD|HOMES|"
    r"PROPERTIES|HOLDINGS|INVESTMENTS?|DEVELOPMENT|REALTY|ENERGY|HOSPITAL|HEALTH|COMMUNITY|HOMEOWNERS|"
    r"OWNERS|TOWNHOMES|CONDOMINIUM|FUND|GROUP|CENTER|VENTURES|ENTERPRISES|MALL|AGRINOMICS|GARDENS|"
    r"SYSTEM|BANK|COMMISSION|CEMETERY|STONEMOR|TRANSPORTATION)\b")


def is_entity(name):
    return bool(ENTITY.search(str(name or "").upper()))


# ------------------------------------------------------------ owners
own = pd.read_csv(outputs / "owners_ranked.csv")
own = own[own.raw_names.map(lambda s: any(is_entity(n) for n in str(s).split("; ")))].copy()
own = own[own.frontage_ft > 0]
by_all = own.nlargest(TOP_N, "missing_ft")
by_major = own.nlargest(TOP_N, "missing_major_ft")
top = pd.concat([by_all, by_major]).drop_duplicates("owner").reset_index(drop=True)
top["id"] = top.index
rank_all = {o: i + 1 for i, o in enumerate(by_all.owner)}
rank_major = {o: i + 1 for i, o in enumerate(by_major.owner)}

# ------------------------------------------------------------ map features
fr = gpd.read_file(outputs / "frontage.gpkg", layer="frontage")
owner_id = dict(zip(top.owner, top.id))
fr["oid"] = fr.owner.map(owner_id)
keep = fr.oid.notna() | (fr.street_class == "major")
fr = fr[keep].copy()
fr["geometry"] = fr.geometry.simplify(3)
fr = fr.to_crs(4326)
named = fr.PROPERTY_OWNER.map(is_entity).to_numpy()


def val(x):
    """JSON-safe scalar: pandas missing values (NaN/NA) become None."""
    return None if pd.isna(x) else x

def bboxes(df):
    out = {}
    for oid, g in df[df.oid.notna()].groupby("oid"):
        x0, y0, x1, y1 = g.total_bounds
        out[int(oid)] = [round(y0, 5), round(x0, 5), round(y1, 5), round(x1, 5)]
    return out

bbox, bbox_major = bboxes(fr), bboxes(fr[fr.street_class == "major"])  # zoom target per map tab

feats = []
for is_named, row in zip(named, fr.itertuples()):
    geom = shapely.set_precision(row.geometry, 1e-5)
    if geom.is_empty:
        continue
    name = val(row.owner) if is_named else None
    feats.append({"type": "Feature",
                  "properties": {"s": int(row.sidewalk), "c": row.street_class[0],
                                 "o": None if pd.isna(row.oid) else int(row.oid),
                                 "n": name, "a": val(row.LOCATION_ADDR) if name else None},
                  "geometry": shapely.geometry.mapping(geom)})

# ------------------------------------------------------------ sidewalk inventory (geometry only)
sw = gpd.read_file(data_dir / "sidewalks.geojson").set_crs(2264, allow_override=True)
sw = sw[sw.geometry.notna() & ~sw.geometry.is_empty]
sw_geoms = shapely.set_precision(sw.geometry.simplify(3).to_crs(4326).to_numpy(), 1e-5)
sw_feats = [{"type": "Feature", "properties": {}, "geometry": shapely.geometry.mapping(g)}
            for g in sw_geoms if g is not None and not g.is_empty]

# ------------------------------------------------------------ summary
par = pd.read_csv(outputs / "parcels_frontage.csv", usecols=["frontage_ft", "missing_ft", "missing_major_ft", "LAND_CLASS"],
                  low_memory=False)
all_owners = pd.read_csv(outputs / "owners_ranked.csv", usecols=["missing_ft", "missing_major_ft"])
miss, maj = all_owners.missing_ft.sum(), all_owners.missing_major_ft.sum()
summary = {
    "frontage_mi": round(par.frontage_ft.sum() / 5280),
    "missing_mi": round(par.missing_ft.sum() / 5280),
    "pct_covered": round(1 - par.missing_ft.sum() / par.frontage_ft.sum(), 3),
    "major_missing_mi": round(maj / 5280),
    "top100_share_all": round(all_owners.missing_ft.nlargest(100).sum() / miss, 3),
    "top100_share_major": round(all_owners.missing_major_ft.nlargest(100).sum() / maj, 3),
    "single_family_share": round(par[par.LAND_CLASS == "RES/ 1-FAMILY"].missing_ft.sum() / miss, 3),
    "built": pd.Timestamp.now(tz="America/New_York").strftime("%Y-%m-%d"),
}

owners_json = [{
    "id": int(r.id), "owner": r.owner, "parcels": int(r.parcels),
    "frontage_mi": round(r.frontage_ft / 5280, 2), "missing_mi": round(r.missing_ft / 5280, 2),
    "major_mi": round(r.missing_major_ft / 5280, 2), "pct": round(r.pct_missing, 3),
    "names": val(r.raw_names), "rank_all": rank_all.get(r.owner), "rank_major": rank_major.get(r.owner),
    "bbox": bbox.get(int(r.id)), "bbox_major": bbox_major.get(int(r.id)),
} for r in top.itertuples()]

# ------------------------------------------------------------ write
(site / "data").mkdir(parents=True, exist_ok=True)
shutil.copy(Path(__file__).parent / "web" / "index.html", site / "index.html")
# allow_nan=False: fail the build rather than emit NaN, which browsers reject as invalid JSON
(site / "data" / "owners.json").write_text(
    json.dumps({"summary": summary, "owners": owners_json}, allow_nan=False), encoding="utf-8")
(site / "data" / "frontage.geojson").write_text(
    json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":"), allow_nan=False),
    encoding="utf-8")
(site / "data" / "sidewalks.geojson").write_text(
    json.dumps({"type": "FeatureCollection", "features": sw_feats}, separators=(",", ":"), allow_nan=False),
    encoding="utf-8")
cols = ["owner", "parcels", "frontage_ft", "missing_ft", "missing_major_ft", "pct_missing", "pending_missing_ft", "raw_names"]
top.assign(rank_all=top.owner.map(rank_all), rank_major=top.owner.map(rank_major))[
    ["rank_all", "rank_major"] + cols].round(0).to_csv(site / "data" / "top_owners.csv", index=False)
for p in sorted((site / "data").iterdir()):
    print(f"{p}: {p.stat().st_size / 1e6:.1f} MB")
print(f"{len(feats):,} map features, {len(sw_feats):,} sidewalk features, {len(top)} named owners")
