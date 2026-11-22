"""Build the candidate queue of places from the thelist-opendata mirror.

A candidate is a freehold property ID (PID) that has a property name in the
address points, a heritage register entry, or a row in data/seeds.csv.

Usage: python3 scripts/build_queue.py <mirror dir> [data dir] [half_km]
"""
import sys
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

D = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "data"
HALF = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
HOBART = (526700, 5252400)  # GDA94 / MGA zone 55

t = pq.read_table(f"{D}/list_parcels_statewide.parquet",
                  columns=["PID", "TENURE_TY", "COMP_AREA", "geometry_bbox"])
p = t.to_pandas()
bb = pd.json_normalize(p.pop("geometry_bbox"))
p["x"] = (bb.xmin + bb.xmax) / 2
p["y"] = (bb.ymin + bb.ymax) / 2
p = p[(p.PID > 0) & (p.TENURE_TY == "Freehold Title")]
p["wx"] = p.x * p.COMP_AREA
p["wy"] = p.y * p.COMP_AREA
g = p.groupby("PID").agg(area_m2=("COMP_AREA", "sum"), titles=("COMP_AREA", "size"),
                         wx=("wx", "sum"), wy=("wy", "sum"))
g["easting"] = (g.wx / g.area_m2).round()
g["northing"] = (g.wy / g.area_m2).round()
g["area_ha"] = (g.area_m2 / 1e4).round(1)
g = g.drop(columns=["wx", "wy", "area_m2"])

a = pq.read_table(f"{D}/list_address_points_statewide.parquet",
                  columns=["PID", "PROP_NAME", "ST_NO_FROM", "STREET", "ST_TYPE", "LOCALITY"]).to_pandas()
a = a.dropna(subset=["PID"])
a["PID"] = a.PID.astype("int64")
named = a.dropna(subset=["PROP_NAME"])
nm = named.groupby("PID").agg(name=("PROP_NAME", lambda s: " / ".join(sorted(set(s)))))
first = a.sort_values("PROP_NAME").drop_duplicates("PID").set_index("PID")
num = first.ST_NO_FROM.fillna(0).astype(int).astype(str).replace("0", "")
addr = (num + " " + first.STREET.fillna("") + " " + first.ST_TYPE.fillna("")).str.strip()
loc = first.LOCALITY

h = pq.read_table(f"{D}/list_heritage_register_statewide.parquet",
                  columns=["THR_ID", "NAME", "PID"]).to_pandas()
h["PID"] = pd.to_numeric(h.PID, errors="coerce")
h = h.dropna(subset=["PID"])
h["PID"] = h.PID.astype("int64")
hh = h.drop_duplicates(["PID", "THR_ID"]).groupby("PID").agg(
    heritage=("NAME", lambda s: " / ".join(sorted(set(map(str, s))))),
    thr_ids=("THR_ID", lambda s: " ".join(str(int(v)) for v in sorted(set(s)))))

seeds = pd.read_csv(f"{OUT}/seeds.csv").set_index("PID")

q = g.join(nm, how="left").join(hh, how="left")
q["address"] = addr.reindex(q.index)
q["locality"] = loc.reindex(q.index)
q["seed"] = q.index.isin(seeds.index)
q = q[q.name.notna() | q.heritage.notna() | q.seed].copy()
q["label"] = seeds.label.reindex(q.index)
q["km_from_hobart"] = (np.hypot(q.easting - HOBART[0], q.northing - HOBART[1]) / 1000).round(1)
q["score"] = (q.area_ha * 0.5 ** (q.km_from_hobart / HALF)).round(1)
q = q.sort_values("score", ascending=False).reset_index()
q.insert(0, "rank", range(1, len(q) + 1))
q = q[["rank", "score", "PID", "name", "label", "heritage", "locality", "address", "area_ha",
       "titles", "km_from_hobart", "thr_ids", "easting", "northing", "seed"]]
q.to_parquet(f"{OUT}/place_queue.parquet", index=False)
print(len(q), "candidates;", int(q.name.notna().sum()), "named;",
      int(q.heritage.notna().sum()), "heritage;", int(q.seed.sum()), "seeds")
