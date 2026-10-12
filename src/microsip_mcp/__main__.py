from __future__ import annotations

import argparse

import uvicorn

from .config import load_empresa
from .server import construir_app


def main(argv=None):
    ap = argparse.ArgumentParser(description="MCP de analitica Microsip (HTTP)")
    ap.add_argument("--config", required=True, help="empresas/<empresa>.toml")
    a = ap.parse_args(argv)
    emp = load_empresa(a.config)
    app = construir_app(emp)           # falla aqui si no hay token valido en el entorno
    print(f"[{emp.id}] sirviendo en http://{emp.host}:{emp.port}/<token>/mcp  (token en ${emp.token_env})")
    # access_log=False: la ruta lleva el token y no debe quedar en logs.
    uvicorn.run(app, host=emp.host, port=emp.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
