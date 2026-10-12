"""Guardas de la herramienta `sql` (mismas reglas que el MCP original, mas endurecimiento)."""
from __future__ import annotations

import re

PALABRAS_BLOQUEADAS = (
    "attach", "detach", "copy", "install", "load", "pragma", "create", "insert", "update",
    "delete", "drop", "alter", "export", "import", "call", "truncate",
    "read_csv", "read_text", "read_parquet", "read_json", "glob",
)

_COMENTARIOS = re.compile(r"(--[^\n]*|/\*.*?\*/)", re.S)
_CADENAS = re.compile(r"'(?:[^']|'')*'")


class SqlNoPermitido(ValueError):
    pass


def validar_sql(consulta: str) -> str:
    """Devuelve la consulta limpia o lanza SqlNoPermitido."""
    if not consulta or not consulta.strip():
        raise SqlNoPermitido("Consulta vacia.")
    limpia = _COMENTARIOS.sub(" ", consulta).strip().rstrip(";").strip()
    if ";" in _CADENAS.sub("''", limpia):
        raise SqlNoPermitido("Solo se permite un enunciado.")
    sin_cadenas = _CADENAS.sub("''", limpia).lower()
    if not re.match(r"^(select|with)\b", sin_cadenas):
        raise SqlNoPermitido("Solo se permiten consultas SELECT o WITH.")
    for palabra in PALABRAS_BLOQUEADAS:
        if re.search(rf"\b{re.escape(palabra)}\b", sin_cadenas):
            raise SqlNoPermitido(f"Palabra no permitida: {palabra}")
    return limpia
