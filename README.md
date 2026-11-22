# tas-places

A knowledge base of places in Tasmania, built from open data and sourced history.

Site: https://mdsumner.github.io/tas-places/

## Idea

A place is a property in theLIST cadastre (a property ID, PID). For each place the
repository holds:

- **facts** extracted by script from theLIST open data (titles, area, buildings,
  zones, fire history, elevation, watercourses, heritage entries, links to other places);
- **claims** about its history, one row each, with a source and a link;
- **reports** written for a theme (a reason for asking), which link back to places.

Pages are renderings of the data. As places and claims are added, the pages get richer
and places link to each other.

## Layout

| Path | Holds |
|---|---|
| `data/place_queue.parquet` | every candidate place (named or heritage-registered freehold PIDs), ranked |
| `data/places.parquet`, `places.csv` | one row per extracted place |
| `data/place_*.parquet` | titles, zones, fires, features, watercourses, heritage, links, outlines |
| `data/claims.csv` | sourced history claims, keyed by PID |
| `data/seeds.csv` | places added to the queue by hand |
| `data/reports.csv` | which report covers which places, by theme |
| `scripts/` | `queue.py`, `extract.py`, `build_site.py`, `resolve.py`, `fetch_mirror.sh` |
| `properties/`, `geotech/` | reports, one folder per theme |
| `places/` | generated place pages (not committed) |

## Rebuild the data

Needs Python with pandas, pyarrow, geopandas and rasterio.

```sh
scripts/fetch_mirror.sh mirror          # about 1 GB from the thelist-opendata mirror
python3 scripts/queue.py mirror data    # candidate queue
python3 scripts/extract.py mirror data  # facts for the selected places
```

The ranking score is `area_ha * 0.5 ^ (km_from_hobart / 30)`: larger first, halved for
every 30 km from Hobart. The third argument to both scripts changes the 30.

## Build the site

Needs Quarto, and Python with pandas and pyarrow.

```sh
python3 scripts/build_site.py   # writes places/*.qmd
quarto preview
```

The `Publish site` workflow does this on every push to `main`.

## Add a place or a question

See https://mdsumner.github.io/tas-places/request.html. In short: open a
**Place request** issue, or run the **Place request** workflow with an address.
A workflow replies with the candidates it finds in theLIST data.

## Add a theme

1. Make a folder with an `index.qmd` listing page (copy `geotech/index.qmd`).
2. Add it to the navbar and the `render` list in `_quarto.yml`.
3. Write reports in it, and add a row per report to `data/reports.csv`.

## Rules

- No ownership and no living people, beyond what a cited public source already states.
- Every history claim has a source. Secondary sources are flagged.
- Inference is labelled as inference.

## Data and licence

theLIST open data is (c) State of Tasmania, CC BY 3.0 AU, read through the
thelist-opendata mirror (https://source.coop/mdsumner/thelist-opendata). This project
is not endorsed by Land Tasmania. theLIST is the current, authoritative source.
