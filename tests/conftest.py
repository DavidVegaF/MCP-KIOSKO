"""Fixtures: Parquet sinteticos que imitan los casos reales (id nuevo/viejo, ambiguo, cancelada, 0,0)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from microsip_mcp.build import construir
from microsip_mcp.config import load_empresa

RAIZ = Path(__file__).resolve().parent.parent
D = dt.date


def _w(dirp: Path, nombre: str, cols: dict):
    pq.write_table(pa.table(cols), dirp / f"{nombre}.parquet")


@pytest.fixture(scope="session")
def empresa(tmp_path_factory):
    base = tmp_path_factory.mktemp("korner")
    pqd = base / "parquet"
    pqd.mkdir()
    (base / "empresas").mkdir()
    (base / "empresas" / "korner.toml").write_text(f"""
[empresa]
id = "korner"
nombre = "Grupo Comercial Korner (prueba)"
perfil = "ruta"
[duckdb]
path = "data/korner/analitica.duckdb"
[server]
public_host = "mac.example.ts.net"
token_env = "MCP_TOKEN_KORNER"
[reglas]
estatus_excluidos = ["C"]
conceptos_devolucion = [7972]
""")
    # catalogo de kioscos: 14109 nuevo / viejo 1409; 12067; viejo 54059 repetido (ambiguo); cafeteria 0,0
    _w(pqd, "dim_kiosko", {
        "id_nuevo": [14109, 12067, 54060, 54095, 17005], "id_viejo": [1409, 12067, 54059, 54059, None],
        "nombre": ["14109 TIENDA UNO", "12067 TIENDA DOS", "54060 TIENDA TRES", "54095 TIENDA CUATRO", "17005 CAFETERIA"],
        "tipo": ["Tienda", "Tienda", "Tienda", "Tienda", "Café"], "zona": ["R1", "R1", "R2", "R2", None],
        "zona_k": ["Manzanillo", "Tecoman", "Guzman", "Guzman", None],
        "lat": [19.05, 18.92, 19.6, 19.61, 0.0], "lon": [-104.3, -104.07, -103.4, -103.41, 0.0],
        "domicilio": ["AV. UNO", "CALLE DOS", "TRES", "CUATRO", "CINCO"], "num_ext": ["1", "2", "3", "4", "5"],
        "colonia": ["CENTRO"] * 5, "cp": [28000] * 5, "poblacion": ["MANZANILLO", "TECOMAN", "GUZMAN", "GUZMAN", "COLIMA"],
        "estado": ["COLIMA", "COLIMA", "JALISCO", "JALISCO", "COLIMA"],
    })
    _w(pqd, "dim_almacen", {"almacen_id": [1, 11, 12, 13], "nombre": ["ALMACEN GENERAL", "Camioneta 1", "Camioneta 2", "Camioneta 3"]})
    _w(pqd, "dim_vendedor", {"vendedor_id": [1, 2], "nombre": ["VENDEDOR A", "VENDEDOR B"]})
    _w(pqd, "dim_articulo", {
        "articulo_id": [100, 200, 300], "clave": ["2000112", "2000034", "2002784"],
        "nombre": ["BARAJA ESPAÑOLA", "GLOBO AGUA MAGIC", "SPINNER GRANDE"], "linea": ["JUEGOS", "GLOBOS", "JUGUETES"],
        "grupo": ["G1", "G1", "G2"], "estatus": ["A"] * 3, "es_juego": ["N"] * 3,
    })
    # remisiones: 1) id nuevo 14109, cam 11 VENDEDOR A; 2) id viejo 1409 (= mismo kiosko), cam 11 VENDEDOR A;
    # 3) 12067 cam 12 JAZ; 4) viejo ambiguo 54059 -> sin kiosko; 5) id desconocido 99999; 6) CANCELADA (excluida)
    _w(pqd, "remision_enc", {
        "docto_ve_id": [1, 2, 3, 4, 5, 6], "folio": ["RM1", "RM2", "RM3", "RM4", "RM5", "RM6"],
        "fecha": [D(2026, 10, 1), D(2026, 10, 2), D(2026, 10, 2), D(2026, 10, 3), D(2026, 10, 3), D(2026, 10, 3)],
        "hora": [dt.time(9, 0)] * 6, "estatus": ["N", "N", "N", "N", "N", "C"],
        "almacen_id": [11, 11, 12, 11, 12, 11], "vendedor_id": [1, 1, 2, 1, 2, 1],
        "orden_compra": ["14109-1-3-2236", "1409-2-3-100", "12067-2-3-7464", "54059-1-3-5", "99999-1-3-9", "14109-1-3-1"],
    })
    _w(pqd, "remision_det", {
        "docto_ve_id": [1, 1, 2, 3, 3, 4, 5, 6], "articulo_id": [100, 200, 100, 200, 300, 100, 300, 100],
        "unidades": [1.0, 4.0, 2.0, 10.0, 4.0, 3.0, 5.0, 99.0],
        "precio_unitario": [24.5, 34.5, 24.5, 34.5, 34.5, 24.5, 34.5, 24.5],
        "precio_total_neto": [24.5, 138.0, 49.0, 345.0, 138.0, 73.5, 172.5, 2425.5],
    })
    _w(pqd, "doctos_in_enc", {
        "docto_in_id": [10, 11, 12], "folio": ["DI1", "DI2", "DI3"],
        "fecha": [D(2026, 10, 2), D(2026, 10, 3), D(2026, 10, 3)], "almacen_id": [11, 12, 11],
        "concepto_in_id": [7972, 7972, 123], "cancelado": ["N", "N", "N"], "descripcion": ["dev kiosko", "dev", "otro"],
    })
    _w(pqd, "doctos_in_det", {
        "docto_in_id": [10, 11, 12], "articulo_id": [100, 200, 100], "unidades": [1.0, 2.0, 50.0], "costo_total": [10.0, 20.0, 500.0],
    })
    construir(base / "empresas" / "korner.toml", pqd, RAIZ / "sql" / "korner")
    return load_empresa(base / "empresas" / "korner.toml")
