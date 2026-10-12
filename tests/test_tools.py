import asyncio
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from microsip_mcp.server import construir_app, construir_mcp

TOKEN = "t" * 40


def texto(res) -> str:
    return "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")


async def llamar(emp, nombre, **args):
    res = await construir_mcp(emp).call_tool(nombre, args)
    # FastMCP devuelve (contenido, estructurado) o lista segun la version
    contenido = res[0] if isinstance(res, tuple) else res
    return "\n".join(c.text for c in contenido)


def run(coro):
    return asyncio.run(coro)


def test_herramientas_registradas(empresa):
    nombres = {t.name for t in run(construir_mcp(empresa).list_tools())}
    assert nombres == {"diccionario", "ventas", "ranking_camionetas", "ranking_vendedores", "productos_ruta",
                       "devoluciones_ruta", "kiosko_geolocalizar", "visitas", "articulo", "calidad_datos", "sql",
                       "existencias", "sugerido_compra", "sin_movimiento", "stock_camioneta"}


def test_ventas_por_camioneta(empresa):
    out = run(llamar(empresa, "ventas", agrupar_por="camioneta", desde="2026-10-01", hasta="2026-10-03"))
    assert "Camioneta 1" in out and "Camioneta 2" in out
    # Camioneta 1: RM1 (162.5) + RM2 (49) + RM4 (73.5) = 285.00 ; RM6 cancelada no cuenta
    assert "285.00" in out


def test_ranking_vendedores_y_camionetas(empresa):
    v = run(llamar(empresa, "ranking_vendedores", desde="2026-10-01", hasta="2026-10-03"))
    assert "VENDEDOR A" in v and "VENDEDOR B" in v
    c = run(llamar(empresa, "ranking_camionetas", desde="2026-10-01", hasta="2026-10-03"))
    assert "Camioneta 1" in c and "pct_total" in c


def test_productos_ruta_orden(empresa):
    out = run(llamar(empresa, "productos_ruta", desde="2026-10-01", hasta="2026-10-03", ordenar_por="unidades"))
    primera = [l for l in out.splitlines() if l.startswith("| 2000")][0]
    assert "2000034" in primera           # globos: 4 + 10 = 14 piezas


def test_devoluciones_con_porcentaje(empresa):
    out = run(llamar(empresa, "devoluciones_ruta", desde="2026-10-01", hasta="2026-10-03", agrupar_por="articulo"))
    assert "2000034" in out and "pct_devuelto" in out
    lineas = {l.split("|")[1].strip(): l for l in out.splitlines() if l.startswith("| 2000")}
    assert "16.7" in lineas["2000112 BARAJA ESPAÑOLA"]            # devuelve 1 de 6 vendidas
    assert "14.3" in lineas["2000034 GLOBO AGUA MAGIC"]           # devuelve 2 de 14 vendidas


def test_geolocalizar_por_id_viejo_y_nombre(empresa):
    a = run(llamar(empresa, "kiosko_geolocalizar", kiosko="1409"))
    b = run(llamar(empresa, "kiosko_geolocalizar", kiosko="uno"))
    for out in (a, b):
        assert "14109 TIENDA UNO" in out and "google.com/maps?q=19.05,-104.3" in out
    assert "| 2 |" in a                                     # 2 remisiones (RM1 id nuevo + RM2 id viejo)


def test_geolocalizar_sin_coordenadas(empresa):
    out = run(llamar(empresa, "kiosko_geolocalizar", kiosko="cafeteria"))
    assert "17005 CAFETERIA" in out and "google.com" not in out


def test_visitas_por_folio_busca_todo_el_historial(empresa):
    out = run(llamar(empresa, "visitas", folio="rm3"))
    assert "12067 TIENDA DOS" in out and "18.92" in out


def test_articulo_y_calidad(empresa):
    assert "BARAJA" in run(llamar(empresa, "articulo", busqueda="baraja"))
    out = run(llamar(empresa, "calidad_datos"))
    assert "54059" in out and "99999" in out


def test_sql_tool(empresa):
    out = run(llamar(empresa, "sql", consulta="SELECT COUNT(*) AS n FROM fact_visita"))
    assert "| 5 |" in out
    with pytest.raises(Exception):
        run(llamar(empresa, "sql", consulta="DROP TABLE param"))


def test_fecha_invalida(empresa):
    with pytest.raises(Exception, match="AAAA-MM-DD"):
        run(llamar(empresa, "ventas", desde="01/10/2026"))


def test_diccionario(empresa):
    out = run(llamar(empresa, "diccionario"))
    assert "7972" in out and "2026-10-03" in out and "Las facturas no se cuentan" in out


# ---------------------------------------------------------------- HTTP de punta a punta
@pytest.fixture()
def servidor(empresa, monkeypatch):
    monkeypatch.setenv(empresa.token_env, TOKEN)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); puerto = s.getsockname()[1]; s.close()
    cfg = uvicorn.Config(construir_app(empresa), host="127.0.0.1", port=puerto, log_level="error", access_log=False)
    srv = uvicorn.Server(cfg)
    th = threading.Thread(target=srv.run, daemon=True); th.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{puerto}"
    srv.should_exit = True; th.join(5)


def test_http_token_correcto_incorrecto_y_health(servidor):
    assert httpx.get(f"{servidor}/health").status_code == 200
    assert httpx.post(f"{servidor}/mcp").status_code == 404                       # sin token
    assert httpx.post(f"{servidor}/{'x'*40}/mcp").status_code == 404               # token malo


def test_http_cliente_mcp_real(servidor):
    async def go():
        async with streamablehttp_client(f"{servidor}/{TOKEN}/mcp") as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = await s.list_tools()
                res = await s.call_tool("ranking_camionetas", {"desde": "2026-10-01", "hasta": "2026-10-03"})
                return len(tools.tools), texto(res)
    n, out = run(go())
    assert n == 15 and "Camioneta 1" in out


def test_http_host_publico_permitido_y_host_ajeno_rechazado(servidor):
    h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
    ok = httpx.post(f"{servidor}/{TOKEN}/mcp", json=body, headers={**h, "Host": "mac.example.ts.net"})
    mal = httpx.post(f"{servidor}/{TOKEN}/mcp", json=body, headers={**h, "Host": "evil.example.com"})
    assert ok.status_code == 200 and mal.status_code in (400, 421)


def test_existencias_general_camioneta_y_cobertura(empresa):
    out = run(llamar(empresa, "existencias", articulo="baraja"))
    fila = [l for l in out.splitlines() if l.startswith("| 2000112")][0]
    assert "| 100.00 |" in fila and "| 5.00 |" in fila and "| 105.00 |" in fila and "| 10.00 |" in fila   # general, camioneta, total, en camino


def test_sugerido_compra_formula(empresa):
    out = run(llamar(empresa, "sugerido_compra"))
    filas = {l.split("|")[1].strip(): l for l in out.splitlines() if l.startswith("| 200")}
    # globo (200): venta neta 12 pzas en 0-30 d -> dem = 0.5*12/30 = 0.2/dia; necesidad 0.2*50 = 10; posicion = 2 -> sugerido 8
    assert "2000034" in filas and filas["2000034"].split("|")[10].strip() == "8"
    # spinner (300): 9 pzas (RM3 4 + RM5 5) -> 0.15/dia; necesidad 7.5; posicion 0 -> 8
    assert "2002784" in filas and filas["2002784"].split("|")[10].strip() == "8"
    # baraja (100): posicion 100+5+10 cubre la necesidad -> no se sugiere
    assert "2000112" not in filas


def test_sugerido_parametros_y_camionetas(empresa):
    # con cobertura 0 y entrega 0 la necesidad es 0: no se sugiere nada
    assert "Sin resultados" in run(llamar(empresa, "sugerido_compra", cobertura_dias=0, lead_time_dias=0))
    with pytest.raises(Exception, match=">= 0"):
        run(llamar(empresa, "sugerido_compra", cobertura_dias=-1))


def test_sin_movimiento_y_stock_camioneta(empresa):
    sm = run(llamar(empresa, "sin_movimiento"))
    fila = [l for l in sm.splitlines() if l.startswith("| 2000400")][0]     # tiene 7 pzas en el general y ninguna venta
    assert "| 7.00 |" in fila and "| 70.00 |" in fila
    assert "2000112" not in sm                                              # la baraja si se vende: no aparece
    sc = run(llamar(empresa, "stock_camioneta", camioneta="camioneta 1"))
    assert "2000112" in sc and "| 5.00 |" in sc
