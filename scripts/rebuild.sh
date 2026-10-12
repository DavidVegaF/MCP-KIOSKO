#!/bin/bash
# En la Mac: arma la base nueva desde data/<empresa>/parquet.new y la reemplaza de forma atomica.
# Si algo falla, la base vigente (analitica.duckdb) NO se toca.
set -euo pipefail
EMP="${1:?uso: rebuild.sh <empresa>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# Archivos que no salen de Firebird (ej. dim_kiosko.parquet, del Excel de kioscos) viven fijos en static/
for f in "data/$EMP/static/"*.parquet; do
  [ -e "$f" ] || continue
  [ -f "data/$EMP/parquet.new/$(basename "$f")" ] || cp "$f" "data/$EMP/parquet.new/"
done
"$ROOT/.venv/bin/python" -m microsip_mcp.build \
  --config "empresas/$EMP.toml" --parquet "data/$EMP/parquet.new" --sql-dir "sql/$EMP"
rm -rf "data/$EMP/parquet.old"
[ -d "data/$EMP/parquet" ] && mv "data/$EMP/parquet" "data/$EMP/parquet.old"
mv "data/$EMP/parquet.new" "data/$EMP/parquet"
echo "FIN $EMP $(date '+%F %T')"
