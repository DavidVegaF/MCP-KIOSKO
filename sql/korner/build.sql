-- build.sql (empresa RUTA / GRUPO COMERCIAL KORNER)
-- Se renderiza con etl/build.py: {{PARQUET}}, {{ESTATUS_EXCLUIDOS}}, {{CONCEPTOS_DEVOLUCION}}, {{HOY}}.
-- Lee los Parquet que deja etl/extract.py y arma el esquema que consultan las herramientas MCP.
-- Regla general: toda metrica es SUM(...) sobre renglones de REMISION (tipo R). Las facturas NO se cuentan.

CREATE TABLE param AS SELECT CAST('{{HOY}}' AS DATE) AS hoy;

-- ---------- Dimensiones ----------
CREATE TABLE dim_articulo AS
SELECT articulo_id, TRIM(clave) AS clave, TRIM(nombre) AS nombre,
       COALESCE(TRIM(linea), 'SIN LINEA') AS linea, COALESCE(TRIM(grupo), 'SIN GRUPO') AS grupo,
       TRIM(estatus) AS estatus, TRIM(es_juego) AS es_juego
FROM read_parquet('{{PARQUET}}/dim_articulo.parquet');

CREATE TABLE dim_almacen AS
SELECT almacen_id, TRIM(nombre) AS almacen
FROM read_parquet('{{PARQUET}}/dim_almacen.parquet');

CREATE TABLE dim_vendedor AS
SELECT vendedor_id, TRIM(nombre) AS vendedor
FROM read_parquet('{{PARQUET}}/dim_vendedor.parquet');

-- Catalogo de kioscos (viene del Excel DAVID_RUTAS.xlsx via etl/load_kioscos.py).
-- La coordenada 0,0 (ej. cafeteria) se trata como desconocida.
CREATE TABLE dim_kiosko AS
SELECT id_nuevo AS kiosko_id, id_viejo, TRIM(nombre) AS nombre, tipo, zona, zona_k,
       CASE WHEN lat = 0 AND lon = 0 THEN NULL ELSE lat END AS lat,
       CASE WHEN lat = 0 AND lon = 0 THEN NULL ELSE lon END AS lon,
       TRIM(domicilio) AS domicilio, TRIM(num_ext) AS num_ext, TRIM(colonia) AS colonia,
       cp, TRIM(poblacion) AS poblacion, TRIM(estado) AS estado
FROM read_parquet('{{PARQUET}}/dim_kiosko.parquet');

-- La orden de compra empieza con el id del kiosko: puede ser el ID NUEVO (5 digitos) o el ID VIEJO
-- (4 o 5 digitos). El ID NUEVO tiene prioridad. Un ID VIEJO repetido en el catalogo es ambiguo
-- y se excluye (queda sin kiosko, visible en la tabla de calidad).
CREATE TABLE kiosko_alias AS
WITH nuevos AS (
  SELECT CAST(kiosko_id AS VARCHAR) AS alias, kiosko_id, 1 AS prioridad FROM dim_kiosko
), viejos AS (
  SELECT CAST(id_viejo AS VARCHAR) AS alias, ANY_VALUE(kiosko_id) AS kiosko_id, 2 AS prioridad
  FROM dim_kiosko WHERE id_viejo IS NOT NULL GROUP BY id_viejo HAVING COUNT(*) = 1
), todos AS (SELECT * FROM nuevos UNION ALL SELECT * FROM viejos)
SELECT alias, kiosko_id FROM todos
QUALIFY ROW_NUMBER() OVER (PARTITION BY alias ORDER BY prioridad) = 1;

-- ---------- Hechos: ventas de ruta (renglones de remision) ----------
CREATE TABLE fact_remision_det AS
SELECT
  e.docto_ve_id, e.folio, e.fecha, e.hora, e.estatus,
  e.almacen_id, COALESCE(al.almacen, 'ALMACEN ' || e.almacen_id) AS camioneta,
  e.vendedor_id, COALESCE(v.vendedor, 'SIN VENDEDOR') AS vendedor,
  TRIM(e.orden_compra) AS orden_compra,
  split_part(TRIM(e.orden_compra), '-', 1) AS kiosko_raw,
  TRY_CAST(split_part(TRIM(e.orden_compra), '-', 2) AS INTEGER) AS oc_seg2,
  ka.kiosko_id,
  d.articulo_id, COALESCE(a.clave, '') AS clave, COALESCE(a.nombre, '') AS articulo,
  COALESCE(a.linea, 'SIN LINEA') AS linea,
  d.unidades, d.precio_unitario, d.precio_total_neto AS importe
FROM read_parquet('{{PARQUET}}/remision_enc.parquet') e
JOIN read_parquet('{{PARQUET}}/remision_det.parquet') d ON d.docto_ve_id = e.docto_ve_id
LEFT JOIN dim_almacen al ON al.almacen_id = e.almacen_id
LEFT JOIN dim_vendedor v ON v.vendedor_id = e.vendedor_id
LEFT JOIN dim_articulo a ON a.articulo_id = d.articulo_id
LEFT JOIN kiosko_alias ka ON ka.alias = split_part(TRIM(e.orden_compra), '-', 1)
WHERE COALESCE(e.estatus, '') NOT IN ({{ESTATUS_EXCLUIDOS}})
  AND COALESCE(e.almacen_id, -1) NOT IN ({{ALMACENES_EXCLUIDOS}});   -- el canal son solo las camionetas

-- Una fila por remision = una visita a un kiosko.
CREATE TABLE fact_visita AS
SELECT docto_ve_id, folio, fecha, MIN(hora) AS hora, almacen_id, camioneta, vendedor_id, vendedor,
       orden_compra, kiosko_raw, kiosko_id,
       SUM(importe) AS importe, SUM(unidades) AS piezas, COUNT(*) AS renglones
FROM fact_remision_det
GROUP BY docto_ve_id, folio, fecha, almacen_id, camioneta, vendedor_id, vendedor,
         orden_compra, kiosko_raw, kiosko_id;

-- ---------- Hechos: devoluciones del kiosko a la camioneta (DOCTOS_IN, concepto de devolucion) ----------
CREATE TABLE fact_devolucion_det AS
SELECT
  e.docto_in_id, e.folio, e.fecha, e.almacen_id,
  COALESCE(al.almacen, 'ALMACEN ' || e.almacen_id) AS camioneta,
  e.concepto_in_id, TRIM(e.descripcion) AS descripcion,
  d.articulo_id, COALESCE(a.clave, '') AS clave, COALESCE(a.nombre, '') AS articulo,
  COALESCE(a.linea, 'SIN LINEA') AS linea,
  d.unidades, d.costo_total
FROM read_parquet('{{PARQUET}}/doctos_in_enc.parquet') e
JOIN read_parquet('{{PARQUET}}/doctos_in_det.parquet') d ON d.docto_in_id = e.docto_in_id
LEFT JOIN dim_almacen al ON al.almacen_id = e.almacen_id
LEFT JOIN dim_articulo a ON a.articulo_id = d.articulo_id
WHERE e.concepto_in_id IN ({{CONCEPTOS_DEVOLUCION}})
  AND COALESCE(e.cancelado, 'N') <> 'S';

-- Cambios de mercancia / salidas a tienda (DOCTOS_IN, concepto de reglas.conceptos_cambio, ej. 7974): producto que
-- SALE de la camioneta hacia el kiosko sin remision (consumo real de inventario, sin ingreso).
CREATE TABLE fact_cambio_det AS
SELECT
  e.docto_in_id, e.folio, e.fecha, e.almacen_id,
  COALESCE(al.almacen, 'ALMACEN ' || e.almacen_id) AS camioneta,
  e.concepto_in_id, TRIM(e.descripcion) AS descripcion,
  d.articulo_id, COALESCE(a.clave, '') AS clave, COALESCE(a.nombre, '') AS articulo,
  COALESCE(a.linea, 'SIN LINEA') AS linea,
  d.unidades, d.costo_total
FROM read_parquet('{{PARQUET}}/doctos_in_enc.parquet') e
JOIN read_parquet('{{PARQUET}}/doctos_in_det.parquet') d ON d.docto_in_id = e.docto_in_id
LEFT JOIN dim_almacen al ON al.almacen_id = e.almacen_id
LEFT JOIN dim_articulo a ON a.articulo_id = d.articulo_id
WHERE e.concepto_in_id IN ({{CONCEPTOS_CAMBIO}})
  AND COALESCE(e.cancelado, 'N') <> 'S';

-- Vendedor probable de cada camioneta por dia (la devolucion no trae vendedor y una camioneta
-- la usan varios vendedores): el que mas vendio ese dia en esa camioneta.
CREATE TABLE vendedor_camioneta_dia AS
SELECT almacen_id, fecha, vendedor_id, vendedor
FROM (
  SELECT almacen_id, fecha, vendedor_id, vendedor, SUM(importe) AS imp
  FROM fact_remision_det GROUP BY ALL
)
QUALIFY ROW_NUMBER() OVER (PARTITION BY almacen_id, fecha ORDER BY imp DESC) = 1;

-- ---------- Vistas de apoyo con el kiosko ya resuelto ----------
CREATE VIEW v_venta AS
SELECT f.*, k.nombre AS kiosko, k.zona, k.zona_k, k.poblacion, k.lat, k.lon
FROM fact_remision_det f LEFT JOIN dim_kiosko k ON k.kiosko_id = f.kiosko_id;

CREATE VIEW v_visita AS
SELECT f.*, k.nombre AS kiosko, k.zona, k.zona_k, k.poblacion, k.lat, k.lon
FROM fact_visita f LEFT JOIN dim_kiosko k ON k.kiosko_id = f.kiosko_id;

CREATE VIEW v_cambio AS
SELECT d.*, COALESCE(vc.vendedor, 'SIN VENDEDOR (ese dia)') AS vendedor, vc.vendedor_id
FROM fact_cambio_det d
LEFT JOIN vendedor_camioneta_dia vc ON vc.almacen_id = d.almacen_id AND vc.fecha = d.fecha;

-- Canje = un cambio de mercancia (salida a tienda) emparejado con la devolucion que lo origino: la descripcion del
-- cambio dice "Canje folio entrada ET0000283" y ese es el folio de la devolucion (entrada de tienda).
CREATE TABLE canje AS
WITH c AS (
  SELECT docto_in_id, folio AS folio_cambio, fecha, almacen_id, camioneta,
         NULLIF(regexp_extract(COALESCE(descripcion, ''), '(?i)folio\s+entrada\s+(\S+)', 1), '') AS folio_entrada,
         COUNT(*) AS renglones_entregados, SUM(unidades) AS pzas_entregadas, SUM(costo_total) AS costo_entregado
  FROM fact_cambio_det GROUP BY docto_in_id, folio, fecha, almacen_id, camioneta, descripcion
), d AS (
  SELECT folio AS folio_entrada, COUNT(*) AS renglones_devueltos, SUM(unidades) AS pzas_devueltas, SUM(costo_total) AS costo_devuelto
  FROM fact_devolucion_det GROUP BY folio
)
SELECT c.*, d.renglones_devueltos, COALESCE(d.pzas_devueltas, 0) AS pzas_devueltas, COALESCE(d.costo_devuelto, 0) AS costo_devuelto,
       d.folio_entrada IS NOT NULL AS con_devolucion,
       c.costo_entregado - COALESCE(d.costo_devuelto, 0) AS costo_neto
FROM c LEFT JOIN d ON d.folio_entrada = c.folio_entrada;

CREATE VIEW v_canje AS
SELECT x.*, COALESCE(vc.vendedor, 'SIN VENDEDOR (ese dia)') AS vendedor
FROM canje x LEFT JOIN vendedor_camioneta_dia vc ON vc.almacen_id = x.almacen_id AND vc.fecha = x.fecha;

CREATE VIEW v_devolucion AS
SELECT d.*, COALESCE(vc.vendedor, 'SIN VENDEDOR (ese dia)') AS vendedor, vc.vendedor_id
FROM fact_devolucion_det d
LEFT JOIN vendedor_camioneta_dia vc ON vc.almacen_id = d.almacen_id AND vc.fecha = d.fecha;

-- ---------- Calidad de datos ----------
CREATE VIEW calidad_kiosko AS
SELECT kiosko_raw, COUNT(DISTINCT docto_ve_id) AS remisiones, ROUND(SUM(importe), 2) AS importe
FROM fact_remision_det WHERE kiosko_id IS NULL GROUP BY kiosko_raw ORDER BY remisiones DESC;


-- =====================================================================================================
-- Inventario y compras (existencias, sugeridos). Existencia = suma de entradas - salidas de SALDOS_IN
-- (todos los periodos), igual que en DTODO. Los tipos de almacen: general / camioneta / otro.
-- =====================================================================================================
CREATE TABLE stock AS
WITH s AS (
  SELECT articulo_id, almacen_id, SUM(entradas_unidades - salidas_unidades) AS existencia,
         SUM(entradas_costo - salidas_costo) AS valor
  FROM read_parquet('{{PARQUET}}/saldos_in.parquet') GROUP BY 1, 2
), c AS (
  SELECT articulo_id, almacen_id, SUM(unidades_comprom) AS comprometido
  FROM read_parquet('{{PARQUET}}/comprom_articulos.parquet') GROUP BY 1, 2
)
SELECT s.articulo_id, s.almacen_id, COALESCE(al.almacen, 'ALMACEN ' || s.almacen_id) AS almacen,
       CASE WHEN s.almacen_id = {{ALMACEN_GENERAL}} THEN 'general'
            WHEN al.almacen ILIKE 'camioneta%' THEN 'camioneta' ELSE 'otro' END AS tipo_almacen,
       s.existencia, COALESCE(c.comprometido, 0) AS comprometido,
       s.existencia - COALESCE(c.comprometido, 0) AS disponible, s.valor
FROM s
LEFT JOIN c ON c.articulo_id = s.articulo_id AND c.almacen_id = s.almacen_id
LEFT JOIN dim_almacen al ON al.almacen_id = s.almacen_id
WHERE s.existencia <> 0 OR COALESCE(c.comprometido, 0) <> 0;

-- Demanda de ruta = salida fisica neta de las camionetas: remisiones + cambios/salidas a tienda - devoluciones,
-- ponderada 50/30/20 sobre los ultimos 90 dias (ventanas 0-30, 31-60, 61-90 dias contra la fecha de corte), piezas/dia.
CREATE TABLE demanda_ruta AS
WITH m AS (
  SELECT articulo_id, fecha,  unidades AS u FROM fact_remision_det
  UNION ALL SELECT articulo_id, fecha,  unidades FROM fact_cambio_det
  UNION ALL SELECT articulo_id, fecha, -unidades FROM fact_devolucion_det
), w AS (
  SELECT articulo_id,
         SUM(CASE WHEN fecha >  h.hoy - 30 THEN u ELSE 0 END) AS n1,
         SUM(CASE WHEN fecha <= h.hoy - 30 AND fecha > h.hoy - 60 THEN u ELSE 0 END) AS n2,
         SUM(CASE WHEN fecha <= h.hoy - 60 AND fecha > h.hoy - 90 THEN u ELSE 0 END) AS n3,
         MAX(CASE WHEN u > 0 THEN fecha END) AS ultima_venta
  FROM m, param h WHERE fecha > h.hoy - 90 GROUP BY 1
)
SELECT articulo_id,
       GREATEST(n1, 0) AS u_0_30, GREATEST(n2, 0) AS u_31_60, GREATEST(n3, 0) AS u_61_90,
       (0.5 * GREATEST(n1, 0) + 0.3 * GREATEST(n2, 0) + 0.2 * GREATEST(n3, 0)) / 30.0 AS dem_diaria,
       ultima_venta
FROM w;

-- Compras en camino: ordenes (tipo O) con unidades por recibir.
CREATE TABLE compra_en_transito AS
SELECT articulo_id, SUM(unidades_a_rec) AS en_transito, COUNT(DISTINCT docto_cm_id) AS ordenes,
       MIN(fecha) AS orden_mas_antigua
FROM read_parquet('{{PARQUET}}/compra_pendiente.parquet') GROUP BY 1;

-- Proveedor principal por articulo (el predeterminado; si no hay, el de menor precio).
CREATE TABLE prov_principal AS
SELECT pc.articulo_id, TRIM(pr.nombre) AS proveedor, pc.minimo_ucom, pc.contenido, pc.precio_ucom
FROM read_parquet('{{PARQUET}}/precios_compra.parquet') pc
LEFT JOIN read_parquet('{{PARQUET}}/proveedores.parquet') pr ON pr.proveedor_id = pc.proveedor_id
QUALIFY ROW_NUMBER() OVER (PARTITION BY pc.articulo_id ORDER BY pc.predeterminado DESC, pc.precio_ucom ASC NULLS LAST) = 1;

-- Clase ABC por venta (importe sin IVA de remisiones) de los ultimos 90 dias: A+ / A / B / C segun la venta acumulada
-- (cortes en abc_param). La clase de un articulo se decide con la venta acumulada ANTES de incluirlo.
CREATE TABLE abc_articulo AS
WITH v AS (
  SELECT articulo_id, SUM(importe) AS venta, SUM(unidades) AS unidades
  FROM fact_remision_det, param h WHERE fecha > h.hoy - 90 GROUP BY 1 HAVING SUM(importe) > 0
), r AS (
  SELECT *, (SUM(venta) OVER (ORDER BY venta DESC, articulo_id) - venta) / SUM(venta) OVER () AS acum_previa,
         SUM(venta) OVER (ORDER BY venta DESC, articulo_id) / SUM(venta) OVER () AS acum
  FROM v
)
SELECT r.articulo_id, r.venta, r.unidades, r.acum,
       (SELECT p.clase FROM abc_param p WHERE r.acum_previa < p.corte ORDER BY p.orden LIMIT 1) AS clase
FROM r;

-- Variabilidad semanal de la salida de ruta (13 semanas, con semanas en cero): base del stock de seguridad.
CREATE TABLE desv_semanal AS
WITH m AS (
  SELECT articulo_id, fecha,  unidades AS u FROM fact_remision_det
  UNION ALL SELECT articulo_id, fecha,  unidades FROM fact_cambio_det
  UNION ALL SELECT articulo_id, fecha, -unidades FROM fact_devolucion_det
), s AS (
  SELECT articulo_id, CAST(date_diff('day', fecha, h.hoy) // 7 AS INTEGER) AS sem, SUM(u) AS u
  FROM m, param h WHERE fecha > h.hoy - 91 AND fecha <= h.hoy GROUP BY 1, 2
), art AS (SELECT DISTINCT articulo_id FROM s), semanas AS (SELECT unnest(range(0, 13)) AS sem)
SELECT a.articulo_id, STDDEV_SAMP(GREATEST(COALESCE(s.u, 0), 0)) AS desv_semanal
FROM art a CROSS JOIN semanas w LEFT JOIN s ON s.articulo_id = a.articulo_id AND s.sem = w.sem
GROUP BY a.articulo_id;

-- Primer movimiento de ruta de cada articulo (para marcar productos nuevos).
CREATE TABLE primera_mov AS
SELECT articulo_id, MIN(fecha) AS primera_mov FROM (
  SELECT articulo_id, fecha FROM fact_remision_det UNION ALL SELECT articulo_id, fecha FROM fact_cambio_det
) GROUP BY 1;

-- Una fila por articulo: existencias, demanda, compras en camino y proveedor.
CREATE TABLE art_inventario AS
WITH g AS (SELECT articulo_id, SUM(existencia) AS existencia, SUM(comprometido) AS comprometido, SUM(valor) AS valor
           FROM stock WHERE tipo_almacen = 'general' GROUP BY 1),
     c AS (SELECT articulo_id, SUM(existencia) AS existencia, SUM(valor) AS valor
           FROM stock WHERE tipo_almacen = 'camioneta' GROUP BY 1)
SELECT a.articulo_id, a.clave, a.nombre, a.linea,
       COALESCE(g.existencia, 0) AS exist_general, COALESCE(g.comprometido, 0) AS comprom_general,
       COALESCE(c.existencia, 0) AS exist_camionetas,
       COALESCE(g.valor, 0) + COALESCE(c.valor, 0) AS valor_inventario,
       COALESCE(d.dem_diaria, 0) AS dem_diaria, d.ultima_venta,
       COALESCE(t.en_transito, 0) AS en_transito, COALESCE(t.ordenes, 0) AS ordenes_pendientes,
       p.proveedor, p.minimo_ucom, p.contenido, p.precio_ucom,
       COALESCE(ab.clase, CASE WHEN d.articulo_id IS NOT NULL THEN 'C' END) AS clase_abc, COALESCE(ab.venta, 0) AS venta_90d,
       COALESCE(sd.desv_semanal, 0) AS desv_semanal,
       COALESCE((SELECT z FROM abc_param WHERE clase = COALESCE(ab.clase, CASE WHEN d.articulo_id IS NOT NULL THEN 'C' END)), 0) AS z,
       pm.primera_mov
FROM dim_articulo a
LEFT JOIN g ON g.articulo_id = a.articulo_id
LEFT JOIN c ON c.articulo_id = a.articulo_id
LEFT JOIN demanda_ruta d ON d.articulo_id = a.articulo_id
LEFT JOIN compra_en_transito t ON t.articulo_id = a.articulo_id
LEFT JOIN prov_principal p ON p.articulo_id = a.articulo_id
LEFT JOIN abc_articulo ab ON ab.articulo_id = a.articulo_id
LEFT JOIN desv_semanal sd ON sd.articulo_id = a.articulo_id
LEFT JOIN primera_mov pm ON pm.articulo_id = a.articulo_id
WHERE a.estatus = 'A'
  AND (g.articulo_id IS NOT NULL OR c.articulo_id IS NOT NULL OR d.articulo_id IS NOT NULL OR t.articulo_id IS NOT NULL);
