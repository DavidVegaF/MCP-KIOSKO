-- params: desde
-- Movimientos de inventario de ruta: devoluciones del kiosko (reglas.conceptos_devolucion, ej. 7972) y
-- cambios de mercancia / salidas a tienda (reglas.conceptos_cambio, ej. 7974).
SELECT DOCTO_IN_ID AS docto_in_id, TRIM(FOLIO) AS folio, FECHA AS fecha, ALMACEN_ID AS almacen_id,
       CONCEPTO_IN_ID AS concepto_in_id, TRIM(CANCELADO) AS cancelado, TRIM(DESCRIPCION) AS descripcion
FROM DOCTOS_IN
WHERE CONCEPTO_IN_ID IN ({CONCEPTOS_MOVIMIENTO}) AND FECHA >= ?
