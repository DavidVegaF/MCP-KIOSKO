# MCP existente: "Analítica con IA sobre Microsip" (DTODO)

Fuente: sesión `session_01FVYDNBDPbdN4Jm89i6A2Lr`, que leyó el PDF
*"Analítica con IA sobre Microsip: mapa del sistema y guía de replicación"* (8-oct-2026, Ing. David Vega).
El PDF y el código (`extract.py`, `build.sql`, `indicadores.sql`, `mcp_server.py`, `run.cmd`, `rebuild.sh`)
viven en el equipo del usuario, **no en GitHub**; este documento es la reconstrucción desde el texto del PDF.

## Arquitectura

```
Firebird (Microsip, usuario BI_READER solo lectura)
   │  extract.py  – 24 consultas, columnas explícitas, sin datos sensibles → Parquet (~35 MB)
   ▼
run.cmd (tarea Windows "MicrosipETL", 02:00, ~3 min) ──scp──► Mac Mini M4 (LAN, IP reservada)
                                                          rebuild.sh: build.sql + indicadores.sql
                                                          → analitica.new.duckdb → rename atómico → analitica.duckdb
                                                          mcp_server.py (FastMCP, `mcp<2`, 10 herramientas, stdio)
   ▲
Claude Desktop (suscripción) – local, o por `ssh <mac> python mcp_server.py` en equipos remotos
```

- Datos congelados a la corrida de las 02:00 (`param.hoy` = fecha de corte, no el reloj). Nunca escribe en Microsip.
- Conexión DuckDB read-only abierta y cerrada **por consulta** (no bloquea el intercambio nocturno).
- Sin costo por consulta (no usa API, usa la suscripción de Claude Desktop).
- Transporte actual: **stdio**. "Servidor MCP por HTTP" está en la hoja de ruta (prioridad baja) → **es justo lo que pide el nuevo proyecto (solo un link)**.

## Extractos (24 Parquet) ← tablas Microsip

dim_articulo ← ARTICULOS, LINEAS_ARTICULOS, GRUPOS_LINEAS, CLAVES_ARTICULOS (clave principal = rol 17, si no "SIN CLAVE") ·
dim_almacen ← ALMACENES · dim_sucursal ← SUCURSALES_CATALOGOS(+_DET), SUCURSALES (la sucursal no está en ALMACENES) ·
dim_cliente ← CLIENTES, TIPOS_CLIENTES, ZONAS_CLIENTES (sin domicilio/RFC/tel/correo) · dim_proveedor ← PROVEEDORES, TIPOS_PROV ·
dim_vendedor ← VENDEDORES · dim_precio_empresa ← PRECIOS_EMPRESA · costo_articulo ← PRECIOS_ARTICULOS (listas COSTOS y COSTO CHINA) ·
precio_venta_lista ← PRECIOS_ARTICULOS · precios_compra ← PRECIOS_COMPRA(+_DET) · juegos_det ← JUEGOS_DET ·
venta_pv_det ← DOCTOS_PV(+_DET) tipos V, v, D · venta_pv_impuestos ← IMPUESTOS_DOCTOS_PV_DET ·
doctos_ve_enc ← DOCTOS_VE · venta_ve_det ← DOCTOS_VE_DET tipos F, R, D · venta_ve_impuestos ← IMPUESTOS_DOCTOS_VE_DET ·
venta_ve_ligas ← DOCTOS_VE_LIGAS (evita doble conteo pedido/remisión/factura) · compra_cm_det ← DOCTOS_CM(+_DET) ·
compra_cm_impuestos ← IMPUESTOS_DOCTOS_CM_DET · saldos_in ← SALDOS_IN (existencia = suma acumulada) ·
comprom_articulos ← COMPROM_ARTICULOS · clasificadores ← CLASIFICADORES_CAT (TIPO_OBJETO='A') ·
clasif_valores ← CLASIFICADORES_CAT_VALORES · articulo_clasif ← ELEMENTOS_CAT_CLASIF (ELEMENTO_ID = ARTICULO_ID).
`CALC_DISP_ARTALM` solo se usa para validar existencias, no alimenta el almacén. Conexión Firebird: charset **ISO8859_1**.

## Almacén DuckDB (27 tablas + 15 vistas `v_*`)

- **Hechos**: `fact_venta_det` (1,944,467 renglones, 2025-01-02→2026-10-07; modulo, venta_det_id `PV:123`/`VE:456`, fecha, hora, articulo_id, almacen, canal, cliente_id, rol, signo, unidades_fisicas, importe_con_impto, costo_total, costo_propio) · `fact_compra_det` (33,830) · `snapshot_existencias` (52,261: existencia, comprometido, disponible, tipo_almacen).
- **Dimensiones**: dim_articulo (24,049), dim_almacen (15; tipo vendible/bodega_resurtido/logistico/transito), dim_cliente (10,623), dim_proveedor (486), dim_vendedor (9), dim_clasificador (22), dim_costo (18,081).
- **Puentes**: venta_vendedor, articulo_clasif, clasif_valor, art_etiquetas, prov_principal (lead_time, mínimo), compra_en_transito, doc_vendedor (legado), param.
- **Indicadores** (recalculados cada noche): art_existencia, art_exist_mensual, art_metricas, abc_articulo, rotacion_articulo, sin_movimiento, recomendacion_compra, recomendacion_promocion, revisar_inventario (187 con disponible negativo).
- Toda métrica = `SUM(valor * signo)` (+1 venta, −1 devolución).

## Reglas de negocio

- **Venta**: PV tipos V/v (+), D (−); VE tipos F factura y R remisión (+), D (−). No cuentan cancelados, no aplicados, cotizaciones, pedidos, remisiones ya ligadas a factura, retiros/ingresos de caja. Neta de devoluciones, con IVA (también sin IVA).
- **Canales** (por módulo + almacén + rol en M90): M90 Menudeo/Mayoreo (PV, M90, rol N) · Electrónica Página Web (PV, M90, paquete J y componentes C) · Madero 179 (PV, almacén ELECTRONICA) · Franquicias (VE, FACTURACION WEB; en 2025 WEB) · PV DISPONIBLE (PV, WEB hoy / MADERO 179 antes) · VE M90 (VE, FRANQUICIA) · 2 etiquetas de respaldo (<0.3 %).
- **Paquetes**: el ingreso se cuenta en renglón J, unidades físicas y costo en componentes C (`unidades_fisicas=0` en J, `importe_con_impto=0` en C, `costo_total=0` en J, `costo_propio=0` en C).
- **Margen** = (venta con IVA − costo)/venta con IVA; costo = lista COSTOS por artículo.
- **ABC** (ventana 90 d, por unidades y por margen): A+ 0–20 %, A 20–80 %, B 80–95 %, C 95–100 %.
- **Demanda diaria** ponderada: 50 % días 0–30, 30 % 31–60, 20 % 61–90.
- **Existencia** = SALDOS_IN acumulado − comprometido, todos los almacenes salvo tránsito. No almacenables (bolsas, fletes, servicios) cuentan en ventas/ABC/margen, no en inventario.
- **Sin movimiento**: ≥90 días sin venta.
- **Punto de reorden** = demanda en lead time + stock de seguridad (z = 1.65 / 1.28 / 0.84 / 0.5 según clase ABC; σ mensual × √(lead/30)). Lead time y mínimo de PRECIOS_COMPRA; default 20 días y 1 unidad. Posición = disponible + compras en tránsito; se excluyen disponibles negativos.
- **Promoción**: semáforo de 4 señales (días sin venta, cobertura, antigüedad, tendencia); puntaje ≥6 ROJO, 3–5 AMARILLO. Descuento máximo hasta el precio que iguala el costo, contra lista de venta 42.

## Las 10 herramientas MCP (FastMCP, devuelven tablas markdown)

| Herramienta | Qué hace | Parámetros |
|---|---|---|
| `diccionario` | Esquema y reglas (leer antes de `sql`) | — |
| `ventas` | Venta c/s IVA, unidades, margen, docs | desde, hasta, agrupar_por (total/mes/canal/linea/almacen/articulo/vendedor), canal, linea, almacen, articulo, vendedor, etiqueta |
| `master` | Tabla maestra por artículo tipo Excel | linea, etiqueta, abc_clase, solo_con_existencia, top (300) |
| `articulo` | Ficha de artículo(s) | busqueda (clave exacta o parte del nombre) |
| `abc` | Clasificación ABC | criterio (unidades/margen), clase, linea, etiqueta, top (50) |
| `sin_movimiento` | Inmovilizados por valor | linea, etiqueta, top (50) |
| `recomendacion_compra` | Qué comprar y cuánto | linea, abc, etiqueta, top (50) |
| `recomendacion_promocion` | Candidatos a promoción | nivel (AMARILLO/ROJO), linea, etiqueta, top (50) |
| `clasificadores` | Etiquetas y # de artículos | nombre |
| `sql` | Consulta libre de solo lectura | consulta |

Guardas de `sql`: solo SELECT/WITH, una sentencia, conexión read-only, tope 2,000 filas (200 visibles), bloquea `attach copy install load pragma create insert update delete drop alter export import call`. Filtros de texto: coincidencia parcial sin distinguir mayúsculas.

## Seguridad / privacidad

Usuario `BI_READER` (solo lectura, solo tablas necesarias) · extractor con columnas explícitas (sin RFC, CURP, teléfonos, correos, domicilios) · `config.ini` con permisos restringidos, contraseña fuera del código · ssh/scp por LAN con llave sin contraseña (`-n`, `BatchMode=yes`) · en `authorized_keys` usar `command="..."` + `restrict`. Sí viajan a Claude: nombres de artículos, clientes y proveedores + cifras.

## Limitaciones conocidas

Sin tiempo real · solo lectura · sin vendedor en punto de venta (0 de 1,856,685 renglones PV; 88,669 VE sí) · 0/486 proveedores con tipo/mínimo de orden · sin historial < 2025-01-02 · sin CxC/producción/finanzas/logística · ~0.14 % de diferencia vs ERP por redondeo de ticket · compras vs ventas 2025 sin conciliar · datos sucios (proveedor ".", no almacenables con inventario) · `costo_propio_1` duplicada y `doc_vendedor` legado · decimales inferidos por pyarrow · requiere `mcp<2` · una sola Mac Mini siempre encendida · reportes por correo no existen.

## Hoja de ruta del PDF

Alta: reservar IP de la Mac; replicar Claude Desktop en equipos de director/compras. Media: conciliar compras vs ventas; reportes programados por correo; parámetros y mapeo de almacenes a tablas. **Baja: servidor MCP por HTTP (~40 usuarios sin SSH)**; tabla `fact_venta_doc`.

## Cómo conectarlo con el nuevo proyecto (MCP-KIOSKO)

- Para "solo poner el link en Claude": exponer `mcp_server.py` como **Streamable HTTP** (FastMCP lo soporta) detrás de un túnel/dominio con autenticación; sin SSH ni Claude Desktop local.
- Se puede combinar con el servicio Firebird en vivo (`docs/CONTEXTO-MICROSIP.md`) para tener analítica (DuckDB, histórica) y consulta operativa (existencias/traspasos en vivo) en un mismo conector.
