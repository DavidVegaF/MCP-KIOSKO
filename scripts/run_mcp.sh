#!/bin/bash
# Arranca el conector de una empresa leyendo el token de ~/.config/microsip-mcp/<empresa>.env
# (archivo con: export MCP_TOKEN_<EMPRESA>=...  y permisos 600). El token nunca va en el repo ni en logs.
set -euo pipefail
EMP="${1:?uso: run_mcp.sh <empresa>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1090
source "$HOME/.config/microsip-mcp/$EMP.env"
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m microsip_mcp --config "empresas/$EMP.toml"
