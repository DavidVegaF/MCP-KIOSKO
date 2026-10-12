-- params:
-- Ordenes de compra (tipo O) con unidades POR RECIBIR: es lo que ya esta pedido y todavia no llega.
SELECT d.ARTICULO_ID AS articulo_id, e.DOCTO_CM_ID AS docto_cm_id, TRIM(e.FOLIO) AS folio, e.FECHA AS fecha,
       e.PROVEEDOR_ID AS proveedor_id, TRIM(e.ESTATUS) AS estatus, d.UNIDADES AS unidades,
       d.UNIDADES_A_REC AS unidades_a_rec
FROM DOCTOS_CM e
JOIN DOCTOS_CM_DET d ON d.DOCTO_CM_ID = e.DOCTO_CM_ID
WHERE e.TIPO_DOCTO = 'O' AND d.UNIDADES_A_REC > 0
