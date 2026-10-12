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

CREATE VIEW v_devolucion AS
SELECT d.*, COALESCE(vc.vendedor, 'SIN VENDEDOR (ese dia)') AS vendedor, vc.vendedor_id
FROM fact_devolucion_det d
LEFT JOIN vendedor_camioneta_dia vc ON vc.almacen_id = d.almacen_id AND vc.fecha = d.fecha;

-- ---------- Calidad de datos ----------
CREATE VIEW calidad_kiosko AS
SELECT kiosko_raw, COUNT(DISTINCT docto_ve_id) AS remisiones, ROUND(SUM(importe), 2) AS importe
FROM fact_remision_det WHERE kiosko_id IS NULL GROUP BY kiosko_raw ORDER BY remisiones DESC;
