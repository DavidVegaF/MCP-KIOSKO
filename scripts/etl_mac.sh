#!/bin/bash
# Extraccion + reconstruccion de una empresa, DIRECTO desde la Mac (alcanza a Firebird por ZeroTier).
#   scripts/etl_mac.sh korner
# Si algo falla, la base vigente (analitica.duckdb) NO se toca: rebuild.sh solo la reemplaza al terminar bien.
set -uo pipefail
EMP="${1:?uso: etl_mac.sh <empresa>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
LOG="data/$EMP/etl_last_run.log"
mkdir -p "data/$EMP"
{
  echo "==== INICIO $(date '+%F %T') ===="
  rm -rf "data/$EMP/parquet.new"
  if ! .venv/bin/python etl/extract.py --config "empresas/$EMP.toml" --queries "etl/$EMP/queries" \
        --ini etl/etl.ini --out "data/$EMP/parquet.new"; then
    echo "ERROR extract"; echo "==== FIN CON ERROR $(date '+%F %T') ===="; exit 1
  fi
  if ! scripts/rebuild.sh "$EMP"; then
    echo "ERROR rebuild"; echo "==== FIN CON ERROR $(date '+%F %T') ===="; exit 1
  fi
  echo "==== FIN $(date '+%F %T') ===="
} > "$LOG" 2>&1
