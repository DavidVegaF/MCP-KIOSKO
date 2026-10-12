-- params: desde
-- Devoluciones del kiosko a la camioneta = movimientos de inventario con el/los concepto(s) de reglas.conceptos_devolucion.
SELECT DOCTO_IN_ID AS docto_in_id, TRIM(FOLIO) AS folio, FECHA AS fecha, ALMACEN_ID AS almacen_id,
       CONCEPTO_IN_ID AS concepto_in_id, TRIM(CANCELADO) AS cancelado, TRIM(DESCRIPCION) AS descripcion
FROM DOCTOS_IN
WHERE CONCEPTO_IN_ID IN ({CONCEPTOS_DEVOLUCION}) AND FECHA >= ?
