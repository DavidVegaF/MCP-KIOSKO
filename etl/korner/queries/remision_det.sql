-- params: desde
SELECT d.DOCTO_VE_ID AS docto_ve_id, d.ARTICULO_ID AS articulo_id, d.UNIDADES AS unidades,
       d.PRECIO_UNITARIO AS precio_unitario, d.PRECIO_TOTAL_NETO AS precio_total_neto
FROM DOCTOS_VE_DET d
JOIN DOCTOS_VE e ON e.DOCTO_VE_ID = d.DOCTO_VE_ID
WHERE e.TIPO_DOCTO = 'R' AND e.FECHA >= ?
