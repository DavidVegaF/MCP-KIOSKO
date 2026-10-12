-- params: desde
-- Solo REMISIONES (tipo R). Las facturas no se extraen. ORDEN_COMPRA: los primeros caracteres antes del
-- primer guion son el id del kiosko (se resuelve en build.sql contra el catalogo).
SELECT DOCTO_VE_ID AS docto_ve_id, TRIM(FOLIO) AS folio, FECHA AS fecha, HORA AS hora, TRIM(ESTATUS) AS estatus,
       ALMACEN_ID AS almacen_id, VENDEDOR_ID AS vendedor_id, TRIM(ORDEN_COMPRA) AS orden_compra
FROM DOCTOS_VE
WHERE TIPO_DOCTO = 'R' AND FECHA >= ?
