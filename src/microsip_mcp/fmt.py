"""Salida en tablas markdown."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal


def _celda(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "si" if v else "no"
    if isinstance(v, (float, Decimal)):
        return f"{float(v):,.2f}"
    if isinstance(v, int):
        return f"{v:,}" if abs(v) >= 100000 else str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat()
    return str(v).replace("|", "/").replace("\n", " ")


def tabla(cols, filas, truncado: bool = False, nota: str = "") -> str:
    if not filas:
        return "Sin resultados." + (f"\n\n{nota}" if nota else "")
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    out += ["| " + " | ".join(_celda(v) for v in fila) + " |" for fila in filas]
    pie = []
    if truncado:
        pie.append(f"_Se muestran las primeras {len(filas)} filas; hay mas. Acota con filtros._")
    if nota:
        pie.append(nota)
    return "\n".join(out) + ("\n\n" + "\n".join(pie) if pie else "")
