import asyncio

import pytest

from microsip_mcp.server import construir_mcp

from microsip_mcp import db
from microsip_mcp.guards import SqlNoPermitido, validar_sql


def q(emp, sql, p=None):
    return db.consultar(emp, sql, p)[1]


def test_fecha_corte(empresa):
    assert str(db.hoy(empresa)) == "2026-10-03"


def test_kiosko_se_resuelve_por_id_nuevo_y_viejo(empresa):
    # RM1 (id nuevo 14109) y RM2 (id viejo 1409) -> mismo kiosko
    filas = q(empresa, "SELECT folio, kiosko_id FROM fact_visita ORDER BY folio")
    d = dict(filas)
    assert d["RM1"] == 14109 and d["RM2"] == 14109 and d["RM3"] == 12067


def test_id_viejo_ambiguo_y_desconocido_quedan_sin_kiosko(empresa):
    d = dict(q(empresa, "SELECT folio, kiosko_id FROM fact_visita"))
    assert d["RM4"] is None and d["RM5"] is None
    malos = {r[0] for r in q(empresa, "SELECT kiosko_raw FROM calidad_kiosko")}
    assert malos == {"54059", "99999"}


def test_remision_cancelada_se_excluye(empresa):
    assert not q(empresa, "SELECT 1 FROM fact_visita WHERE folio='RM6'")
    assert q(empresa, "SELECT ROUND(SUM(importe),2) FROM fact_remision_det")[0][0] == 24.5 + 138 + 49 + 345 + 138 + 73.5 + 172.5


def test_coordenada_cero_es_desconocida(empresa):
    assert q(empresa, "SELECT lat IS NULL, lon IS NULL FROM dim_kiosko WHERE kiosko_id=17005")[0] == (True, True)


def test_devolucion_solo_concepto_7972_y_vendedor_probable(empresa):
    filas = q(empresa, "SELECT folio, vendedor FROM v_devolucion ORDER BY folio")
    assert [f[0] for f in filas] == ["DI1", "DI2"]                  # DI3 es otro concepto
    assert dict(filas) == {"DI1": "VENDEDOR A", "DI2": "VENDEDOR B"}


@pytest.mark.parametrize("malo", [
    "DROP TABLE x", "SELECT 1; SELECT 2", "SELECT * FROM t; DELETE FROM t", "PRAGMA database_list",
    "COPY (SELECT 1) TO 'x.csv'", "SELECT * FROM read_csv('/etc/passwd')", "ATTACH 'x.db'", "", "  ",
    "WITH a AS (SELECT 1) INSERT INTO t SELECT * FROM a",
])
def test_sql_bloqueado(malo):
    with pytest.raises(SqlNoPermitido):
        validar_sql(malo)


def test_sql_permitido_y_comentarios():
    assert validar_sql("SELECT 'a;b' AS x -- coment; drop").startswith("SELECT")
    assert validar_sql("WITH a AS (SELECT last_update FROM t) SELECT * FROM a;")


def test_duckdb_sin_acceso_a_archivos(empresa):
    with pytest.raises(Exception):
        q(empresa, "SELECT * FROM read_csv('/etc/passwd')")


def test_almacen_general_y_cancelada_fuera_pero_facturada_y_pendiente_dentro(empresa):
    folios = {r[0] for r in q(empresa, "SELECT DISTINCT folio FROM fact_visita")}
    assert "RM7" not in folios            # almacen general (id 1): no es camioneta
    assert "RM6" not in folios            # cancelada
    assert {"RM1", "RM2"} <= folios       # P (pendiente) y F (facturada) si cuentan


def test_cambios_7974_no_son_devolucion_ni_venta_pero_si_demanda(empresa):
    assert {r[0] for r in q(empresa, "SELECT folio FROM fact_cambio_det")} == {"DI4"}          # solo el concepto 7974
    assert "DI4" not in {r[0] for r in q(empresa, "SELECT folio FROM fact_devolucion_det")}
    assert q(empresa, "SELECT COUNT(*) FROM fact_remision_det WHERE folio='DI4'")[0][0] == 0   # no es remision: sin ingreso
    # baraja (100): remisiones 6 + cambio 3 - devolucion 1 = 8 piezas en 0-30 d -> 0.5*8/30 por dia
    assert q(empresa, "SELECT u_0_30, ROUND(dem_diaria*30, 2) FROM demanda_ruta WHERE articulo_id = 100")[0] == (8.0, 4.0)
    assert q(empresa, "SELECT vendedor FROM v_cambio")[0][0] == "VENDEDOR A"                    # el que mas vendio ese dia en la camioneta


def test_calidad_datos_reporta_inventario(empresa):
    res = asyncio.run(construir_mcp(empresa).call_tool("calidad_datos", {}))
    out = "\n".join(c.text for c in (res[0] if isinstance(res, tuple) else res))
    assert "existencias en almacen general" in out and "existencias en camionetas" in out


def test_canje_empareja_cambio_con_su_devolucion_por_folio(empresa):
    fila = q(empresa, "SELECT folio_cambio, folio_entrada, con_devolucion, pzas_entregadas, pzas_devueltas, costo_entregado, "
                      "costo_devuelto, costo_neto, vendedor FROM v_canje")[0]
    # DI4 (cambio) -> "Canje folio entrada DI1": entrego 3 pzas ($30) y regreso 1 ($10): costo neto 20
    assert fila == ("DI4", "DI1", True, 3.0, 1.0, 30.0, 10.0, 20.0, "VENDEDOR A")
