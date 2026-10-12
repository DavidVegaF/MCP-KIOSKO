"""Acceso a DuckDB: una conexion de solo lectura por consulta (no bloquea el reemplazo nocturno)."""
from __future__ import annotations

from contextlib import contextmanager

import duckdb

from .config import Empresa


@contextmanager
def conectar(emp: Empresa):
    if not emp.duckdb_path.exists():
        raise FileNotFoundError(f"No existe la base analitica: {emp.duckdb_path}")
    # enable_external_access=False: ni siquiera lectura de archivos locales desde SQL.
    con = duckdb.connect(
        str(emp.duckdb_path),
        read_only=True,
        config={"enable_external_access": False, "autoinstall_known_extensions": False},
    )
    try:
        yield con
    finally:
        con.close()


def consultar(emp: Empresa, sql: str, params: list | None = None, limite: int | None = None):
    """Ejecuta y devuelve (columnas, filas, truncado)."""
    with conectar(emp) as con:
        cur = con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        filas = cur.fetchmany(limite + 1) if limite else cur.fetchall()
    truncado = bool(limite) and len(filas) > limite
    return cols, filas[:limite] if limite else filas, truncado


def hoy(emp: Empresa):
    """Fecha de corte (param.hoy): las ventanas se calculan contra ella, no contra el reloj."""
    _, filas, _ = consultar(emp, "SELECT hoy FROM param")
    return filas[0][0]
