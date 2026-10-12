"""Configuracion por empresa (TOML). Cada conector es una instancia con su propio archivo."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Empresa:
    id: str
    nombre: str
    perfil: str                      # "ruta" (camionetas/kioscos); "dtodo" llega con el codigo original
    duckdb_path: Path
    host: str = "127.0.0.1"
    port: int = 8101
    public_host: str = ""            # host publico (Tailscale Funnel) para validar el header Host
    token_env: str = "MCP_TOKEN"
    filas_visibles: int = 200
    filas_sql: int = 2000
    reglas: dict = field(default_factory=dict)

    @property
    def token(self) -> str:
        tok = os.environ.get(self.token_env, "").strip()
        if len(tok) < 24:
            raise RuntimeError(
                f"Define la variable de entorno {self.token_env} con un token de al menos 24 caracteres "
                "(ej. python -c \"import secrets;print(secrets.token_urlsafe(32))\")."
            )
        return tok


def load_empresa(path: str | Path) -> Empresa:
    path = Path(path)
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    emp, ddb, srv = raw["empresa"], raw["duckdb"], raw.get("server", {})
    lim = raw.get("limites", {})
    base = path.parent.parent if path.parent.name == "empresas" else path.parent
    dpath = Path(ddb["path"])
    if not dpath.is_absolute():
        dpath = base / dpath
    return Empresa(
        id=emp["id"],
        nombre=emp["nombre"],
        perfil=emp.get("perfil", "ruta"),
        duckdb_path=dpath,
        host=srv.get("host", "127.0.0.1"),
        port=int(srv.get("port", 8101)),
        public_host=srv.get("public_host", ""),
        token_env=srv.get("token_env", f"MCP_TOKEN_{emp['id'].upper()}"),
        filas_visibles=int(lim.get("filas_visibles", 200)),
        filas_sql=int(lim.get("filas_sql", 2000)),
        reglas=raw.get("reglas", {}),
    )
