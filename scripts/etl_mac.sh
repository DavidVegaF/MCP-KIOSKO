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
  # Si el enlace con Firebird (ZeroTier) falla, reintenta: INTENTOS veces, ESPERA segundos entre intentos.
  ok=0
  for i in $(seq 1 "${INTENTOS:-6}"); do
    rm -rf "data/$EMP/parquet.new"
    if .venv/bin/python etl/extract.py --config "empresas/$EMP.toml" --queries "etl/$EMP/queries" \
          --ini etl/etl.ini --out "data/$EMP/parquet.new"; then ok=1; break; fi
    echo "ERROR extract (intento $i de ${INTENTOS:-6}) $(date '+%F %T')"
    [ "$i" -lt "${INTENTOS:-6}" ] && sleep "${ESPERA:-600}"
  done
  if [ "$ok" -ne 1 ]; then
    echo "ERROR extract"; echo "==== FIN CON ERROR $(date '+%F %T') ===="; exit 1
  fi
  if ! scripts/rebuild.sh "$EMP"; then
    echo "ERROR rebuild"; echo "==== FIN CON ERROR $(date '+%F %T') ===="; exit 1
  fi
  echo "==== FIN $(date '+%F %T') ===="
} > "$LOG" 2>&1
