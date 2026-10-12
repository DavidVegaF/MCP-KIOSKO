"""Convierte el catalogo de kioscos (Excel DAVID_RUTAS.xlsx, hoja 'Tiendas (2)') a dim_kiosko.parquet.

El Excel NO va al repo (es publico): se corre en la maquina que arma la base.
    python etl/load_kioscos.py DAVID_RUTAS.xlsx data/korner/parquet/dim_kiosko.parquet
"""
from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
import pyarrow as pa
import pyarrow.parquet as pq

HOJA = "Tiendas (2)"
# encabezado del Excel -> columna de dim_kiosko
COLUMNAS = {
    "Tipo": "tipo", "ZONA": "zona", "Zona K": "zona_k", "ID NUEVO": "id_nuevo", "ID VIEJO": "id_viejo",
    "Tiendas Total Cadena 650": "nombre", "Latitud": "lat", "Longitud": "lon", "Domicilio": "domicilio",
    "NumeroExt": "num_ext", "Colonia": "colonia", "CP": "cp", "Poblacion": "poblacion", "Estado": "estado",
}


def _txt(v):
    return None if v is None else str(v).strip() or None


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _flt(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def leer(xlsx: Path) -> list[dict]:
    wb = openpyxl.load_workbook(xlsx, data_only=True, read_only=True)
    ws = wb[HOJA]
    filas = ws.iter_rows(values_only=True)
    encabezado = None
    for fila in filas:                      # el encabezado no siempre es la primera fila
        if fila and "ID NUEVO" in fila:
            encabezado = list(fila)
            break
    if encabezado is None:
        raise SystemExit(f"No encontre el encabezado 'ID NUEVO' en la hoja {HOJA!r}")
    # el nombre de la columna de nombre trae el total de la cadena ("Tiendas Total Cadena 650"): se busca por prefijo
    idx = {}
    for i, h in enumerate(encabezado):
        if h is None:
            continue
        h = str(h).strip()
        clave = "Tiendas Total Cadena 650" if h.startswith("Tiendas Total Cadena") else h
        if clave in COLUMNAS and COLUMNAS[clave] not in idx:
            idx[COLUMNAS[clave]] = i
    faltan = set(COLUMNAS.values()) - set(idx)
    if faltan:
        raise SystemExit(f"Faltan columnas en el Excel: {sorted(faltan)}")
    out = []
    for fila in filas:
        if not fila or fila[idx["id_nuevo"]] is None:
            continue
        g = lambda c: fila[idx[c]]
        out.append({
            "id_nuevo": _int(g("id_nuevo")), "id_viejo": _int(g("id_viejo")), "nombre": _txt(g("nombre")),
            "tipo": _txt(g("tipo")), "zona": _txt(g("zona")), "zona_k": _txt(g("zona_k")),
            "lat": _flt(g("lat")), "lon": _flt(g("lon")), "domicilio": _txt(g("domicilio")),
            "num_ext": _txt(g("num_ext")), "colonia": _txt(g("colonia")), "cp": _int(g("cp")),
            "poblacion": _txt(g("poblacion")), "estado": _txt(g("estado")),
        })
    return out


def main(argv=None):
    a = argv if argv is not None else sys.argv[1:]
    if len(a) != 2:
        raise SystemExit(__doc__)
    filas = leer(Path(a[0]))
    ids = [f["id_nuevo"] for f in filas]
    if len(ids) != len(set(ids)):
        raise SystemExit("Hay ID NUEVO repetidos en el catalogo: corrigelo antes de cargar")
    destino = Path(a[1])
    destino.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(filas), destino)
    sin_coord = sum(1 for f in filas if not f["lat"] or not f["lon"])
    viejos = {}
    for f in filas:
        viejos.setdefault(f["id_viejo"], []).append(f["nombre"])
    amb = {k: v for k, v in viejos.items() if k is not None and len(v) > 1}
    print(f"OK {len(filas)} kioscos -> {destino}")
    print(f"   sin coordenadas: {sin_coord}")
    print(f"   ID VIEJO repetidos (se excluyen del cruce): {amb or 'ninguno'}")


if __name__ == "__main__":
    main()
