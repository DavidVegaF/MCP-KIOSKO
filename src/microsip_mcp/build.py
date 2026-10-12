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
        for archivo in ("build.sql", "indicadores.sql"):
            ruta = sql_dir / archivo
            if ruta.exists():
                con.execute(renderizar(ruta.read_text(encoding="utf-8"), parquet, emp.reglas, str(hoy)))
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
