"""Extraction pass: LIST facts for the selected places.

Selected places are queue rows with both a property name and a heritage entry,
plus every row in data/seeds.csv.

Usage: python3 scripts/extract.py <mirror dir> [data dir] [half_km]
"""
import re
import sys
import warnings
import numpy as np
import pandas as pd
import geopandas as gpd
import pyarrow.parquet as pq
import rasterio
from rasterio.mask import mask

warnings.filterwarnings("ignore")
D = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "data"
HALF = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
EVENT_FIRE_PLACES = 25  # a fire touching more places than this is an event, not a link
SKIP_LINK_TYPES = {"Town", "Unbounded Locality", "Route", "Valley", "Mountains", "Plain", "Forest"}


def gdf(f, cols=None, filt=None):
    t = pq.read_table(f"{D}/{f}.parquet", columns=(cols + ["geometry"]) if cols else None, filters=filt)
    drop = [c for c in ("geometry", "geometry_bbox") if c in t.schema.names]
    return gpd.GeoDataFrame(t.drop(drop).to_pandas(),
                            geometry=gpd.GeoSeries.from_wkb(t.column("geometry").to_pylist()), crs=28355)


def slugify(name, pid):
    s = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return f"{s[:40].strip('-')}-{pid}"


# --- selection
q = pd.read_parquet(f"{OUT}/place_queue.parquet")
q = q[(q.name.notna() & q.heritage.notna()) | q.seed].copy()
q["display_name"] = q.label.fillna(q.name.fillna(q.heritage)).astype(str)
q["display_name"] = q.display_name.where(q.label.notna(), q.display_name.str.title())
q["score"] = (q.area_ha * 0.5 ** (q.km_from_hobart / HALF)).round(1)
q = q.sort_values("score", ascending=False).reset_index(drop=True)
q["rank"] = range(1, len(q) + 1)
q["slug"] = [slugify(n, p) for n, p in zip(q.display_name, q.PID)]
pids = set(q.PID)

# --- place geometry: dissolve freehold titles per PID
par = gdf("list_parcels_statewide", ["PID", "VOLUME", "FOLIO", "COMP_AREA", "TENURE_TY"])
par = par[par.PID.isin(pids) & (par.TENURE_TY == "Freehold Title")]
titles = par.drop(columns="geometry")[["PID", "VOLUME", "FOLIO", "COMP_AREA"]].rename(
    columns={"VOLUME": "volume", "FOLIO": "folio", "COMP_AREA": "area_m2"})
P = par.dissolve("PID")[["geometry"]].reset_index()
P["geometry"] = P.buffer(0)
ll = P.to_crs(4326).representative_point()
P["lon"] = ll.x.round(5)
P["lat"] = ll.y.round(5)
b = P.bounds.round()
P["xmin"], P["ymin"], P["xmax"], P["ymax"] = b.minx, b.miny, b.maxx, b.maxy


def join(layer, how="intersects"):
    return gpd.sjoin(layer, P[["PID", "geometry"]], predicate=how).drop(columns="index_right")


# --- municipality (largest overlap)
lga = gdf("list_local_govt_areas_statewide", ["NAME"]).rename(columns={"NAME": "municipality"})
o = gpd.overlay(P[["PID", "geometry"]], lga, how="intersection")
o["a"] = o.area
P = P.merge(o.sort_values("a").drop_duplicates("PID", keep="last")[["PID", "municipality"]], on="PID", how="left")

# --- buildings (by centroid inside the place)
bl = gdf("list_2d_building_polys_statewide", ["BUILD_TY", "BUILD_NAME", "SHAPE_Area"])
bl["geometry"] = bl.centroid
jb = join(bl, "within")
bs = jb.groupby("PID").agg(
    buildings=("BUILD_TY", "size"),
    residential=("BUILD_TY", lambda s: int((s == "Residential Building").sum())),
    sheds=("BUILD_TY", lambda s: int((s == "Shed").sum())),
    ruins=("BUILD_TY", lambda s: int((s == "Ruin").sum())),
    largest_building_m2=("SHAPE_Area", lambda s: round(s.max())),
    building_names=("BUILD_NAME", lambda s: " / ".join(sorted(set(s.dropna()))) or None)).reset_index()
P = P.merge(bs, on="PID", how="left")

# --- planning zones
zo = gdf("tasmanian_planning_scheme_zones_statewide", ["ZONE"])
oz = gpd.overlay(P[["PID", "geometry"]], zo, how="intersection")
oz["ha"] = oz.area / 1e4
zones = oz.groupby(["PID", "ZONE"]).ha.sum().round(2).reset_index().rename(columns={"ZONE": "zone"})
zones = zones[zones.ha > 0]
mz = zones.sort_values("ha").drop_duplicates("PID", keep="last")[["PID", "zone"]].rename(columns={"zone": "main_zone"})
P = P.merge(mz, on="PID", how="left")

# --- fire history
fi = gdf("list_fire_history_statewide", ["FIRE_ID", "FIRE_NAME", "FIRE_TYPE", "IGN_DATE", "IGN_CAUSE1", "FIRE_AR_HA"])
fi["geometry"] = fi.buffer(0)
of = gpd.overlay(P[["PID", "geometry"]], fi, how="intersection")
of["burnt_ha"] = (of.area / 1e4).round(1)
fires = of[of.burnt_ha >= 0.1].drop(columns="geometry").rename(columns=str.lower).rename(columns={"pid": "PID"})
fires["ign_date"] = fires.ign_date.astype(str).str[:10]
fs = fires.groupby("PID").agg(fires=("fire_id", "nunique"), burnt_ha_sum=("burnt_ha", "sum")).reset_index()
P = P.merge(fs, on="PID", how="left")

# --- named features and named watercourses
nf = gdf("list_named_feature_extent_statewide", ["NAME", "FEAT_TYPE"])
features = join(nf).drop(columns="geometry").rename(
    columns={"NAME": "feature", "FEAT_TYPE": "feature_type"}).drop_duplicates()
features = features[features.feature_type != "Route"]
hy = gdf("list_hydline_statewide", ["NAME"], filt=[("NAME", "!=", "")])
hy = hy[hy.NAME.notna()]
jr = join(hy)
jr["len"] = jr.length
rivers = jr.groupby(["PID", "NAME"]).len.sum().div(1000).round(2).reset_index().rename(
    columns={"NAME": "watercourse", "len": "km_of_segments_touching"})

# --- heritage register (linked by PID, or by register point inside the place)
he = gdf("list_heritage_register_statewide", ["THR_ID", "NAME", "ADDRESS", "PID", "STATUS", "TITLE", "FOLIO"])
he = he.rename(columns={"PID": "her_pid"})
he["her_pid"] = pd.to_numeric(he.her_pid, errors="coerce")
h1 = he[he.her_pid.isin(pids)].assign(PID=lambda d: d.her_pid.astype("int64"), link="pid")
h2 = join(he, "within").assign(link="point")
heritage = pd.concat([h1, h2]).drop(columns=["geometry", "her_pid"]).rename(columns=str.lower).rename(
    columns={"pid": "PID"})
heritage = heritage.sort_values("link").drop_duplicates(["PID", "thr_id"])
heritage["thr_id"] = heritage.thr_id.astype("Int64")

# --- elevation from the 25 m DEM
rows = []
with rasterio.open(f"{D}/list_dem_25m_statewide.tif") as s:
    for pid, geom in zip(P.PID, P.geometry):
        try:
            arr, _ = mask(s, [geom], crop=True, filled=True, nodata=np.nan)
            v = arr[np.isfinite(arr) & (arr > -100)]
            rows.append((pid, round(float(v.min())), round(float(np.median(v))), round(float(v.max())))
                        if v.size else (pid, None, None, None))
        except Exception:
            rows.append((pid, None, None, None))
P = P.merge(pd.DataFrame(rows, columns=["PID", "elev_min_m", "elev_median_m", "elev_max_m"]), on="PID", how="left")

# --- links between places
nb = gpd.sjoin(P[["PID", "geometry"]].assign(geometry=P.buffer(30)), P[["PID", "geometry"]], predicate="intersects")
nb = nb[nb.PID_left < nb.PID_right][["PID_left", "PID_right"]].rename(columns={"PID_left": "PID_a", "PID_right": "PID_b"})
nb["via"] = "adjacent"
nb["detail"] = ""


def shared(df, key, via):
    d = df[["PID", key]].drop_duplicates()
    m = d.merge(d, on=key)
    m = m[m.PID_x < m.PID_y]
    return m.rename(columns={"PID_x": "PID_a", "PID_y": "PID_b", key: "detail"}).assign(via=via)[
        ["PID_a", "PID_b", "via", "detail"]]


fires["fire_key"] = fires.fire_name.fillna("unnamed fire") + " " + fires.ign_date
n_places = fires.groupby("fire_key").PID.nunique()
fires["event"] = fires.fire_key.map(n_places) > EVENT_FIRE_PLACES
link_feats = features[~features.feature_type.isin(SKIP_LINK_TYPES)]
links = pd.concat([nb, shared(rivers, "watercourse", "shared watercourse"),
                   shared(fires[~fires.event], "fire_key", "same fire"),
                   shared(link_feats, "feature", "shared named feature")], ignore_index=True)

# --- write tables
places = q[["rank", "score", "PID", "slug", "display_name", "name", "heritage", "locality", "address",
            "area_ha", "titles", "km_from_hobart", "seed"]].merge(P.drop(columns="geometry"), on="PID", how="left")
wc = rivers.groupby("PID").watercourse.agg(lambda s: " / ".join(sorted(s))).rename("watercourses").reset_index()
places = places.merge(wc, on="PID", how="left")
nl = links.melt(id_vars=["via", "detail"], value_name="PID").groupby("PID").size().rename("links").reset_index()
places = places.merge(nl, on="PID", how="left")
tables = dict(places=places, place_titles=titles, place_zones=zones,
              place_fires=fires.drop(columns="fire_key"), place_features=features,
              place_watercourses=rivers, place_heritage=heritage, place_links=links)
for n, df in tables.items():
    df.to_parquet(f"{OUT}/{n}.parquet", index=False)
    print(n, len(df))
places.to_csv(f"{OUT}/places.csv", index=False)

# --- outlines: full geometry (GeoParquet, MGA55) and a simplified lon/lat GeoJSON for the site maps
G = P.merge(q[["PID", "slug", "display_name", "rank"]], on="PID")[["PID", "slug", "display_name", "rank", "geometry"]]
G.to_parquet(f"{OUT}/place_outlines.parquet")
S = G.copy()
S["geometry"] = S.simplify(15).to_crs(4326).set_precision(0.00001)
S.to_file(f"{OUT}/place_outlines.geojson", driver="GeoJSON")
