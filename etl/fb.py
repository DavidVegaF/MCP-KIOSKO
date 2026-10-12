"""Conexion de SOLO LECTURA a Firebird (Microsip) con `firebirdsql` (driver Python puro, sin fbclient.dll).

Mismos parametros que ya usa la Mac en grupo-korner/test_fb.py: wire_crypt=False y autenticacion Srp.
Credenciales desde un .ini fuera de git o variables de entorno FB_*; nunca en el codigo.
"""
from __future__ import annotations

import configparser
import os
from pathlib import Path


def cargar_credenciales(ini: Path | None) -> dict:
    cfg = {
        "host": os.environ.get("FB_HOST", "localhost"), "port": os.environ.get("FB_PORT", "3050"),
        "database": os.environ.get("FB_DATABASE", ""), "user": os.environ.get("FB_USER", ""),
        "password": os.environ.get("FB_PASSWORD", ""), "charset": os.environ.get("FB_CHARSET", "WIN1252"),
        "readonly": os.environ.get("FB_READONLY", "true"),
    }
    if ini:
        cp = configparser.ConfigParser()
        cp.read(ini, encoding="utf-8-sig")          # leccion del original: config.ini se lee como utf-8-sig
        if cp.has_section("firebird"):
            cfg.update({k: v for k, v in cp["firebird"].items() if v})
    faltan = [k for k in ("database", "user", "password") if not cfg[k]]
    if faltan:
        raise SystemExit(f"Faltan credenciales Firebird: {faltan}. Usa --ini o variables FB_*.")
    return cfg


def conectar(cfg: dict):
    import firebirdsql                                # pip install firebirdsql

    return firebirdsql.connect(
        host=cfg["host"], port=int(cfg["port"]), database=cfg["database"],
        user=cfg["user"], password=cfg["password"], charset=cfg["charset"],
        wire_crypt=False, auth_plugin_name="Srp",
        readonly=str(cfg.get("readonly", "true")).lower() not in ("0", "false", "no"),
    )
