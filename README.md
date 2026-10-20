# Where the Durham Sidewalk Ends

Which property owners in the City of Durham, NC have the most street frontage with **no sidewalk**?

This project joins Durham's parcel map, sidewalk inventory and street centerlines to measure every
parcel's street frontage and how much of it has a sidewalk alongside it. It then totals the gaps
by owner, so advocates can focus on the few organizations that control the most missing sidewalk.

**Interactive map and rankings:** https://davidbradway.github.io/Where-the-Durham-Sidewalk-Ends/

## Key findings

*Data downloaded October 2026. Figures cover parcels inside city limits that front accepted public streets.*

| | |
|---|---|
| Street frontage measured | **1,970 mi** |
| Frontage with a sidewalk within 25 ft | **32%** (637 mi) |
| Frontage with **no** sidewalk | **1,333 mi** |
| Coverage on local streets / busy streets (collectors + arterials) | 28% / 49% |
| Share of missing frontage in front of single-family homes | 68% |
| Share of missing frontage owned by the top 100 owners | 11% |
| Share of the **busy-street** gap (227 mi) owned by the top 100 owners | **32%** |

**What this means for advocacy:** most missing sidewalk is in front of individual homes on local streets,
so no small set of owners accounts for the gap overall. Busy streets are different. There, ten owners
account for 17% of the gap and the top 100 for about a third. Ranking owners by busy-street frontage
gives the shortest list of organizations to approach.

### Top owners by missing sidewalk on busy streets (collectors and arterials)

| # | Owner | Missing, busy streets (mi) | Missing, all streets (mi) | % of their frontage missing |
|--:|---|--:|--:|--:|
| 1 | Duke University (incl. Duke University Health System) | 11.4 | 14.9 | 56% |
| 2 | City of Durham | 11.1 | 25.3 | 57% |
| 3 | NC Railroad | 4.8 | 8.1 | 86% |
| 4 | Durham Public Schools | 3.0 | 6.1 | 38% |
| 5 | United States of America (incl. VA) | 2.4 | 3.4 | 80% |
| 6 | MI Homes of Raleigh | 1.3 | 1.5 | 99% |
| 7 | Durham County | 1.2 | 2.7 | 35% |
| 8 | Parkwood Association | 1.2 | 2.2 | 84% |
| 9 | Sweetbrier Homeowners Association | 1.1 | 1.1 | 100% |
| 10 | Hope Valley Farms North Homeowners Association | 1.0 | 1.8 | 44% |

### Top owners by missing sidewalk on all streets

| # | Owner | Missing, all streets (mi) | % of their frontage missing |
|--:|---|--:|--:|
| 1 | City of Durham | 25.3 | 57% |
| 2 | Duke University (incl. Health System) | 14.9 | 56% |
| 3 | NC Railroad | 8.1 | 86% |
| 4 | Durham Public Schools | 6.1 | 38% |
| 5 | United States of America | 3.4 | 80% |
| 6 | Hope Valley Country Club | 3.2 | 100% |
| 7 | Durham County | 2.7 | 35% |
| 8 | Durham Housing Authority | 2.6 | 28% |
| 9 | Treyburn Residential Owners Association | 2.5 | 77% |
| 10 | Parkwood Association | 2.2 | 84% |

The site lists the top 100 organizations under each ranking, links each one to its parcels on the map,
and offers the list as a CSV download.

## Method

1. **Data.** Parcels (133,602 polygons), the city's Public Works sidewalk inventory (~11,000 segments) and
   street centerlines with functional class and maintenance responsibility (15,921 segments). All are
   reprojected to NC State Plane (EPSG:2264, US feet).
2. **Scope.** Parcels inside City of Durham limits only, because the sidewalk inventory covers the city alone.
   Stacked condo and leasehold parcels with identical footprints are collapsed into one.
3. **Frontage.** Each parcel boundary is cut into 10 ft pieces. A piece is *street frontage* if
   - it is **not shared** with another parcel (within 1.5 ft), so it borders the public right-of-way gap
     in the parcel map, and
   - it lies within **75 ft of a public street centerline**. Interstates, freeways, ramps, alleys and
     private drives are excluded.

   This leaves out rear and side lot lines. A typical single-family lot gets 72 ft of frontage (median).
4. **Sidewalk coverage.** A frontage piece is covered if a sidewalk line lies within **25 ft**. Sensitivity:
   coverage is 30.6% at 25 ft and 31.8% at 35 ft. Beyond about 45 ft the buffer starts catching sidewalks
   on the far side of the street.
5. **Street class.** Each frontage piece is tagged by its nearest street: *busy* (collector or arterial),
   *local*, or *pending* (new subdivision streets the city has not yet accepted). Pending frontage is
   reported separately and left out of the rankings. Its sidewalks are usually required but not yet in the
   inventory, and counting it made homebuilders look like top offenders.
6. **Owner normalization.** Names are upper-cased, stripped of punctuation and of LLC/INC/CORP suffixes, and
   spelling variants are standardized (ASSOC → ASSOCIATION, HOME OWNERS → HOMEOWNERS). Known institutions are
   aliased together (Duke University + Duke University Health System, the spellings of Durham Public Schools,
   NCDOT, the Housing Authority, etc.). `outputs/mailing_address_groups.csv` also groups owners by mailing
   address. This finds related LLCs, but it also groups HOAs that share a management company.

### Caveats

- The parcel map and the sidewalk inventory don't always line up, so individual parcels can be wrong.
  Treat owner totals as estimates and check specific sites before outreach.
- Some frontage isn't a realistic place for a sidewalk: railroad corridors, creek banks, limited-access roads
  classified as arterials.
- The published site names only organizations. Parcels owned by individuals appear on the map without a name.

## Running it yourself

Requires Python 3.10+.

```bash
pip install -r requirements.txt
python download_data.py          # ~200 MB into data/ (stdlib only; skips files that exist, --force to refresh)
python sidewalk_gaps.py          # analysis -> outputs/ (~5 min, ~4 GB RAM)
python build_site.py             # static site -> site/
python -m http.server -d site    # preview at http://localhost:8000
```

| File | Purpose |
|---|---|
| `download_data.py` | Downloads parcels (ArcGIS Hub GeoPackage), sidewalks and streets (ArcGIS REST, paged) |
| `sidewalk_gaps.py` | Frontage and sidewalk analysis, owner normalization, output tables |
| `build_site.py` | Builds the static site from `outputs/` (owner filtering, map layer, summary stats) |
| `web/index.html` | Site template (Leaflet map + ranked tables) |
| `.github/workflows/pages.yml` | Rebuilds from fresh data and deploys to GitHub Pages on push and monthly |

**Outputs** (`outputs/`, not committed):

- `owners_ranked.csv`: one row per normalized owner, with frontage, missing and busy-street missing (ft),
  the raw name variants merged, and other owners sharing the same mailing address.
- `parcels_frontage.csv`: per-parcel frontage and coverage.
- `mailing_address_groups.csv`: owners grouped by mailing address.
- `frontage.gpkg`: frontage lines flagged by sidewalk and street class, plus parcels, for QGIS.

## Data sources

All from City of Durham / Durham County open data, which may be subject to their own terms of use:

- [Parcels](https://live-durhamnc.opendata.arcgis.com/datasets/da3d194d1e2e4c37afa851b46e29a3f6_0)
- [Sidewalks](https://live-durhamnc.opendata.arcgis.com/datasets/sidewalks-2): Public Works inventory
  ([REST](https://webgis2.durhamnc.gov/server/rest/services/PublicWorksServices/Sidewalks/MapServer/120))
- [Street maintenance responsibility / centerlines](https://services2.arcgis.com/G5vR3cOjh6g2Ed8E/arcgis/rest/services/Street_Maintenance_Responsibility/FeatureServer/0)

Basemap © OpenStreetMap contributors © CARTO.

## License

Code is released under the [MIT License](LICENSE). Data belongs to its publishers.
