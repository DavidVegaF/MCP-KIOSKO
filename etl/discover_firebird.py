"""Descubre el esquema REAL de la base Microsip nueva (solo metadatos y conteos, sin datos personales).

Sirve para confirmar los nombres de columna que usan etl/korner/queries/*.sql antes de extraer.
Correr donde llegue a Firebird (la Mac llega a 192.168.1.2) y pegar el reporte:
    python etl/discover_firebird.py --ini etl/etl.ini > discover_report.txt
"""
from __future__ import annotations

import argparse
from pathlib import Path

from fb import cargar_credenciales, conectar

TABLAS = [
    "DOCTOS_VE", "DOCTOS_VE_DET", "DOCTOS_VE_LIGAS", "IMPUESTOS_DOCTOS_VE_DET",
    "DOCTOS_IN", "DOCTOS_IN_DET", "CONCEPTOS_IN",
    "ALMACENES", "VENDEDORES", "ARTICULOS", "CLAVES_ARTICULOS", "LINEAS_ARTICULOS", "GRUPOS_LINEAS",
    # inventario y compras (stocks y sugeridos de compra)
    "SALDOS_IN", "COMPROM_ARTICULOS", "DOCTOS_CM", "DOCTOS_CM_DET", "PROVEEDORES",
    "PRECIOS_COMPRA", "PRECIOS_COMPRA_DET", "PRECIOS_ARTICULOS", "TRASPASOS_IN", "TRASPASOS_IN_DET",
]

SQL_COLUMNAS = """
SELECT TRIM(rf.RDB$FIELD_NAME), TRIM(t.RDB$TYPE_NAME), f.RDB$FIELD_LENGTH, f.RDB$FIELD_PRECISION,
       f.RDB$FIELD_SCALE, rf.RDB$NULL_FLAG
FROM RDB$RELATION_FIELDS rf
JOIN RDB$FIELDS f ON f.RDB$FIELD_NAME = rf.RDB$FIELD_SOURCE
JOIN RDB$TYPES t ON t.RDB$FIELD_NAME = 'RDB$FIELD_TYPE' AND t.RDB$TYPE = f.RDB$FIELD_TYPE
WHERE rf.RDB$RELATION_NAME = ? ORDER BY rf.RDB$FIELD_POSITION"""

# (titulo, sql). Cada una se ejecuta aislada: si una columna no existe, se imprime el error y se sigue.
CONSULTAS = [
    ("Remisiones por TIPO_DOCTO y ESTATUS (todo el historial)",
     "SELECT TRIM(TIPO_DOCTO), TRIM(ESTATUS), COUNT(*), MIN(FECHA), MAX(FECHA) FROM DOCTOS_VE GROUP BY 1, 2 ORDER BY 1, 2"),
    ("Remisiones (R) por almacen",
     "SELECT d.ALMACEN_ID, TRIM(a.NOMBRE), COUNT(*), MIN(d.FECHA), MAX(d.FECHA) FROM DOCTOS_VE d "
     "LEFT JOIN ALMACENES a ON a.ALMACEN_ID = d.ALMACEN_ID WHERE d.TIPO_DOCTO = 'R' GROUP BY 1, 2 ORDER BY 3 DESC"),
    ("Remisiones (R) por vendedor",
     "SELECT d.VENDEDOR_ID, TRIM(v.NOMBRE), COUNT(*) FROM DOCTOS_VE d "
     "LEFT JOIN VENDEDORES v ON v.VENDEDOR_ID = d.VENDEDOR_ID WHERE d.TIPO_DOCTO = 'R' GROUP BY 1, 2 ORDER BY 3 DESC"),
    ("Relacion almacen x vendedor en remisiones R (una camioneta la usan varios vendedores?)",
     "SELECT d.ALMACEN_ID, d.VENDEDOR_ID, COUNT(*) FROM DOCTOS_VE d WHERE d.TIPO_DOCTO = 'R' GROUP BY 1, 2 ORDER BY 1, 3 DESC"),
    ("ORDEN_COMPRA en remisiones R: vacias vs con valor",
     "SELECT CASE WHEN ORDEN_COMPRA IS NULL OR TRIM(ORDEN_COMPRA) = '' THEN 'vacia' ELSE 'con valor' END, COUNT(*) "
     "FROM DOCTOS_VE WHERE TIPO_DOCTO = 'R' GROUP BY 1"),
    ("ORDEN_COMPRA: 8 ejemplos recientes (formato kiosko-n-3-nnnn)",
     "SELECT FIRST 8 TRIM(FOLIO), FECHA, TRIM(ORDEN_COMPRA) FROM DOCTOS_VE WHERE TIPO_DOCTO = 'R' "
     "AND ORDEN_COMPRA IS NOT NULL AND TRIM(ORDEN_COMPRA) <> '' ORDER BY FECHA DESC, DOCTO_VE_ID DESC"),
    ("Longitud del primer segmento de ORDEN_COMPRA (antes del primer guion)",
     "SELECT CHAR_LENGTH(SUBSTRING(TRIM(ORDEN_COMPRA) FROM 1 FOR POSITION('-' IN TRIM(ORDEN_COMPRA)) - 1)), COUNT(*) "
     "FROM DOCTOS_VE WHERE TIPO_DOCTO = 'R' AND POSITION('-' IN TRIM(ORDEN_COMPRA)) > 1 GROUP BY 1 ORDER BY 1"),
    ("Concepto 7972 en CONCEPTOS_IN",
     "SELECT * FROM CONCEPTOS_IN WHERE CONCEPTO_IN_ID = 7972"),
    ("DOCTOS_IN concepto 7972: por almacen",
     "SELECT i.ALMACEN_ID, TRIM(a.NOMBRE), COUNT(*), MIN(i.FECHA), MAX(i.FECHA) FROM DOCTOS_IN i "
     "LEFT JOIN ALMACENES a ON a.ALMACEN_ID = i.ALMACEN_ID WHERE i.CONCEPTO_IN_ID = 7972 GROUP BY 1, 2 ORDER BY 3 DESC"),
    ("DOCTOS_IN concepto 7972: 8 ejemplos (la DESCRIPCION trae el kiosko?)",
     "SELECT FIRST 8 TRIM(FOLIO), FECHA, ALMACEN_ID, TRIM(DESCRIPCION), TRIM(CANCELADO), TRIM(APLICADO) "
     "FROM DOCTOS_IN WHERE CONCEPTO_IN_ID = 7972 ORDER BY FECHA DESC, DOCTO_IN_ID DESC"),
    ("SALDOS_IN: rango de fechas y filas",
     "SELECT COUNT(*), MIN(FECHA), MAX(FECHA), COUNT(DISTINCT ALMACEN_ID), COUNT(DISTINCT ARTICULO_ID) FROM SALDOS_IN"),
    ("Existencia por almacen (suma de entradas - salidas, unidades)",
     "SELECT s.ALMACEN_ID, TRIM(a.NOMBRE), COUNT(DISTINCT s.ARTICULO_ID), SUM(s.ENTRADAS_UNIDADES - s.SALIDAS_UNIDADES) "
     "FROM SALDOS_IN s LEFT JOIN ALMACENES a ON a.ALMACEN_ID = s.ALMACEN_ID GROUP BY 1, 2 ORDER BY 1"),
    ("Compras: DOCTOS_CM por TIPO_DOCTO y ESTATUS",
     "SELECT TRIM(TIPO_DOCTO), TRIM(ESTATUS), COUNT(*), MIN(FECHA), MAX(FECHA) FROM DOCTOS_CM GROUP BY 1, 2 ORDER BY 1, 2"),
    ("Proveedores: cuantos y con datos de compra",
     "SELECT COUNT(*) FROM PROVEEDORES"),
    ("PRECIOS_COMPRA: filas (lead time / minimos por articulo-proveedor)",
     "SELECT COUNT(*) FROM PRECIOS_COMPRA"),
    ("Traspasos de mercancia (almacen general -> camionetas): ultimos 8",
     "SELECT FIRST 8 TRIM(FOLIO), FECHA, ALMACEN_ORIGEN_ID, ALMACEN_DESTINO_ID, TRIM(ESTATUS) FROM TRASPASOS_IN ORDER BY FECHA DESC, TRASPASO_IN_ID DESC"),
    ("Almacenes",
     "SELECT ALMACEN_ID, TRIM(NOMBRE), TRIM(OCULTO) FROM ALMACENES ORDER BY ALMACEN_ID"),
    ("Vendedores",
     "SELECT * FROM VENDEDORES"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ini", type=Path)
    a = ap.parse_args()
    con = conectar(cargar_credenciales(a.ini))
    cur = con.cursor()

    print("# REPORTE DE ESQUEMA (solo metadatos y conteos)\n")
    for tabla in TABLAS:
        print(f"## Columnas de {tabla}")
        try:
            cur.execute(SQL_COLUMNAS, (tabla,))
            filas = cur.fetchall()
            if not filas:
                print("   (la tabla no existe o no tiene columnas visibles)")
            for n, t, ln, pr, sc, nf in filas:
                print(f"   {n:32} {t:10} len={ln} prec={pr} scale={sc} {'NOT NULL' if nf else ''}")
        except Exception as e:                      # noqa: BLE001 - reporte tolerante
            print(f"   ERROR: {e}")
        print()
    for titulo, sql in CONSULTAS:
        print(f"## {titulo}")
        try:
            cur.execute(sql)
            for fila in cur.fetchall():
                print("   " + " | ".join("" if v is None else str(v).strip() for v in fila))
        except Exception as e:                      # noqa: BLE001
            print(f"   ERROR: {e}")
        print()
    con.close()


if __name__ == "__main__":
    main()
