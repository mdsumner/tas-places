"""Generate the place pages and the places index from the data tables.

A place gets a page when it has a claim in data/claims.csv, a report in
data/reports.csv, or a row in data/seeds.csv. Generated files go to places/
and are not committed; the publish workflow runs this before quarto render.

Usage: python3 scripts/build_site.py
"""
import json
import os
import pandas as pd

D = "data"
os.makedirs("places", exist_ok=True)
places = pd.read_parquet(f"{D}/places.parquet")
titles = pd.read_parquet(f"{D}/place_titles.parquet")
zones = pd.read_parquet(f"{D}/place_zones.parquet")
fires = pd.read_parquet(f"{D}/place_fires.parquet")
feats = pd.read_parquet(f"{D}/place_features.parquet")
rivers = pd.read_parquet(f"{D}/place_watercourses.parquet")
heritage = pd.read_parquet(f"{D}/place_heritage.parquet")
links = pd.read_parquet(f"{D}/place_links.parquet")
claims = pd.read_csv(f"{D}/claims.csv", dtype={"year": "Int64"})
holders = pd.read_csv(f"{D}/holders.csv", dtype={"from_year": "Int64", "to_year": "Int64"})
reports = pd.read_csv(f"{D}/reports.csv", dtype=str).fillna("")
seeds = pd.read_csv(f"{D}/seeds.csv")
outlines = {f["properties"]["PID"]: f for f in json.load(open(f"{D}/place_outlines.geojson"))["features"]}

rep_pids = {}
for _, r in reports.iterrows():
    for pid in r.pids.split():
        rep_pids.setdefault(int(pid), []).append(r)
featured = set(claims.PID) | set(holders.PID) | set(rep_pids) | set(seeds.PID)
featured &= set(places.PID)
P = places.set_index("PID")


def num(v, nd=0, unit=""):
    if pd.isna(v):
        return "not recorded"
    s = f"{v:,.{nd}f}"
    return f"{s} {unit}".strip()


def esc(s):
    return str(s).replace("|", "/").replace("\n", " ")


def place_ref(pid):
    name = P.display_name.get(pid, str(pid))
    if pid in featured:
        return f"[{name}]({P.slug[pid]}.qmd)"
    return f"{name} (PID {pid})"


def map_block(pid):
    near = {pid}
    l = links[(links.PID_a == pid) | (links.PID_b == pid)]
    near |= set(l.PID_a) | set(l.PID_b)
    fc = {"type": "FeatureCollection", "features": []}
    for n in near:
        if n in outlines:
            f = dict(outlines[n])
            f["properties"] = dict(f["properties"], focus=(n == pid), page=(P.slug[n] + ".html") if n in featured else "")
            fc["features"].append(f)
    return ("```{=html}\n<div id=\"place-map\" class=\"place-map\"></div>\n<script>\n"
            "window.addEventListener('load', function () { tasPlacesMap('place-map', "
            + json.dumps(fc, separators=(",", ":")) + "); });\n</script>\n```\n")


def page(pid):
    r = P.loc[pid]
    out = []
    themes = sorted({x.theme for x in rep_pids.get(pid, [])})
    cats = [str(r.municipality)] + themes
    out.append("---")
    out.append(f"title: \"{r.display_name}\"")
    out.append(f"subtitle: \"{str(r.locality).title() if pd.notna(r.locality) else 'Locality not recorded'}, {r.municipality}\"")
    out.append(f"categories: [{', '.join(cats)}]")
    out.append(f"area_ha: {r.area_ha}")
    out.append(f"km_from_hobart: {r.km_from_hobart}")
    out.append(f"pid: {pid}")
    out.append("---\n")
    out.append(map_block(pid))
    out.append("Orange is this place; blue outlines are connected places. Click an outline for its name.\n")

    out.append("## At a glance\n")
    rows = [("Property ID (PID)", str(pid)),
            ("LIST property name", r["name"] if pd.notna(r["name"]) else "none in the address points"),
            ("Address", r.address if pd.notna(r.address) and str(r.address).strip() else "not recorded"),
            ("Area", f"{num(r.area_ha, 1, 'ha')} in {int(r.titles)} freehold title(s)"),
            ("Distance from Hobart", num(r.km_from_hobart, 1, "km")),
            ("Location", f"{r.lat}, {r.lon} (representative point)"),
            ("Elevation", f"{num(r.elev_min_m)} to {num(r.elev_max_m)} m, median {num(r.elev_median_m)} m"
             if pd.notna(r.elev_min_m) else "not recorded"),
            ("Buildings mapped", f"{num(r.buildings)}: {num(r.residential)} residential, {num(r.sheds)} sheds, {num(r.ruins)} ruin(s)"
             if pd.notna(r.buildings) else "none mapped"),
            ("Main planning zone", r.main_zone if pd.notna(r.main_zone) else "not recorded"),
            ("Queue rank", f"{int(r['rank'])} of {len(places)}")]
    out.append("| | |\n|---|---|")
    out += [f"| {a} | {esc(b)} |" for a, b in rows]
    out.append("")

    rp = rep_pids.get(pid, [])
    if rp:
        out.append("## Reports\n")
        out += [f"- [{x.title}](../{x.path}) ({x.theme})" for x in rp]
        out.append("")

    h = heritage[heritage.PID == pid]
    if len(h):
        out.append("## Heritage register\n")
        out.append("| THR ID | Name | Address | Status |\n|---|---|---|---|")
        out += [f"| {x.thr_id} | {esc(x['name'])} | {esc(x.address)} | {esc(x.status)} |" for _, x in h.iterrows()]
        out.append("")

    c = claims[claims.PID == pid].sort_values("year", na_position="last")
    out.append("## History\n")
    if len(c):
        out.append("Each row is one sourced claim from `data/claims.csv`. Notes flag secondary sources and disagreements.\n")
        out.append("| Year | Subject | Claim | Source |\n|---|---|---|---|")
        for _, x in c.iterrows():
            note = f" *{esc(x.note)}*" if pd.notna(x.note) else ""
            yr = "" if pd.isna(x.year) else int(x.year)
            out.append(f"| {yr} | {esc(x.subject)} | {esc(x.claim)}{note} | [{esc(x.source)}]({x.source_url}) |")
    else:
        out.append("No sourced history has been added yet. See [how to request an addition](../request.qmd).")
    out.append("")

    hd = holders[holders.PID == pid].sort_values(["from_year", "to_year"], na_position="last")
    if len(hd):
        out.append("## Holders over time\n")
        out.append("Historical holders from published sources, one sourced row each (`data/holders.csv`). "
                   "This table does not say who holds the place now. See [families](../families.qmd) for links between places.\n")
        out.append("| From | To | Holder | Role | Subject | Source |\n|---|---|---|---|---|---|")
        for _, x in hd.iterrows():
            fy = "" if pd.isna(x.from_year) else int(x.from_year)
            ty = "" if pd.isna(x.to_year) else int(x.to_year)
            note = f" *{esc(x.note)}*" if pd.notna(x.note) else ""
            out.append(f"| {fy} | {ty} | {esc(x.holder)} | {esc(x.role)}{note} | {esc(x.subject)} | [{esc(x.source)}]({x.source_url}) |")
        out.append("")

    l = links[(links.PID_a == pid) | (links.PID_b == pid)].copy()
    if len(l):
        l["other"] = l.PID_b.where(l.PID_a == pid, l.PID_a)
        out.append("## Connected places\n")
        for other, g in l.groupby("other"):
            why = "; ".join(sorted({(v.via + (f" ({v.detail})" if v.detail else "")) for _, v in g.iterrows()}))
            out.append(f"- {place_ref(int(other))}: {why}")
        out.append("")

    w = rivers[rivers.PID == pid]
    f = feats[feats.PID == pid]
    if len(w) or len(f):
        out.append("## Watercourses and named features\n")
        if len(w):
            out.append("**Named watercourses:** " + ", ".join(sorted(w.watercourse)) + ".\n")
        if len(f):
            out.append("**LIST named features:** " + ", ".join(f"{x.feature} ({x.feature_type.lower()})" for _, x in f.sort_values("feature").iterrows()) + ".\n")

    fi = fires[fires.PID == pid].sort_values("ign_date")
    if len(fi):
        out.append("## Fire history\n")
        out.append("| Ignition date | Fire | Type | Burnt on this place (ha) |\n|---|---|---|---|")
        out += [f"| {x.ign_date if x.ign_date != 'NaT' else 'not recorded'} | {esc(x.fire_name) if pd.notna(x.fire_name) else 'unnamed'} | {esc(x.fire_type)} | {x.burnt_ha} |" for _, x in fi.iterrows()]
        out.append("")

    z = zones[zones.PID == pid].sort_values("ha", ascending=False)
    if len(z):
        out.append("## Planning zones\n")
        out += [f"- {x.zone}: {x.ha:,.1f} ha" for _, x in z.iterrows()]
        out.append("")

    t = titles[titles.PID == pid].sort_values("area_m2", ascending=False)
    out.append("## Titles\n")
    out.append(", ".join(f"{x.volume}/{int(x.folio) if pd.notna(x.folio) else '?'} ({x.area_m2 / 1e4:,.1f} ha)" for _, x in t.iterrows()) + ".\n")
    s = seeds[seeds.PID == pid]
    if len(s):
        out.append(f"::: {{.callout-note}}\nAdded by hand to the queue: {s.note.iloc[0]}\n:::\n")
    out.append("*Facts are extracted from theLIST open data (c) State of Tasmania, CC BY 3.0 AU, via the thelist-opendata mirror. "
               "A place here is a property ID, which can group several titles. Ownership is not recorded.*")
    open(f"places/{r.slug}.qmd", "w").write("\n".join(out) + "\n")


for pid in sorted(featured):
    page(pid)

# --- places index: map of everything, listing of place pages, top of the queue
pts = [{"n": r.display_name, "x": r.lon, "y": r.lat, "p": (r.slug + ".html") if r.PID in featured else "", "r": int(r["rank"])}
       for _, r in places.dropna(subset=["lon"]).iterrows()]
fc = {"type": "FeatureCollection", "features": []}
for pid in sorted(featured):
    f = dict(outlines[pid])
    f["properties"] = dict(f["properties"], focus=True, page=P.slug[pid] + ".html")
    fc["features"].append(f)
idx = ["---", "title: Places", "listing:", "  id: place-listing", "  contents: \"*.qmd\"", "  type: table", "  sort: \"title\"",
       "  fields: [title, subtitle, area_ha, km_from_hobart, categories]",
       "  field-display-names:", "    subtitle: Locality", "    area_ha: Area (ha)", "    km_from_hobart: km from Hobart",
       "  filter-ui: true", "---\n",
       f"Every place is a property ID in theLIST cadastre. {len(places)} places have extracted facts; "
       f"{len(featured)} have a page so far (orange outlines). Dots are the rest of the queue.\n",
       "```{=html}\n<div id=\"all-map\" class=\"place-map tall\"></div>\n<script>\nwindow.addEventListener('load', function () { tasPlacesMap('all-map', "
       + json.dumps(fc, separators=(",", ":")) + ", " + json.dumps(pts, separators=(",", ":")) + "); });\n</script>\n```\n",
       "## Places with a page\n", ":::{#place-listing}\n:::\n",
       "## Next in the queue\n",
       "Ranked by area, halved for every 30 km from Hobart. The full table is `data/places.csv` in the repository.\n",
       "| Rank | Place | Locality | Municipality | Area (ha) | km from Hobart |\n|---|---|---|---|---|---|"]
for _, r in places.sort_values("rank").head(40).iterrows():
    nm = f"[{r.display_name}]({r.slug}.qmd)" if r.PID in featured else r.display_name
    idx.append(f"| {int(r['rank'])} | {nm} | {str(r.locality).title() if pd.notna(r.locality) else ''} | {r.municipality} | {r.area_ha:,.1f} | {r.km_from_hobart} |")
open("places/index.qmd", "w").write("\n".join(idx) + "\n")
# --- families page: holders grouped by family name, linking places
fm = ["---", "title: Families and holders", "---\n",
      "Historical holders of places, grouped by family name, from `data/holders.csv`. Every row has a source on the place page. "
      "A family appearing at more than one place is a link between those places.\n",
      "This page records history from published sources. It does not say who holds any place now, "
      "and it leaves out living people.\n"]
for family, g in sorted(holders.groupby("family"), key=lambda kv: (-kv[1].PID.nunique(), kv[0])):
    n = g.PID.nunique()
    fm.append(f"## {family}\n")
    fm.append(f"{n} place{'s' if n > 1 else ''}.\n")
    fm.append("| From | To | Holder | Role | Place |\n|---|---|---|---|---|")
    for _, x in g.sort_values(["from_year", "to_year"], na_position="last").iterrows():
        fy = "" if pd.isna(x.from_year) else int(x.from_year)
        ty = "" if pd.isna(x.to_year) else int(x.to_year)
        ref = f"[{P.display_name[x.PID]}](places/{P.slug[x.PID]}.qmd)" if x.PID in featured else str(x.PID)
        fm.append(f"| {fy} | {ty} | {esc(x.holder)} | {esc(x.role)} | {ref} ({esc(x.subject)}) |")
    fm.append("")
open("families.qmd", "w").write("\n".join(fm) + "\n")
print("wrote", len(featured), "place pages")
