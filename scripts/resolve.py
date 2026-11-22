"""Resolve a place name, address or property ID against theLIST open data.

Prints a Markdown summary of candidates: named properties, heritage entries,
street addresses and gazetteer names. Used by the Place request workflow.

Usage: python3 scripts/resolve.py "<query>" [mirror dir]
With no mirror dir, the three small layers it needs are downloaded to a temp dir.
"""
import os
import re
import sys
import tempfile
import urllib.request
import pandas as pd
import pyarrow.parquet as pq

BASE = "https://data.source.coop/mdsumner/thelist-opendata/geoparquet"
LAYERS = ["list_address_points", "list_heritage_register", "list_nomenclature_csv"]
TYPES = {"ST": "STREET", "RD": "ROAD", "AV": "AVENUE", "AVE": "AVENUE", "HWY": "HIGHWAY", "CT": "COURT",
         "PL": "PLACE", "DR": "DRIVE", "CRES": "CRESCENT", "LA": "LANE", "TCE": "TERRACE", "PDE": "PARADE"}
TYPE_WORDS = set(TYPES.values()) | {"LANE", "WAY", "CLOSE", "GROVE", "ESPLANADE", "CIRCLE", "RISE", "BOULEVARD"}
MAX_ROWS = 15


def load(mirror):
    out = {}
    for n in LAYERS:
        f = os.path.join(mirror, f"{n}_statewide.parquet")
        if not os.path.exists(f):
            urllib.request.urlretrieve(f"{BASE}/{n}/statewide/{n}_statewide.parquet", f)
        t = pq.read_table(f)
        out[n] = t.drop([c for c in ("geometry", "geometry_bbox") if c in t.schema.names]).to_pandas()
    return out


def table(df, cols):
    if not len(df):
        return "None found.\n"
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.head(MAX_ROWS).iterrows():
        lines.append("| " + " | ".join("" if pd.isna(r[c]) else str(r[c]).replace("|", "/") for c in cols) + " |")
    if len(df) > MAX_ROWS:
        lines.append(f"\n({len(df) - MAX_ROWS} more not shown.)")
    return "\n".join(lines) + "\n"


def main():
    raw = sys.argv[1].strip()[:200]
    mirror = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp()
    q = re.sub(r"[^A-Z0-9' ]+", " ", raw.upper()).strip()
    toks = [TYPES.get(t, t) for t in q.split()]
    L = load(mirror)
    a, h, g = L["list_address_points"], L["list_heritage_register"], L["list_nomenclature_csv"]
    queue = pd.read_parquet("data/place_queue.parquet")[["PID", "area_ha", "titles", "km_from_hobart", "rank"]]
    known = set(pd.read_parquet("data/places.parquet").PID)
    out = [f"## Candidates for: {q.title()}\n"]

    if q.isdigit() and len(q) >= 6:  # a property ID
        pid = int(q)
        ap = a[a.PID == pid]
    else:
        ap = a[a.PROP_NAME.fillna("").str.upper().str.contains(re.escape(q), regex=True)]
    ap = ap.dropna(subset=["PID"]).copy()
    ap["PID"] = ap.PID.astype("int64")
    props = ap.sort_values("PROP_NAME").drop_duplicates("PID").merge(queue, on="PID", how="left")
    props["address"] = (props.ST_NO_FROM.fillna(0).astype(int).astype(str).replace("0", "") + " " +
                        props.STREET.fillna("") + " " + props.ST_TYPE.fillna("")).str.strip()
    props["in_knowledge_base"] = props.PID.isin(known).map({True: "yes", False: "no"})
    out.append("### Named properties (address points)\n")
    out.append(table(props, ["PROP_NAME", "address", "LOCALITY", "PID", "area_ha", "titles", "km_from_hobart", "in_knowledge_base"]))

    hm = h[h.NAME.fillna("").str.upper().str.contains(re.escape(q), regex=True)] if not q.isdigit() else h[h.PID.astype(str).str.replace(".0", "", regex=False) == q]
    out.append("### Heritage register\n")
    out.append(table(hm, ["THR_ID", "NAME", "ADDRESS", "PID", "STATUS"]))

    ti = next((i for i, t in enumerate(toks) if t in TYPE_WORDS), None)
    if toks and toks[0].isdigit() and len(toks[0]) < 6 and len(toks) > 1:
        street = toks[1:ti] if ti else toks[1:2]
        wanted_loc = " ".join(toks[ti + 1:]) if ti else ""
        sm = a[(a.ST_NO_FROM == float(toks[0])) & (a.STREET.fillna("").str.upper() == " ".join(street))].copy()
        if len(sm):
            sm["PID"] = sm.PID.astype("Int64")
            grp = sm.groupby(["ST_NO_FROM", "STREET", "ST_TYPE", "LOCALITY"]).agg(
                address_points=("PID", "size"), property_ids=("PID", lambda s: ", ".join(str(v) for v in sorted(set(s.dropna()))[:6])),
                easting=("EASTING", "mean"), northing=("NORTHING", "mean")).reset_index()
            grp["easting"] = grp.easting.round().astype(int)
            grp["northing"] = grp.northing.round().astype(int)
            grp["ST_NO_FROM"] = grp.ST_NO_FROM.astype(int)
            out.append("### Street addresses\n")
            out.append(table(grp, ["ST_NO_FROM", "STREET", "ST_TYPE", "LOCALITY", "address_points", "property_ids", "easting", "northing"]))
            locs = set(grp.LOCALITY)
            if wanted_loc and wanted_loc not in locs:
                out.append(f"Note: theLIST has this address in {', '.join(sorted(locs)).title()}, not {wanted_loc.title()}.\n")
            if (grp.address_points > 1).any():
                out.append("Several address points at one address usually means strata units.\n")
        else:
            out.append("### Street addresses\n\nNone found. Check the street name and number.\n")

    if not q.isdigit():
        gm = g[g.FEAT_NAME.fillna("").str.upper().str.contains(re.escape(q), regex=True)]
        out.append("### Gazetteer names\n")
        out.append(table(gm, ["FEAT_NAME", "FEAT_TYPE", "MUNY", "LATITUDE", "LONGITUDE"]))

    out.append("Reply on this issue with the candidate you mean (the property ID is the clearest), or correct the search.\n")
    out.append("*Searched theLIST open data (c) State of Tasmania, CC BY 3.0 AU, via the thelist-opendata mirror. "
               "Coordinates are GDA94 / MGA zone 55.*")
    print("\n".join(out))


if __name__ == "__main__":
    main()
