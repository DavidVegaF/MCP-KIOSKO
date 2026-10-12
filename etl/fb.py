"""Conexion de SOLO LECTURA a Firebird (Microsip). Credenciales desde un .ini fuera de git o variables de entorno."""
from __future__ import annotations

import configparser
import os
from pathlib import Path


def cargar_credenciales(ini: Path | None) -> dict:
    cfg = {
        "host": os.environ.get("FB_HOST", "localhost"), "port": os.environ.get("FB_PORT", "3050"),
        "database": os.environ.get("FB_DATABASE", ""), "user": os.environ.get("FB_USER", ""),
        "password": os.environ.get("FB_PASSWORD", ""), "charset": os.environ.get("FB_CHARSET", "ISO8859_1"),
        "client_library": os.environ.get("FB_CLIENT_LIBRARY", ""),
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
    from firebird.driver import connect, driver_config   # pip install firebird-driver

    if cfg.get("client_library"):
        driver_config.fb_client_library.value = cfg["client_library"]
    return connect(f"{cfg['host']}/{cfg['port']}:{cfg['database']}",
                   user=cfg["user"], password=cfg["password"], charset=cfg["charset"])
