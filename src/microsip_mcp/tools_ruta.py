"""Herramientas MCP del perfil RUTA (camionetas -> kioscos). Todas son de solo lectura sobre DuckDB."""
from __future__ import annotations

from datetime import date, timedelta

from mcp.server.fastmcp import FastMCP

from . import db
from .config import Empresa
from .fmt import tabla
from .estacional import factor_estacional
from .guards import validar_sql


# ---------------------------------------------------------------- utilidades
def _fecha(valor: str | None, nombre: str) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(valor.strip())
    except ValueError:
        raise ValueError(f"'{nombre}' debe tener formato AAAA-MM-DD (recibido: {valor!r})") from None


def _rango(emp: Empresa, desde: str | None, hasta: str | None, dias: int = 90) -> tuple[date, date]:
    h = _fecha(hasta, "hasta") or db.hoy(emp)
    d = _fecha(desde, "desde") or (h - timedelta(days=dias - 1))
    if d > h:
        raise ValueError("'desde' no puede ser posterior a 'hasta'")
    return d, h


def _like(col: str, valor: str | None, conds: list, params: list) -> None:
    """Coincidencia parcial sin distinguir mayusculas ni acentos (como el MCP original)."""
    if valor and valor.strip():
        conds.append(f"strip_accents({col}) ILIKE strip_accents(?)")
        params.append(f"%{valor.strip()}%")


def _kiosko_cond(valor: str | None, conds: list, params: list) -> None:
    if not valor or not valor.strip():
        return
    v = valor.strip()
    if v.isdigit():
        conds.append("(CAST(kiosko_id AS VARCHAR) = ? OR kiosko_raw = ?)")
        params += [v, v]
    else:
        _like("kiosko", v, conds, params)


def _where(conds: list) -> str:
    return "WHERE " + " AND ".join(conds) if conds else ""


GRUPOS_VENTA = {
    "total": "'TOTAL'",
    "mes": "strftime(fecha, '%Y-%m')",
    "dia": "CAST(fecha AS VARCHAR)",
    "camioneta": "camioneta",
    "vendedor": "vendedor",
    "kiosko": "COALESCE(CAST(kiosko_id AS VARCHAR) || ' ' || kiosko, 'SIN KIOSKO (' || COALESCE(kiosko_raw,'?') || ')')",
    "zona": "COALESCE(zona, 'SIN ZONA')",
    "articulo": "clave || ' ' || articulo",
    "linea": "linea",
}

GRUPOS_DEV = {
    "articulo": "clave || ' ' || articulo",
    "camioneta": "camioneta",
    "vendedor": "vendedor",
    "mes": "strftime(fecha, '%Y-%m')",
    "linea": "linea",
}

DICCIONARIO = """\
# Diccionario - {nombre}
Fecha de corte (ultima venta cargada): **{hoy}**. Los datos se reconstruyen cada noche; el dia en curso nunca esta completo.

## Que cuenta como venta
- Solo **remisiones (tipo R)** del modulo de facturacion (DOCTOS_VE). **Las facturas no se cuentan.**
- Se excluyen las remisiones con estatus {estatus_excl}. El importe es **sin IVA** (PRECIO_TOTAL_NETO del renglon).
- Canal de venta = **camioneta** (almacen de la camioneta de la remision). Un vendedor puede usar varias camionetas y
  una camioneta la usan varios vendedores: por eso se analizan por separado (camioneta) y (vendedor).

## Kioscos
- La **orden de compra** de la remision tiene la forma `14109-1-3-2236`. Lo anterior al primer guion es el id del kiosko:
  puede ser el **ID NUEVO** (5 digitos) o el **ID VIEJO** (4-5 digitos). Se resuelve contra el catalogo de kioscos
  (con coordenadas); el ID NUEVO tiene prioridad. Las remisiones cuyo id no esta en el catalogo salen como `SIN KIOSKO (...)`.
- Una remision = una visita a un kiosko (`v_visita`).

## Devoluciones
- Son movimientos de inventario (DOCTOS_IN) con concepto {conceptos}: **devolucion del kiosko a la camioneta**.
- La devolucion no trae vendedor: se asigna el **vendedor que mas vendio ese dia en esa camioneta** (`vendedor_camioneta_dia`).
  Si ese dia la camioneta no vendio nada, queda como `SIN VENDEDOR (ese dia)`. La devolucion tampoco trae kiosko.

## Tablas y vistas (usar con `sql`)
| Objeto | Que contiene |
|---|---|
| `v_venta` | Un renglon de remision: fecha, folio, camioneta, vendedor, kiosko_id, kiosko, zona, lat, lon, clave, articulo, linea, unidades, importe |
| `v_visita` | Una remision (visita): fecha, hora, folio, camioneta, vendedor, kiosko_id, kiosko, zona, lat, lon, importe, piezas, renglones |
| `v_canje` | Un canje (cambio emparejado con su devolucion): folios, camioneta, vendedor, piezas y costo devuelto/entregado, costo_neto |
| `v_cambio` | Un renglon entregado en cambio (salida a tienda): fecha, folio, camioneta, vendedor (probable), clave, articulo, linea, unidades, costo_total |
| `v_devolucion` | Un renglon devuelto: fecha, folio, camioneta, vendedor (probable), clave, articulo, linea, unidades, costo_total |
| `dim_kiosko` | Catalogo: kiosko_id, id_viejo, nombre, tipo, zona, zona_k, lat, lon, domicilio, colonia, cp, poblacion, estado |
| `dim_articulo`, `dim_almacen`, `dim_vendedor` | Catalogos |
| `kiosko_alias` | alias (id nuevo o viejo) -> kiosko_id |
| `calidad_kiosko` | Ids de orden de compra que no se pudieron resolver |
| `param` | `hoy` = fecha de corte |

## Cambios de mercancia
- Son **cambios fisicos a los kioscos**: DOCTOS_IN con concepto {cambio} (salida a tienda). Sacan producto de la camioneta **sin remision**, asi que no
  aparecen en `ventas` (no hay ingreso) pero **si cuentan como consumo de inventario** en la demanda del sugerido. Se ven con `cambios_ruta`
  (`v_cambio`) y se comparan con las devoluciones.
- Cada cambio dice `Canje folio entrada ET...`: ese es el folio de la **devolucion** que lo origino. Se emparejan en `canje`/`v_canje`
  (herramienta `canjes`): piezas y costo devuelto contra entregado. **Ninguno de los dos documentos trae el kiosko.**

## Inventario y sugeridos
- **Existencia** = entradas - salidas acumuladas de SALDOS_IN por articulo y almacen. Tipos: `general` ({general}), `camioneta`, `otro`.
- **Demanda diaria de ruta** = (0.5 x piezas 0-30 d + 0.3 x piezas 31-60 d + 0.2 x piezas 61-90 d) / 30, donde las piezas son la
  **salida fisica de las camionetas: remisiones + cambios de mercancia (salida a tienda) - devoluciones**.
- **En camino** = unidades por recibir de ordenes de compra (tipo O).
- **Clase ABC** (`abc_articulo`, columna `clase_abc`): por venta sin IVA de 90 dias; A+ primer 20 % de la venta acumulada, A hasta 80 %, B hasta 95 %, C el resto.
- **Estacionalidad**: indice mensual (1.0 = normal) en `estacionalidad_mes`, definido en la configuracion (no se aprende de la ruta). Factor =
  indice de los proximos (entrega + cobertura) dias / indice de la ventana de 90 dias que midio la demanda, acotado a 0.5-2.0 (herramienta `estacionalidad`).
- **Stock de seguridad** = z x desviacion semanal x raiz(entrega/7); z por clase (A+ 1.65, A 1.28, B 0.84, C 0.5).
- **Sugerido** = max(0, venta diaria x factor estacional x (entrega + cobertura) + seguridad - (disponible general [+ camionetas] + en camino)).
  Por defecto 30 dias de cobertura y 20 de entrega (ajustables); estacionalidad y seguridad se pueden apagar. Articulos con menos de 30 dias de
  historia salen como nuevos. **No considera tendencia explicita; los minimos de compra solo se muestran.**
- Tablas: `art_inventario` (una fila por articulo), `stock` (articulo x almacen), `demanda_ruta`, `compra_en_transito`, `prov_principal`.

Toda metrica de venta es `SUM(importe)` o `SUM(unidades)` sobre `v_venta`; las devoluciones `SUM(unidades)` sobre `v_devolucion`.
Filtros de texto: coincidencia parcial, sin distinguir mayusculas ni acentos.
"""


def registrar(mcp: FastMCP, emp: Empresa) -> None:
    vis = emp.filas_visibles

    def _salida(cols, filas, trunc, nota=""):
        return tabla(cols, filas, trunc, nota)

    # ---------------------------------------------------------------- diccionario
    @mcp.tool()
    def diccionario() -> str:
        """Entrega el esquema, las reglas de negocio y el significado de las tablas. Leelo antes de usar `sql`."""
        r = emp.reglas
        return DICCIONARIO.format(
            nombre=emp.nombre,
            hoy=db.hoy(emp),
            estatus_excl=", ".join(f"'{e}'" for e in r.get("estatus_excluidos", ["C"])),
            conceptos=", ".join(str(c) for c in r.get("conceptos_devolucion", [7972])),
            general=r.get("almacen_general", "sin definir"),
            cambio=", ".join(str(c) for c in r.get("conceptos_cambio", [])) or "(sin definir)",
        )

    # ---------------------------------------------------------------- ventas
    @mcp.tool()
    def ventas(
        desde: str | None = None, hasta: str | None = None, agrupar_por: str = "total",
        camioneta: str | None = None, vendedor: str | None = None, kiosko: str | None = None,
        zona: str | None = None, articulo: str | None = None, linea: str | None = None, top: int = 50,
    ) -> str:
        """Venta de ruta (remisiones, sin IVA): importe, unidades, remisiones, kioscos y ticket promedio.

        agrupar_por: total, mes, dia, camioneta, vendedor, kiosko, zona, articulo, linea.
        Fechas AAAA-MM-DD (por defecto, ultimos 90 dias hasta la fecha de corte).
        kiosko acepta id (nuevo o viejo) o parte del nombre. Los demas filtros son coincidencia parcial."""
        g = GRUPOS_VENTA.get(agrupar_por)
        if g is None:
            raise ValueError(f"agrupar_por debe ser uno de: {', '.join(GRUPOS_VENTA)}")
        d, h = _rango(emp, desde, hasta)
        conds, p = ["fecha BETWEEN ? AND ?"], [d, h]
        _like("camioneta", camioneta, conds, p)
        _like("vendedor", vendedor, conds, p)
        _kiosko_cond(kiosko, conds, p)
        _like("zona", zona, conds, p)
        _like("clave || ' ' || articulo", articulo, conds, p)
        _like("linea", linea, conds, p)
        orden = "grupo" if agrupar_por in ("mes", "dia") else "venta DESC"
        sql = f"""
          SELECT {g} AS grupo, ROUND(SUM(importe),2) AS venta, ROUND(SUM(unidades),2) AS unidades,
                 COUNT(DISTINCT docto_ve_id) AS remisiones, COUNT(DISTINCT kiosko_id) AS kioscos,
                 ROUND(SUM(importe)/NULLIF(COUNT(DISTINCT docto_ve_id),0),2) AS ticket_prom
          FROM v_venta {_where(conds)} GROUP BY 1 ORDER BY {orden} LIMIT {int(max(1, min(top, vis)))}"""
        c, f, t = db.consultar(emp, sql, p)
        return _salida(c, f, t, f"Periodo {d} a {h}. Importes sin IVA.")

    # ---------------------------------------------------------------- rankings
    def _ranking(dim_col: str, etiqueta: str, extra: str, desde, hasta, camioneta, vendedor, top):
        d, h = _rango(emp, desde, hasta)
        conds, p = ["fecha BETWEEN ? AND ?"], [d, h]
        _like("camioneta", camioneta, conds, p)
        _like("vendedor", vendedor, conds, p)
        sql = f"""
          WITH b AS (SELECT * FROM v_venta {_where(conds)}),
          tot AS (SELECT SUM(importe) AS t FROM b)
          SELECT {dim_col} AS {etiqueta}, ROUND(SUM(importe),2) AS venta,
                 ROUND(100*SUM(importe)/NULLIF((SELECT t FROM tot),0),1) AS pct_total,
                 ROUND(SUM(unidades),2) AS unidades, COUNT(DISTINCT docto_ve_id) AS remisiones,
                 COUNT(DISTINCT kiosko_id) AS kioscos, COUNT(DISTINCT fecha) AS dias_con_venta,
                 ROUND(SUM(importe)/NULLIF(COUNT(DISTINCT fecha),0),2) AS venta_por_dia,
                 {extra}
          FROM b GROUP BY 1 ORDER BY venta DESC LIMIT {int(max(1, min(top, vis)))}"""
        c, f, t = db.consultar(emp, sql, p)
        return _salida(c, f, t, f"Periodo {d} a {h}. Importes sin IVA.")

    @mcp.tool()
    def ranking_camionetas(
        desde: str | None = None, hasta: str | None = None,
        camioneta: str | None = None, vendedor: str | None = None, top: int = 20,
    ) -> str:
        """Que camionetas venden mas: venta, participacion, kioscos visitados, dias con venta y vendedores que la usaron."""
        return _ranking("camioneta", "camioneta", "COUNT(DISTINCT vendedor_id) AS vendedores",
                        desde, hasta, camioneta, vendedor, top)

    @mcp.tool()
    def ranking_vendedores(
        desde: str | None = None, hasta: str | None = None,
        camioneta: str | None = None, vendedor: str | None = None, top: int = 20,
    ) -> str:
        """Que vendedor vende mas: venta, participacion, kioscos visitados, dias con venta y camionetas que uso."""
        return _ranking("vendedor", "vendedor", "COUNT(DISTINCT almacen_id) AS camionetas",
                        desde, hasta, camioneta, vendedor, top)

    # ---------------------------------------------------------------- productos
    @mcp.tool()
    def productos_ruta(
        desde: str | None = None, hasta: str | None = None, camioneta: str | None = None,
        vendedor: str | None = None, zona: str | None = None, linea: str | None = None,
        articulo: str | None = None, ordenar_por: str = "unidades", top: int = 30,
    ) -> str:
        """Que productos venden mas los vendedores de ruta (ordenar_por: unidades o importe), con kioscos y camionetas que lo movieron."""
        if ordenar_por not in ("unidades", "importe"):
            raise ValueError("ordenar_por debe ser 'unidades' o 'importe'")
        d, h = _rango(emp, desde, hasta)
        conds, p = ["fecha BETWEEN ? AND ?"], [d, h]
        _like("camioneta", camioneta, conds, p)
        _like("vendedor", vendedor, conds, p)
        _like("zona", zona, conds, p)
        _like("linea", linea, conds, p)
        _like("clave || ' ' || articulo", articulo, conds, p)
        sql = f"""
          SELECT clave, articulo, linea, ROUND(SUM(unidades),2) AS unidades, ROUND(SUM(importe),2) AS importe,
                 COUNT(DISTINCT docto_ve_id) AS remisiones, COUNT(DISTINCT kiosko_id) AS kioscos,
                 COUNT(DISTINCT almacen_id) AS camionetas
          FROM v_venta {_where(conds)} GROUP BY clave, articulo, linea
          ORDER BY {ordenar_por} DESC LIMIT {int(max(1, min(top, vis)))}"""
        c, f, t = db.consultar(emp, sql, p)
        return _salida(c, f, t, f"Periodo {d} a {h}. Importes sin IVA.")

    # ---------------------------------------------------------------- devoluciones
    @mcp.tool()
    def devoluciones_ruta(
        desde: str | None = None, hasta: str | None = None, agrupar_por: str = "articulo",
        camioneta: str | None = None, vendedor: str | None = None, articulo: str | None = None,
        linea: str | None = None, top: int = 30,
    ) -> str:
        """Que se devuelve mas (devolucion del kiosko a la camioneta, DOCTOS_IN concepto de devolucion).

        agrupar_por: articulo, camioneta, vendedor, mes, linea. Incluye el % devuelto contra lo vendido en el mismo periodo.
        El vendedor de una devolucion es el que mas vendio ese dia en esa camioneta (la devolucion no lo trae)."""
        g = GRUPOS_DEV.get(agrupar_por)
        if g is None:
            raise ValueError(f"agrupar_por debe ser uno de: {', '.join(GRUPOS_DEV)}")
        d, h = _rango(emp, desde, hasta)
        conds, p = ["fecha BETWEEN ? AND ?"], [d, h]
        _like("camioneta", camioneta, conds, p)
        _like("vendedor", vendedor, conds, p)
        _like("clave || ' ' || articulo", articulo, conds, p)
        _like("linea", linea, conds, p)
        w = _where(conds)
        orden = "grupo" if agrupar_por == "mes" else "unidades_devueltas DESC"
        sql = f"""
          WITH dev AS (
            SELECT {g} AS grupo, SUM(unidades) AS u, SUM(costo_total) AS c, COUNT(DISTINCT docto_in_id) AS n
            FROM v_devolucion {w} GROUP BY 1),
          ven AS (
            SELECT {g} AS grupo, SUM(unidades) AS u FROM v_venta {w} GROUP BY 1)
          SELECT dev.grupo AS grupo, ROUND(dev.u,2) AS unidades_devueltas, ROUND(dev.c,2) AS costo_devuelto,
                 dev.n AS movimientos, ROUND(ven.u,2) AS unidades_vendidas,
                 ROUND(100*dev.u/NULLIF(ven.u,0),1) AS pct_devuelto
          FROM dev LEFT JOIN ven USING (grupo) ORDER BY {orden} LIMIT {int(max(1, min(top, vis)))}"""
        c, f, t = db.consultar(emp, sql, p + p)
        return _salida(c, f, t,
                       f"Periodo {d} a {h}. pct_devuelto = devuelto / vendido (remisiones) del mismo grupo; vacio si no hubo venta.")

    # ---------------------------------------------------------------- kioscos
    @mcp.tool()
    def kiosko_geolocalizar(kiosko: str, top: int = 10) -> str:
        """Ubica un kiosko: coordenadas, liga a Google Maps, domicilio y resumen de visitas.

        `kiosko` acepta id (nuevo o viejo) o parte del nombre. Para ubicar una remision usa `visitas` con su folio."""
        v = kiosko.strip()
        if not v:
            raise ValueError("Indica un id o parte del nombre del kiosko")
        conds, p = [], []
        if v.isdigit():
            conds.append("(CAST(k.kiosko_id AS VARCHAR) = ? OR CAST(k.id_viejo AS VARCHAR) = ?)")
            p += [v, v]
        else:
            _like("k.nombre", v, conds, p)
        sql = f"""
          SELECT k.kiosko_id, k.id_viejo, k.nombre, k.tipo, k.zona, k.zona_k, k.lat, k.lon,
                 CASE WHEN k.lat IS NULL THEN NULL
                      ELSE 'https://www.google.com/maps?q=' || k.lat || ',' || k.lon END AS mapa,
                 TRIM(COALESCE(k.domicilio,'') || ' ' || COALESCE(k.num_ext,'') || ', ' || COALESCE(k.colonia,'')
                      || ', ' || COALESCE(k.poblacion,'') || ', ' || COALESCE(k.estado,'')) AS domicilio,
                 COUNT(vi.docto_ve_id) AS remisiones, ROUND(SUM(vi.importe),2) AS venta,
                 MAX(vi.fecha) AS ultima_visita, MODE(vi.camioneta) AS camioneta_frecuente,
                 MODE(vi.vendedor) AS vendedor_frecuente
          FROM dim_kiosko k LEFT JOIN fact_visita vi ON vi.kiosko_id = k.kiosko_id
          {_where(conds)} GROUP BY ALL ORDER BY remisiones DESC, k.kiosko_id LIMIT {int(max(1, min(top, vis)))}"""
        c, f, t = db.consultar(emp, sql, p)
        return _salida(c, f, t, "Venta sin IVA, todo el historial cargado.")

    @mcp.tool()
    def visitas(
        desde: str | None = None, hasta: str | None = None, camioneta: str | None = None,
        vendedor: str | None = None, kiosko: str | None = None, folio: str | None = None, top: int = 50,
    ) -> str:
        """Lista de visitas (una remision = una visita) con el kiosko y sus coordenadas. Sirve para ver la ruta de un dia,
        de una camioneta o de un vendedor, o para ubicar una remision por su folio (ej. RM3749)."""
        d, h = _rango(emp, desde, hasta, dias=7)
        conds, p = ["fecha BETWEEN ? AND ?"], [d, h]
        _like("camioneta", camioneta, conds, p)
        _like("vendedor", vendedor, conds, p)
        _kiosko_cond(kiosko, conds, p)
        if folio and folio.strip():
            conds.append("UPPER(TRIM(folio)) = UPPER(?)")
            p.append(folio.strip())
            p[0], p[1] = date(2000, 1, 1), date(2999, 1, 1)   # un folio se busca en todo el historial
        sql = f"""
          SELECT fecha, hora, folio, camioneta, vendedor, kiosko_id, kiosko, zona, lat, lon,
                 ROUND(importe,2) AS importe, ROUND(piezas,2) AS piezas, orden_compra
          FROM v_visita {_where(conds)} ORDER BY fecha DESC, hora DESC, folio LIMIT {int(max(1, min(top, vis)))}"""
        c, f, t = db.consultar(emp, sql, p)
        return _salida(c, f, t, "Importes sin IVA. lat/lon vacios = kiosko sin coordenadas o sin resolver.")

    # ---------------------------------------------------------------- articulo
    @mcp.tool()
    def articulo(busqueda: str, desde: str | None = None, hasta: str | None = None, top: int = 10) -> str:
        """Ficha de uno o varios articulos (clave exacta o parte del nombre): venta de ruta, devoluciones y % devuelto."""
        b = busqueda.strip()
        if not b:
            raise ValueError("Indica una clave o parte del nombre")
        d, h = _rango(emp, desde, hasta, dias=365)
        sql = f"""
          WITH a AS (
            SELECT articulo_id, clave, nombre, linea FROM dim_articulo
            WHERE UPPER(clave) = UPPER(?) OR strip_accents(nombre) ILIKE strip_accents(?)
            ORDER BY (UPPER(clave) = UPPER(?)) DESC, clave LIMIT {int(max(1, min(top, vis)))}),
          v AS (SELECT articulo_id, SUM(unidades) AS u, SUM(importe) AS i, COUNT(DISTINCT kiosko_id) AS k,
                       MAX(fecha) AS ultima FROM fact_remision_det WHERE fecha BETWEEN ? AND ? GROUP BY 1),
          x AS (SELECT articulo_id, SUM(unidades) AS u FROM fact_devolucion_det
                WHERE fecha BETWEEN ? AND ? GROUP BY 1)
          SELECT a.clave, a.nombre, a.linea, ROUND(v.u,2) AS unidades_vendidas, ROUND(v.i,2) AS venta,
                 v.k AS kioscos, v.ultima AS ultima_venta, ROUND(x.u,2) AS unidades_devueltas,
                 ROUND(100*x.u/NULLIF(v.u,0),1) AS pct_devuelto
          FROM a LEFT JOIN v USING (articulo_id) LEFT JOIN x USING (articulo_id)"""
        c, f, t = db.consultar(emp, sql, [b, f"%{b}%", b, d, h, d, h])
        return _salida(c, f, t, f"Periodo {d} a {h} (por defecto, ultimos 365 dias). Importes sin IVA.")

    # ---------------------------------------------------------------- calidad
    @mcp.tool()
    def calidad_datos() -> str:
        """Revisa la calidad del dato: ordenes de compra cuyo id de kiosko no se pudo resolver, remisiones sin vendedor y cobertura de coordenadas."""
        c1, f1, _ = db.consultar(emp, """
          SELECT 'remisiones cargadas' AS concepto, COUNT(DISTINCT docto_ve_id) AS n FROM fact_remision_det
          UNION ALL SELECT 'remisiones sin kiosko resuelto', COUNT(DISTINCT docto_ve_id) FROM fact_remision_det WHERE kiosko_id IS NULL
          UNION ALL SELECT 'remisiones sin vendedor', COUNT(DISTINCT docto_ve_id) FROM fact_remision_det WHERE vendedor_id IS NULL
          UNION ALL SELECT 'kioscos sin coordenadas', COUNT(*) FROM dim_kiosko WHERE lat IS NULL
          UNION ALL SELECT 'existencias en almacen general (filas; 0 = revisar almacen_general)', COUNT(*) FROM stock WHERE tipo_almacen = 'general'
          UNION ALL SELECT 'existencias en camionetas (filas)', COUNT(*) FROM stock WHERE tipo_almacen = 'camioneta'
          UNION ALL SELECT 'articulos con existencia negativa en algun almacen', COUNT(DISTINCT articulo_id) FROM stock WHERE existencia < 0
          UNION ALL SELECT 'ids viejos ambiguos (excluidos)', COUNT(*) FROM (SELECT id_viejo FROM dim_kiosko
                      WHERE id_viejo IS NOT NULL GROUP BY 1 HAVING COUNT(*) > 1)""")
        c2, f2, t2 = db.consultar(emp, "SELECT * FROM calidad_kiosko LIMIT 25")
        return (_salida(c1, f1, False) + "\n\n**Ids de orden de compra sin resolver (top 25):**\n\n" + _salida(c2, f2, t2))

    # ---------------------------------------------------------------- cambios de mercancia
    @mcp.tool()
    def cambios_ruta(
        desde: str | None = None, hasta: str | None = None, agrupar_por: str = "articulo",
        camioneta: str | None = None, vendedor: str | None = None, articulo: str | None = None,
        linea: str | None = None, top: int = 30,
    ) -> str:
        """Cambios fisicos de mercancia a los kioscos (salida a tienda, DOCTOS_IN concepto de cambio) contra lo que devuelven.

        Un cambio saca producto de la camioneta sin remision (no hay ingreso). agrupar_por: articulo, camioneta, vendedor,
        mes, linea. Muestra lo entregado en cambio, lo devuelto en el mismo periodo y la diferencia. El vendedor es el que mas
        vendio ese dia en esa camioneta (el documento no lo trae)."""
        g = GRUPOS_DEV.get(agrupar_por)
        if g is None:
            raise ValueError(f"agrupar_por debe ser uno de: {', '.join(GRUPOS_DEV)}")
        d, h = _rango(emp, desde, hasta)
        conds, p = ["fecha BETWEEN ? AND ?"], [d, h]
        _like("camioneta", camioneta, conds, p)
        _like("vendedor", vendedor, conds, p)
        _like("clave || ' ' || articulo", articulo, conds, p)
        _like("linea", linea, conds, p)
        w = _where(conds)
        orden = "grupo" if agrupar_por == "mes" else "entregado_en_cambio DESC NULLS LAST"
        sql = f"""
          WITH c AS (SELECT {g} AS grupo, SUM(unidades) AS u, SUM(costo_total) AS cst, COUNT(DISTINCT docto_in_id) AS n
                     FROM v_cambio {w} GROUP BY 1),
               d AS (SELECT {g} AS grupo, SUM(unidades) AS u FROM v_devolucion {w} GROUP BY 1)
          SELECT COALESCE(c.grupo, d.grupo) AS grupo, ROUND(c.u,2) AS entregado_en_cambio, ROUND(c.cst,2) AS costo,
                 c.n AS movimientos, ROUND(d.u,2) AS devuelto, ROUND(COALESCE(c.u,0) - COALESCE(d.u,0),2) AS diferencia
          FROM c FULL OUTER JOIN d ON d.grupo = c.grupo ORDER BY {orden} LIMIT {int(max(1, min(top, vis)))}"""
        c_, f, t = db.consultar(emp, sql, p + p)
        return _salida(c_, f, t, f"Periodo {d} a {h}. diferencia > 0: salio mas de lo que regreso. Costo = costo de la mercancia entregada.")

    @mcp.tool()
    def canjes(
        desde: str | None = None, hasta: str | None = None, agrupar_por: str = "camioneta",
        camioneta: str | None = None, vendedor: str | None = None, top: int = 30,
    ) -> str:
        """Canjes de mercancia: cada cambio (salida a tienda) emparejado con la devolucion que lo origino (por el folio de entrada).

        agrupar_por: camioneta, vendedor, mes, dia o canje (uno por renglon, con sus dos folios). Mide piezas y costo devuelto contra
        entregado; costo_neto = entregado - devuelto (lo que cuesta el programa de cambios). sin_devolucion = cambios cuyo folio
        de entrada no se encontro. El vendedor es el que mas vendio ese dia en esa camioneta."""
        grupos = {"camioneta": "camioneta", "vendedor": "vendedor", "mes": "strftime(fecha, '%Y-%m')",
                  "dia": "CAST(fecha AS VARCHAR)", "canje": None}
        if agrupar_por not in grupos:
            raise ValueError(f"agrupar_por debe ser uno de: {', '.join(grupos)}")
        d, h = _rango(emp, desde, hasta)
        conds, p = ["fecha BETWEEN ? AND ?"], [d, h]
        _like("camioneta", camioneta, conds, p)
        _like("vendedor", vendedor, conds, p)
        lim = int(max(1, min(top, vis)))
        if agrupar_por == "canje":
            sql = f"""
              SELECT fecha, folio_cambio, folio_entrada, camioneta, vendedor, ROUND(pzas_devueltas,2) AS pzas_devueltas,
                     ROUND(pzas_entregadas,2) AS pzas_entregadas, ROUND(costo_devuelto,2) AS costo_devuelto,
                     ROUND(costo_entregado,2) AS costo_entregado, ROUND(costo_neto,2) AS costo_neto
              FROM v_canje {_where(conds)} ORDER BY fecha DESC, folio_cambio DESC LIMIT {lim}"""
        else:
            g = grupos[agrupar_por]
            orden = "grupo" if agrupar_por in ("mes", "dia") else "costo_neto DESC"
            sql = f"""
              SELECT {g} AS grupo, COUNT(*) AS canjes, ROUND(SUM(pzas_devueltas),2) AS pzas_devueltas,
                     ROUND(SUM(pzas_entregadas),2) AS pzas_entregadas, ROUND(SUM(costo_devuelto),2) AS costo_devuelto,
                     ROUND(SUM(costo_entregado),2) AS costo_entregado, ROUND(SUM(costo_neto),2) AS costo_neto,
                     COUNT(*) FILTER (WHERE NOT con_devolucion) AS sin_devolucion
              FROM v_canje {_where(conds)} GROUP BY 1 ORDER BY {orden} LIMIT {lim}"""
        c_, f, t = db.consultar(emp, sql, p)
        return _salida(c_, f, t, f"Periodo {d} a {h}. Costos al costo de inventario. costo_neto > 0: se entrego mas valor del que regreso.")

    # ---------------------------------------------------------------- inventario y compras
    @mcp.tool()
    def existencias(
        articulo: str | None = None, linea: str | None = None, solo_con_existencia: bool = True, top: int = 50,
    ) -> str:
        """Existencias por articulo: almacen general, camionetas, lo que viene en camino, venta diaria de ruta y dias de cobertura.

        Existencia = entradas - salidas acumuladas (SALDOS_IN). La venta diaria es la salida de ruta (remisiones + cambios - devoluciones),
        ponderada 50/30/20 sobre los ultimos 90 dias. Ordenado por venta diaria (los que mas rotan primero)."""
        conds, p = [], []
        _like("clave || ' ' || nombre", articulo, conds, p)
        _like("linea", linea, conds, p)
        if solo_con_existencia:
            conds.append("(exist_general + exist_camionetas) > 0")
        sql = f"""
          SELECT clave, nombre AS articulo, linea, ROUND(exist_general,2) AS exist_general,
                 ROUND(exist_camionetas,2) AS exist_camionetas, ROUND(exist_general + exist_camionetas,2) AS total,
                 ROUND(en_transito,2) AS en_camino, ROUND(dem_diaria*30,1) AS venta_30d_estimada,
                 CASE WHEN dem_diaria > 0 THEN ROUND(GREATEST(exist_general + exist_camionetas, 0)/dem_diaria) END AS dias_cobertura,
                 CASE WHEN exist_general < 0 OR exist_camionetas < 0 THEN 'revisar existencia negativa' END AS aviso
          FROM art_inventario {_where(conds)} ORDER BY dem_diaria DESC, total DESC LIMIT {int(max(1, min(top, vis)))}"""
        c, f, t = db.consultar(emp, sql, p)
        return _salida(c, f, t, "Piezas. dias_cobertura = existencia total / venta diaria (existencia negativa cuenta 0); vacio si no hay venta en 90 dias.")

    def _indices() -> dict[int, float]:
        _, filas, _ = db.consultar(emp, "SELECT mes, indice FROM estacionalidad_mes")
        return {int(m): float(i) for m, i in filas}

    @mcp.tool()
    def sugerido_compra(
        linea: str | None = None, articulo: str | None = None, cobertura_dias: int = 30, lead_time_dias: int = 20,
        incluir_camionetas: bool = True, estacionalidad: bool = True, seguridad: bool = True, clase: str | None = None,
        top: int = 50,
    ) -> str:
        """Sugerido de compra para el almacen general.

        Referencia: salida diaria de las camionetas = remisiones + cambios de mercancia - devoluciones, ponderada 50/30/20 sobre 90 dias.
        Necesidad = venta diaria x factor de estacionalidad x (tiempo de entrega + dias de cobertura). Stock de seguridad (si `seguridad`)
        = z de la clase ABC x variabilidad semanal x raiz(entrega/7). Posicion = existencia disponible (general, y camionetas si
        incluir_camionetas) + ordenes de compra por recibir. Sugerido = necesidad + seguridad - posicion, hacia arriba; solo positivos.
        `clase`: A+, A, B o C. Articulos con menos de 30 dias de historia salen marcados como nuevos (la demanda no es confiable)."""
        if cobertura_dias < 0 or lead_time_dias < 0:
            raise ValueError("cobertura_dias y lead_time_dias deben ser >= 0")
        if clase is not None and clase.upper() not in ("A+", "A", "B", "C"):
            raise ValueError("clase debe ser A+, A, B o C")
        horizonte = lead_time_dias + cobertura_dias
        factor, idx_h, idx_b = (1.0, 1.0, 1.0)
        if estacionalidad and horizonte > 0:
            factor, idx_h, idx_b = factor_estacional(_indices(), db.hoy(emp), horizonte)
        conds, p = ["dem_diaria > 0"], [bool(incluir_camionetas), horizonte * factor, bool(seguridad), float(lead_time_dias)]
        _like("linea", linea, conds, p)
        _like("clave || ' ' || nombre", articulo, conds, p)
        if clase:
            conds.append("clase_abc = ?")
            p.append(clase.upper())
        sql = f"""
          WITH b AS (
            SELECT a.*, GREATEST(exist_general - comprom_general, 0) + CASE WHEN ? THEN GREATEST(exist_camionetas, 0) ELSE 0 END
                      + en_transito AS posicion,
                   dem_diaria * ? AS necesidad,
                   CASE WHEN ? THEN z * desv_semanal * sqrt(? / 7.0) ELSE 0 END AS ss
            FROM art_inventario a {_where(conds)})
          SELECT clave, nombre AS articulo, linea, clase_abc AS clase, ROUND(dem_diaria*30,1) AS venta_30d, ROUND(exist_general,1) AS general,
                 ROUND(exist_camionetas,1) AS camionetas, ROUND(en_transito,1) AS en_camino,
                 ROUND(posicion,1) AS posicion, ROUND(necesidad,1) AS necesidad, ROUND(ss,1) AS seguridad,
                 CAST(CEIL(necesidad + ss - posicion) AS BIGINT) AS sugerido,
                 proveedor, ROUND(minimo_ucom,1) AS minimo_compra,
                 CASE WHEN primera_mov > (SELECT hoy FROM param) - 30 THEN 'nuevo (<30 d)' END AS aviso
          FROM b WHERE necesidad + ss - posicion > 0 ORDER BY venta_90d DESC LIMIT {int(max(1, min(top, vis)))}"""
        c, f, t = db.consultar(emp, sql, p)
        est = f"estacionalidad x{factor:.2f} (indice horizonte {idx_h:.2f} / base {idx_b:.2f})" if estacionalidad else "sin estacionalidad"
        return _salida(c, f, t, f"Cobertura {cobertura_dias} d + entrega {lead_time_dias} d; {est}; "
                                f"stock de seguridad {'incluido' if seguridad else 'no incluido'}; "
                                f"camionetas {'incluidas' if incluir_camionetas else 'no incluidas'} en la posicion. Piezas.")

    @mcp.tool()
    def estacionalidad() -> str:
        """Indice de estacionalidad por mes (1.0 = mes normal) y el factor que se aplica hoy al sugerido de compra para distintos horizontes."""
        c, f, t = db.consultar(emp, "SELECT mes, indice FROM estacionalidad_mes ORDER BY mes")
        idx = {int(m): float(i) for m, i in f}
        hoy = db.hoy(emp)
        filas = [(h, *[round(x, 2) for x in factor_estacional(idx, hoy, h)]) for h in (30, 50, 60, 90)]
        return (_salida(c, f, t, "Perfil mensual editable en la configuracion; no se aprende de la ruta (poca historia formal).")
                + "\n\n" + _salida(["horizonte_dias", "factor", "indice_horizonte", "indice_base"], filas, False,
                                    f"Factor = indice de los proximos dias / indice de la ventana que midio la demanda (corte {hoy}); acotado a 0.5-2.0."))

    @mcp.tool()
    def abc(clase: str | None = None, linea: str | None = None, top: int = 50) -> str:
        """Clasificacion ABC por venta (importe sin IVA) de los ultimos 90 dias en ruta: A+ (primer 20 % de la venta), A (hasta 80 %), B (hasta 95 %), C. Sin `clase`
        da el resumen por clase; con `clase` lista los articulos."""
        conds, p = ["clase_abc IS NOT NULL", "venta_90d > 0"], []
        _like("linea", linea, conds, p)
        if clase:
            if clase.upper() not in ("A+", "A", "B", "C"):
                raise ValueError("clase debe ser A+, A, B o C")
            conds.append("clase_abc = ?")
            p.append(clase.upper())
            sql = f"""SELECT clave, nombre AS articulo, linea, clase_abc AS clase, ROUND(venta_90d,2) AS venta_90d,
                             ROUND(dem_diaria*30,1) AS pzas_30d, ROUND(exist_general + exist_camionetas,1) AS existencia
                      FROM art_inventario {_where(conds)} ORDER BY venta_90d DESC LIMIT {int(max(1, min(top, vis)))}"""
        else:
            sql = f"""SELECT clase_abc AS clase, COUNT(*) AS articulos, ROUND(SUM(venta_90d),2) AS venta_90d,
                             ROUND(100*SUM(venta_90d)/SUM(SUM(venta_90d)) OVER (), 1) AS pct_venta
                      FROM art_inventario {_where(conds)} GROUP BY 1 ORDER BY CASE clase_abc WHEN 'A+' THEN 1 WHEN 'A' THEN 2 WHEN 'B' THEN 3 ELSE 4 END"""
        c, f, t = db.consultar(emp, sql, p)
        return _salida(c, f, t, "Venta de remisiones de los ultimos 90 dias (sin IVA). La clase fija el z del stock de seguridad.")

    @mcp.tool()
    def sin_movimiento(linea: str | None = None, top: int = 50) -> str:
        """Articulos con existencia que NO se vendieron en ruta en los ultimos 90 dias, ordenados por valor de inventario (costo)."""
        conds, p = ["(exist_general + exist_camionetas) > 0", "ultima_venta IS NULL"], []
        _like("linea", linea, conds, p)
        sql = f"""
          SELECT clave, nombre AS articulo, linea, ROUND(exist_general,1) AS general, ROUND(exist_camionetas,1) AS camionetas,
                 ROUND(valor_inventario,2) AS valor_inventario
          FROM art_inventario {_where(conds)} ORDER BY valor_inventario DESC LIMIT {int(max(1, min(top, vis)))}"""
        c, f, t = db.consultar(emp, sql, p)
        return _salida(c, f, t, "Valor al costo de entrada acumulado (SALDOS_IN).")

    @mcp.tool()
    def stock_camioneta(camioneta: str | None = None, articulo: str | None = None, top: int = 60) -> str:
        """Que lleva cada camioneta: existencia, comprometido y disponible por articulo."""
        conds, p = ["s.tipo_almacen = 'camioneta'", "s.existencia <> 0"], []
        _like("s.almacen", camioneta, conds, p)
        _like("a.clave || ' ' || a.nombre", articulo, conds, p)
        sql = f"""
          SELECT s.almacen AS camioneta, a.clave, a.nombre AS articulo, a.linea, ROUND(s.existencia,2) AS existencia,
                 ROUND(s.comprometido,2) AS comprometido, ROUND(s.disponible,2) AS disponible
          FROM stock s JOIN dim_articulo a ON a.articulo_id = s.articulo_id {_where(conds)}
          ORDER BY s.almacen, s.existencia DESC LIMIT {int(max(1, min(top, vis)))}"""
        c, f, t = db.consultar(emp, sql, p)
        return _salida(c, f, t)

    # ---------------------------------------------------------------- sql
    @mcp.tool()
    def sql(consulta: str) -> str:
        """Consulta libre de solo lectura (SELECT o WITH) sobre todo el almacen. Lee antes `diccionario`.
        Una sola sentencia; procesa hasta 2,000 filas y muestra hasta 200."""
        limpia = validar_sql(consulta)
        c, f, t = db.consultar(emp, limpia, None, emp.filas_sql)
        visibles = f[: emp.filas_visibles]
        nota = ""
        if t:
            nota = f"Resultado truncado a {emp.filas_sql} filas."
        if len(f) > len(visibles):
            nota += f" Se muestran {len(visibles)} de {len(f)} filas procesadas."
        return tabla(c, visibles, False, nota.strip())
