import datetime as dt
import decimal
import sys
from pathlib import Path

import pyarrow.parquet as pq

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "etl"))
import extract  # noqa: E402


class FakeCursor:
    """Imita el cursor de firebird-driver."""
    def __init__(self):
        self.ejecutado = []
    def execute(self, sql, params=()):
        self.ejecutado.append((sql, list(params)))
        self.description = [("DOCTO_VE_ID",), ("FOLIO",), ("PRECIO",)]
    def fetchall(self):
        return [(1, "RM1   ", decimal.Decimal("24.50")), (2, "RM2", decimal.Decimal("10"))]


def test_params_y_render():
    sql = "-- params: desde\nSELECT 1 FROM X WHERE C IN ({CONCEPTOS_DEVOLUCION}) AND F >= ?"
    out = extract.renderizar(sql, {"conceptos_devolucion": [7972, 100]})
    assert "IN (7972, 100)" in out
    assert extract.parametros(out, dt.date(2026, 1, 1)) == [dt.date(2026, 1, 1)]
    assert extract.parametros("-- params:\nSELECT 1", dt.date(2026, 1, 1)) == []


def test_concepto_no_numerico_se_rechaza():
    import pytest
    with pytest.raises(ValueError):
        extract.renderizar("{CONCEPTOS_DEVOLUCION}", {"conceptos_devolucion": ["7972; DROP TABLE X"]})


def test_decimales_a_float_y_trim(tmp_path):
    q = tmp_path / "q"; q.mkdir()
    (q / "remision_enc.sql").write_text("-- params: desde\nSELECT 1 WHERE F >= ?")
    cur = FakeCursor()
    res = extract.extraer(cur, q, tmp_path / "out", {}, dt.date(2026, 1, 1))
    assert res == {"remision_enc": 2}
    t = pq.read_table(tmp_path / "out" / "remision_enc.parquet")
    assert t.column_names == ["docto_ve_id", "folio", "precio"]
    assert str(t.schema.field("precio").type) == "double"
    assert t.column("folio").to_pylist() == ["RM1", "RM2"]
    assert not list((tmp_path / "out").glob("*.tmp"))


def test_queries_del_repo_tienen_encabezado_params():
    for f in (RAIZ / "etl" / "korner" / "queries").glob("*.sql"):
        assert f.read_text().lstrip().startswith("-- params:"), f.name


def test_credenciales_ini_y_env(tmp_path, monkeypatch):
    import pytest
    import fb
    for k in ("FB_DATABASE", "FB_USER", "FB_PASSWORD", "FB_HOST", "FB_CHARSET"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SystemExit):
        fb.cargar_credenciales(None)                     # sin credenciales no arranca
    ini = tmp_path / "etl.ini"
    ini.write_text("﻿[firebird]\nhost = 192.168.1.2\ndatabase = KORNER\nuser = BI_READER\npassword = x\n", encoding="utf-8")
    cfg = fb.cargar_credenciales(ini)                    # BOM utf-8-sig tolerado
    assert cfg["host"] == "192.168.1.2" and cfg["database"] == "KORNER" and cfg["charset"] == "WIN1252"


def test_listas_vacias_no_descartan_todo():
    from microsip_mcp.build import renderizar
    sql = renderizar("{{ESTATUS_EXCLUIDOS}}|{{ALMACENES_EXCLUIDOS}}|{{CONCEPTOS_DEVOLUCION}}", Path("/x"),
                     {"estatus_excluidos": [], "almacenes_excluidos": [], "conceptos_devolucion": []}, "2026-01-01")
    assert sql == "'__NINGUNO__'|-1|-1"
