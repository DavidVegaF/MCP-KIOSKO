"""Reconstruye el almacen DuckDB desde los Parquet: archivo nuevo + reemplazo atomico (como el original)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import duckdb

from .config import load_empresa


def _lista_sql(valores, texto: bool) -> str:
    if not valores:                       # NOT IN (NULL) descartaria TODAS las filas: usar un valor imposible
        return "'__NINGUNO__'" if texto else "-1"
    return ", ".join("'" + str(v).replace("'", "''") + "'" if texto else str(int(v)) for v in valores)


def renderizar(plantilla: str, parquet: Path, reglas: dict, hoy: str) -> str:
    sub = {
        "{{PARQUET}}": parquet.as_posix(),
        "{{HOY}}": hoy,
        "{{ESTATUS_EXCLUIDOS}}": _lista_sql(reglas.get("estatus_excluidos", ["C"]), True),
        "{{CONCEPTOS_DEVOLUCION}}": _lista_sql(reglas.get("conceptos_devolucion", [7972]), False),
        "{{CONCEPTOS_CAMBIO}}": _lista_sql(reglas.get("conceptos_cambio", []), False),
        "{{ALMACENES_EXCLUIDOS}}": _lista_sql(reglas.get("almacenes_excluidos", []), False),
        "{{ALMACEN_GENERAL}}": str(int(reglas.get("almacen_general", -1))),
    }
    for k, v in sub.items():
        plantilla = plantilla.replace(k, v)
    if "{{" in plantilla:
        raise ValueError("Quedaron marcadores sin sustituir en el SQL")
    return plantilla


Z_POR_DEFECTO = {"A+": 1.65, "A": 1.28, "B": 0.84, "C": 0.5}       # mismos factores que el MCP de DTODO
CORTES_POR_DEFECTO = [0.20, 0.80, 0.95]                              # A+ 0-20 %, A 20-80 %, B 80-95 %, C 95-100 % de la venta acumulada


def crear_parametros(con, estacionalidad: dict, abc: dict) -> None:
    """Tablas `estacionalidad_mes` y `abc_param` (las lee build.sql y las herramientas)."""
    idx = {int(k): float(v) for k, v in estacionalidad.items()}
    for m, v in idx.items():
        if not 1 <= m <= 12 or not 0.1 <= v <= 5:
            raise ValueError(f"[estacionalidad] mes {m} / indice {v} fuera de rango (mes 1-12, indice 0.1-5)")
    con.execute("CREATE TABLE estacionalidad_mes (mes INTEGER, indice DOUBLE)")
    con.executemany("INSERT INTO estacionalidad_mes VALUES (?, ?)", [(m, idx.get(m, 1.0)) for m in range(1, 13)])
    cortes = [float(c) for c in abc.get("cortes", CORTES_POR_DEFECTO)]
    if len(cortes) != 3 or not (0 < cortes[0] < cortes[1] < cortes[2] < 1):
        raise ValueError("[abc] cortes debe tener 3 valores crecientes entre 0 y 1")
    z = {**Z_POR_DEFECTO, **{k: float(v) for k, v in abc.get("z", {}).items()}}
    con.execute("CREATE TABLE abc_param (clase VARCHAR, orden INTEGER, corte DOUBLE, z DOUBLE)")
    con.executemany("INSERT INTO abc_param VALUES (?, ?, ?, ?)",
                    [("A+", 1, cortes[0], z["A+"]), ("A", 2, cortes[1], z["A"]), ("B", 3, cortes[2], z["B"]), ("C", 4, 1.0, z["C"])])


def construir(config: Path, parquet: Path, sql_dir: Path) -> Path:
    emp = load_empresa(config)
    destino = emp.duckdb_path
    destino.parent.mkdir(parents=True, exist_ok=True)
    nuevo = destino.with_name(destino.stem + ".new.duckdb")
    for f in (nuevo, nuevo.with_name(nuevo.name + ".wal")):
        if f.exists():
            f.unlink()

    con = duckdb.connect(str(nuevo))
    try:
        # Fecha de corte = ultima venta cargada ("hoy" del almacen), igual que param.hoy del original.
        hoy = con.execute(
            f"SELECT MAX(fecha)::DATE FROM read_parquet('{(parquet / 'remision_enc.parquet').as_posix()}')"
        ).fetchone()[0]
        if hoy is None:
            raise RuntimeError("remision_enc.parquet no tiene ventas: no se reemplaza la base vigente")
        crear_parametros(con, emp.estacionalidad, emp.abc)
        for archivo in ("build.sql", "indicadores.sql"):
            ruta = sql_dir / archivo
            if ruta.exists():
                con.execute(renderizar(ruta.read_text(encoding="utf-8"), parquet, emp.reglas, str(hoy)))
        if "almacen_general" not in emp.reglas:
            print("AVISO: falta 'almacen_general = <id>' en [reglas]: las existencias del almacen general NO se clasifican", file=sys.stderr)
        else:
            n = con.execute("SELECT COUNT(*) FROM stock WHERE tipo_almacen = 'general'").fetchone()[0]
            if n == 0:
                print(f"AVISO: ninguna existencia en el almacen general {emp.reglas['almacen_general']}: revisa el id", file=sys.stderr)
        con.execute("CHECKPOINT")
    except Exception:
        con.close()
        raise
    con.close()
    os.replace(nuevo, destino)          # atomico: nadie ve una base a medio armar
    return destino


def main(argv=None):
    ap = argparse.ArgumentParser(description="Arma analitica.duckdb desde los Parquet")
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--parquet", required=True, type=Path)
    ap.add_argument("--sql-dir", required=True, type=Path)
    a = ap.parse_args(argv)
    print("OK", construir(a.config, a.parquet, a.sql_dir))


if __name__ == "__main__":
    sys.exit(main())
