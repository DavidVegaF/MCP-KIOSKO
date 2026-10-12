import pytest

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
