"""Extrae de Firebird (solo lectura) a Parquet: una consulta por archivo en etl/<empresa>/queries/.

    python etl/extract.py --config empresas/korner.toml --queries etl/korner/queries \
                          --ini etl/etl.ini --out data/korner/parquet

Reglas (heredadas del extractor original):
  - columnas explicitas, nada de SELECT *; datos personales (RFC, telefonos, correos, domicilios) no se extraen.
  - los decimales se escriben como float64 (pyarrow infiere decimales distintos entre corridas).
  - cada Parquet se escribe a archivo temporal y se renombra: una corrida a medias no deja archivos truncados.
"""
from __future__ import annotations

import argparse
import datetime as dt
import decimal
import os
import re
import sys
import tomllib
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

# dim_kiosko.parquet no sale de Firebird: viene del Excel (etl/load_kioscos.py).
ARCHIVOS_EXTERNOS = {"dim_kiosko"}


def renderizar(sql: str, reglas: dict) -> str:
    conceptos = ", ".join(str(int(c)) for c in reglas.get("conceptos_devolucion", [7972]))   # int(): sin inyeccion
    return sql.replace("{CONCEPTOS_DEVOLUCION}", conceptos)


def parametros(sql: str, desde: dt.date) -> list:
    m = re.match(r"--\s*params:\s*(.*)", sql.strip().splitlines()[0])
    nombres = [p.strip() for p in (m.group(1).split(",") if m else []) if p.strip()]
    valores = {"desde": desde}
    return [valores[n] for n in nombres]


def _normalizar(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, str):
        return v.strip()
    return v


def a_tabla(columnas: list[str], filas: list[tuple]) -> pa.Table:
    cols = {c: [_normalizar(f[i]) for f in filas] for i, c in enumerate(columnas)}
    return pa.table(cols)


def escribir_atomico(tabla: pa.Table, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".parquet.tmp")
    pq.write_table(tabla, tmp)
    os.replace(tmp, destino)


def extraer(cursor, queries: Path, out: Path, reglas: dict, desde: dt.date) -> dict[str, int]:
    resumen = {}
    for archivo in sorted(queries.glob("*.sql")):
        sql = renderizar(archivo.read_text(encoding="utf-8"), reglas)
        cursor.execute(sql, parametros(sql, desde))
        columnas = [d[0].lower() for d in cursor.description]
        filas = cursor.fetchall()
        escribir_atomico(a_tabla(columnas, filas), out / f"{archivo.stem}.parquet")
        resumen[archivo.stem] = len(filas)
        print(f"  {archivo.stem}: {len(filas)} filas")
    return resumen


def main(argv=None):
    from fb import cargar_credenciales, conectar

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--queries", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--ini", type=Path)
    a = ap.parse_args(argv)

    raw = tomllib.loads(a.config.read_text(encoding="utf-8"))
    reglas = raw.get("reglas", {})
    desde = dt.date.fromisoformat(raw.get("etl", {}).get("desde", "2020-01-01"))

    con = conectar(cargar_credenciales(a.ini))
    try:
        resumen = extraer(con.cursor(), a.queries, a.out, reglas, desde)
    finally:
        con.close()
    if not resumen.get("remision_enc"):
        sys.exit("ERROR: remision_enc quedo vacia; no se continua (no se reemplazara la base vigente)")
    faltan = [n for n in ARCHIVOS_EXTERNOS if not (a.out / f"{n}.parquet").exists()]
    if faltan:
        print(f"NOTA: {faltan} no estan aqui; rebuild.sh los toma de data/<empresa>/static/ en la Mac.")
    print("FIN")


if __name__ == "__main__":
    main()
