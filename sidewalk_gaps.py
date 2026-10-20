"""Rank Durham property owners by street frontage lacking an adjacent sidewalk.

Usage:  python sidewalk_gaps.py [data_dir=data] [out_dir=outputs]
        (run download_data.py first)

Method
  1. Parcels (EPSG:2264, ft) inside City of Durham limits; stacked condo duplicates
     collapsed to one footprint.
  2. Each parcel boundary is cut into <=SEG_FT pieces. A piece is street frontage when
       - it is NOT within SHARED_FT of any other parcel (i.e. it borders the
         right-of-way gap in the parcel fabric, not a neighbour), and
       - it is within STREET_FT of a public street centerline (interstates, ramps,
         alleys and private drives excluded).
  3. A frontage piece is "covered" when a sidewalk line is within SIDEWALK_FT.
  4. Owners are normalised + aliased, then frontage is summed per owner.
"""
import re, sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

SEG_FT, SHARED_FT, STREET_FT, SIDEWALK_FT = 10.0, 1.5, 75.0, 25.0
EXCLUDED_STREETS = {"INTERSTATE", "RAMP", "ALLEY", "PRIVATE", "MEDIAN_XING"}
EXCLUDED_FUNC = {"Interstate", "Freeway/Expressway", "Freeway"}

data = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
out = Path(sys.argv[2] if len(sys.argv) > 2 else "outputs")
out.mkdir(exist_ok=True)

# ---------------------------------------------------------------- load
cols = ["PARCEL_TYPE", "PIN", "REID", "PROPERTY_OWNER", "OWNER_MAIL_1", "OWNER_MAIL_2",
        "OWNER_MAIL_CITY", "OWNER_MAIL_STATE", "OWNER_MAIL_ZIP", "LOCATION_ADDR",
        "CITY", "LAND_CLASS", "ACREAGE", "TOTAL_PROP_VALUE"]
par = gpd.read_file(data / "parcels.gpkg", columns=cols)
assert par.crs.to_epsg() == 2264
par["geometry"] = par.geometry.make_valid()

# collapse identical stacked footprints; prefer base parcel, then condo association
par = (par.assign(_wkb=par.geometry.to_wkb(), _rank=par.PARCEL_TYPE.map({0: 0, 1: 1, 2: 2}))
          .sort_values("_rank").drop_duplicates("_wkb").drop(columns=["_wkb", "_rank"])
          .reset_index(drop=True))
print("unique footprints:", len(par))

sw = gpd.read_file(data / "sidewalks.geojson").set_crs(2264, allow_override=True)
st = gpd.read_file(data / "streets.geojson").set_crs(2264, allow_override=True)
st_ok = st[~st.FTRCODE.isin(EXCLUDED_STREETS) & ~st.FUNCCLASS.isin(EXCLUDED_FUNC)]
print(f"sidewalks {len(sw)}, streets {len(st)} -> {len(st_ok)} eligible")

in_city = par.CITY.fillna("").str.contains("DURHAM").to_numpy()
city_idx = np.flatnonzero(in_city)
print("city parcels:", len(city_idx))

# ---------------------------------------------------------------- boundary pieces
rings = shapely.segmentize(shapely.get_parts(par.geometry.values[city_idx].boundary, return_index=True)[0], SEG_FT)
_, ring_owner = shapely.get_parts(par.geometry.values[city_idx].boundary, return_index=True)
ring_owner = city_idx[ring_owner]
coords, ring_id = shapely.get_coordinates(rings, return_index=True)
same = ring_id[1:] == ring_id[:-1]
a, b = coords[:-1][same], coords[1:][same]
seg_parcel = ring_owner[ring_id[:-1][same]]
seg_len = np.hypot(*(b - a).T)
mid = shapely.points((a + b) / 2)
print(f"{len(mid):,} boundary pieces")

ptree = shapely.STRtree(par.geometry.values)
stree = shapely.STRtree(st_ok.geometry.values)
wtree = shapely.STRtree(sw.geometry.values)

def any_hit(tree, pts, dist, own=None, chunk=500_000):
    hit = np.zeros(len(pts), bool)
    for s in range(0, len(pts), chunk):
        i, j = tree.query(pts[s:s + chunk], predicate="dwithin", distance=dist)
        if own is not None:
            keep = j != own[s:s + chunk][i]
            i = i[keep]
        hit[s + np.unique(i)] = True
    return hit

shared = any_hit(ptree, mid, SHARED_FT, own=seg_parcel)
cand = np.flatnonzero(~shared)
near_street = np.zeros(len(mid), bool)
near_street[cand] = any_hit(stree, mid[cand], STREET_FT)
front = np.flatnonzero(near_street)
covered = np.zeros(len(mid), bool)
covered[front] = any_hit(wtree, mid[front], SIDEWALK_FT)
print(f"frontage pieces {len(front):,}; covered {covered.sum():,}")

# classify each frontage piece by the street it faces
i, j = stree.query_nearest(mid[front], all_matches=False)
near = st_ok.iloc[j[np.argsort(i)]]
street_class = np.where(near.FTRCODE.str.contains("Pending").to_numpy(), "pending",
                np.where(near.FUNCCLASS.isin(["LocalRoads"]).to_numpy(), "local", "major"))

seg = pd.DataFrame({"pidx": seg_parcel[front], "len": seg_len[front], "covered": covered[front],
                    "cls": street_class})
seg["miss"] = seg.len * ~seg.covered
by = seg.pivot_table(index="pidx", columns="cls", values=["len", "miss"], aggfunc="sum", fill_value=0)
agg = pd.DataFrame(index=by.index)
agg["frontage_ft"] = by["len"][["local", "major"]].sum(axis=1)  # accepted streets only
agg["missing_ft"] = by["miss"][["local", "major"]].sum(axis=1)
agg["covered_ft"] = agg.frontage_ft - agg.missing_ft
agg["missing_major_ft"] = by["miss"]["major"]  # collectors + arterials
agg["pending_frontage_ft"] = by["len"].get("pending", 0)
agg["pending_missing_ft"] = by["miss"].get("pending", 0)
print(seg.groupby("cls").apply(lambda g: f"{g.len.sum()/5280:,.0f} mi, {1-g.miss.sum()/g.len.sum():.0%} covered",
                               include_groups=False))

# ---------------------------------------------------------------- owner normalisation
ALIASES = [  # (regex on cleaned name, canonical owner)
    (r"^DUKE UNIV|^DUKE UNIVERSITY HEALTH", "DUKE UNIVERSITY (incl. Health System)"),
    (r"^DUKE ENERGY", "DUKE ENERGY"),
    (r"^CITY OF DURHAM|^DURHAM CITY OF|^THE CITY OF DURHAM", "CITY OF DURHAM"),
    (r"^COUNTY OF DURHAM|^DURHAM COUNTY$|^DURHAM COUNTY OF", "DURHAM COUNTY"),
    (r"DURHAM PUBLIC SCHOOLS|DURHAM COUNTY BOARD OF ED|^BOARD OF EDUCATION|DURHAM CITY BOARD OF ED",
     "DURHAM PUBLIC SCHOOLS"),
    (r"^HOUSING AUTHORITY OF THE CITY|^DURHAM HOUSING AUTH", "DURHAM HOUSING AUTHORITY"),
    (r"DEPARTMENT OF TRANSPORTATION|^NC DOT|^NCDOT|TURNPIKE AUTHORITY|STATE HWY COMMISSION|STATE HIGHWAY COMMISSION",
     "NC DEPT OF TRANSPORTATION"),
    (r"^INTERNATIONAL BUSINESS MACHINE", "IBM"),
    (r"^M M FOWLER|^FOWLER M M|^FOWLER INC M M", "M M FOWLER"),
    (r"^TREYBURN RESIDENTIAL OWNERS", "TREYBURN RESIDENTIAL OWNERS ASSOCIATION"),
    (r"^HOPE VALLEY FARMS NORTH (HOMEOWNERS|OWNERS)", "HOPE VALLEY FARMS NORTH HOMEOWNERS ASSOCIATION"),
    (r"^N ?C CENTRAL UNIV|^NORTH CAROLINA CENTRAL UNIV", "NC CENTRAL UNIVERSITY"),
    (r"^STATE OF NORTH CAROLINA|^STATE OF N ?C$", "STATE OF NORTH CAROLINA"),
    (r"^UNITED STATES OF AMERICA|^USA$", "UNITED STATES OF AMERICA"),
    (r"^RESEARCH TRIANGLE FOUNDATION", "RESEARCH TRIANGLE FOUNDATION"),
    (r"^NORFOLK SOUTHERN|^NORTH CAROLINA RAILROAD", "RAILROADS (NS / NCRR)"),
]
SUFFIX = r"\b(INCORPORATED|INC|LLC|L L C|LP|L P|LTD|LLP|CORPORATION|CORP|CO|COMPANY|THE)\b"

def clean(name):
    s = re.sub(r"[^A-Z0-9 ;&]", " ", str(name or "").upper())
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\bUNIV\b", "UNIVERSITY", s)
    s = re.sub(r"\bOFEDUCATION\b", "OF EDUCATION", s)
    s = re.sub(r"\bHOME OWNERS\b", "HOMEOWNERS", s)
    s = re.sub(r"\bASSOCIA TION\b|\bASSOCIATIONINC\b|\bASSOCI\b|\bASSOC\b|\bASSN\b", "ASSOCIATION", s)
    for pat, canon in ALIASES:
        if re.search(pat, s):
            return canon
    return re.sub(r"\s+", " ", re.sub(SUFFIX, " ", s)).strip() or "(UNKNOWN)"

pp = par.loc[agg.index].copy()
pp = pp.join(agg)
pp["owner"] = pp.PROPERTY_OWNER.map(clean)
pp["mail_key"] = (pp.OWNER_MAIL_1.fillna("").str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
                  + "|" + pp.OWNER_MAIL_ZIP.fillna("").astype(str).str[:5])
pp["pct_missing"] = (pp.missing_ft / pp.frontage_ft).round(3)

own = (pp.groupby("owner")
         .agg(parcels=("PIN", "size"), frontage_ft=("frontage_ft", "sum"),
              covered_ft=("covered_ft", "sum"), missing_ft=("missing_ft", "sum"),
              missing_major_ft=("missing_major_ft", "sum"),
              pending_missing_ft=("pending_missing_ft", "sum"),
              acres=("ACREAGE", "sum"),
              raw_names=("PROPERTY_OWNER", lambda s: "; ".join(s.value_counts().index[:6])),
              mail_keys=("mail_key", lambda s: s.mode().iat[0]))
         .sort_values("missing_ft", ascending=False))
own["pct_missing"] = (own.missing_ft / own.frontage_ft).round(3)
own["missing_miles"] = (own.missing_ft / 5280).round(2)
own["major_rank"] = own.missing_major_ft.rank(ascending=False, method="min").astype(int)

# related entities: other owner names sharing the top mailing address
mail_names = pp.groupby("mail_key").owner.agg(lambda s: sorted(set(s)))
own["same_mailing_addr_owners"] = [
    "; ".join(n for n in mail_names.get(k, []) if n != o)[:300] for o, k in zip(own.index, own.mail_keys)]

mail = (pp[pp.mail_key.str.len() > 7]
          .groupby("mail_key")
          .agg(owners=("owner", lambda s: "; ".join(s.value_counts().index[:8])),
               n_owner_names=("owner", "nunique"), parcels=("PIN", "size"),
               frontage_ft=("frontage_ft", "sum"), missing_ft=("missing_ft", "sum"),
               missing_major_ft=("missing_major_ft", "sum"), mail_addr=("OWNER_MAIL_1", "first"), mail_city=("OWNER_MAIL_CITY", "first"))
          .sort_values("missing_ft", ascending=False))

# ---------------------------------------------------------------- write
tot_f, tot_c = agg.frontage_ft.sum(), agg.covered_ft.sum()
print(f"\nCity frontage (accepted streets) {tot_f/5280:,.0f} mi; covered {tot_c/5280:,.0f} mi ({tot_c/tot_f:.0%}); "
      f"missing {(tot_f-tot_c)/5280:,.0f} mi; owners {len(own):,}")
tot_major = own.missing_major_ft.sum()
major_sorted = own.missing_major_ft.sort_values(ascending=False)
for n in (10, 25, 50, 100):
    print(f"top {n} owners hold {own.missing_ft.iloc[:n].sum()/(tot_f-tot_c):.1%} of missing frontage; "
          f"top {n} by major-street gap hold {major_sorted.iloc[:n].sum()/tot_major:.1%} of major-street gap")

own.to_csv(out / "owners_ranked.csv")
mail.head(500).to_csv(out / "mailing_address_groups.csv")
pp.drop(columns="geometry").sort_values("missing_ft", ascending=False).to_csv(out / "parcels_frontage.csv", index=False)

# frontage pieces for mapping (dissolved per parcel x status)
lines = shapely.linestrings(np.stack([a[front], b[front]], 1))
fg = gpd.GeoDataFrame({"pidx": seg_parcel[front], "sidewalk": covered[front], "street_class": street_class},
                      geometry=lines, crs=2264)
fg = fg.dissolve(["pidx", "sidewalk", "street_class"]).reset_index()
fg = fg.join(pp[["PIN", "PROPERTY_OWNER", "owner", "LOCATION_ADDR"]], on="pidx")
fg["geometry"] = shapely.line_merge(fg.geometry.values)
fg.to_file(out / "frontage.gpkg", layer="frontage", driver="GPKG")
pp.to_file(out / "frontage.gpkg", layer="parcels_with_frontage", driver="GPKG")
print("wrote", *sorted(p.name for p in out.iterdir()))

pd.set_option("display.width", 250, "display.max_colwidth", 70)
show = ["parcels", "frontage_ft", "missing_ft", "pct_missing", "missing_major_ft", "major_rank", "pending_missing_ft"]
print(own[show].head(40).round(2).to_string())
print(own.sort_values("missing_major_ft", ascending=False)[show].head(30).round(2).to_string())
print(mail[["n_owner_names", "parcels", "missing_ft", "missing_major_ft", "mail_addr"]].head(20).round(0).to_string())
