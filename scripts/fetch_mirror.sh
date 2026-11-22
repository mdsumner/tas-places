#!/usr/bin/env bash
# Download the thelist-opendata layers the scripts read into a local mirror dir.
# Usage: scripts/fetch_mirror.sh <mirror dir>
set -euo pipefail
OUT="${1:?mirror dir}"
B="https://data.source.coop/mdsumner/thelist-opendata"
mkdir -p "$OUT"
get() { [ -s "$OUT/$2" ] || curl -fsSL -o "$OUT/$2" "$B/$1"; }
for p in list_parcels list_address_points list_heritage_register list_named_feature_extent \
         list_2d_building_polys list_hydline list_local_govt_areas list_fire_history \
         tasmanian_planning_scheme_zones list_nomenclature_csv; do
  get "geoparquet/$p/statewide/${p}_statewide.parquet" "${p}_statewide.parquet"
done
get "cog/list_dem_25m/statewide/list_dem_25m_statewide.tif" "list_dem_25m_statewide.tif"
ls -la "$OUT"
