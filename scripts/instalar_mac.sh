#!/bin/bash
# Instala/actualiza un conector en la Mac: venv, token, servicio launchd. Idempotente.
#   scripts/instalar_mac.sh korner
# No toca el servicio de DTODO (com.dtodo.microsip.http) ni el tunel.
set -euo pipefail
EMP="${1:?uso: instalar_mac.sh <empresa>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-/opt/homebrew/bin/python3.12}"; [ -x "$PY" ] || PY="$(command -v python3)"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
[ -n "${SKIP_PIP:-}" ] || .venv/bin/pip install -q -e '.[etl]'
mkdir -p "data/$EMP/static" "data/$EMP/parquet"

[ -f "empresas/$EMP.toml" ] || { cp "empresas/$EMP.example.toml" "empresas/$EMP.toml"; echo ">> creado empresas/$EMP.toml (revisa public_host)"; }

# token: se crea una sola vez y vive fuera del repo (permisos 600)
ENVF="$HOME/.config/microsip-mcp/$EMP.env"
mkdir -p "$(dirname "$ENVF")"; chmod 700 "$(dirname "$ENVF")"
VAR="MCP_TOKEN_$(printf '%s' "$EMP" | tr '[:lower:]' '[:upper:]')"
if [ ! -f "$ENVF" ]; then
  printf 'export %s=%s\n' "$VAR" "$(.venv/bin/python -c 'import secrets;print(secrets.token_urlsafe(32))')" > "$ENVF"
  chmod 600 "$ENVF"; echo ">> token nuevo en $ENVF"
fi

# servicio launchd (solo en macOS)
PLIST="$HOME/Library/LaunchAgents/com.dtodo.mcp.$EMP.plist"
if [ "$(uname)" = "Darwin" ]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  sed -e "s#/Users/dtodo-mac/microsip-mcp#$ROOT#g" -e "s#EMPRESA#$EMP#g" \
    scripts/launchd/com.dtodo.mcp.EMPRESA.plist > "$PLIST"
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load -w "$PLIST"
  echo ">> servicio com.dtodo.mcp.$EMP cargado"
fi

# datos de la URL (el token solo se muestra en esta terminal; no lo pegues en chats ni commits)
read -r PORT HOSTPUB < <(.venv/bin/python - "$EMP" <<'PY'
import sys, tomllib
c = tomllib.load(open(f"empresas/{sys.argv[1]}.toml", "rb"))
print(c.get("server", {}).get("port", 8101), c.get("server", {}).get("public_host", "<hostname>"))
PY
)
sleep 3
echo ">> salud local: $(curl -s -m 5 "http://127.0.0.1:$PORT/health" || echo 'sin respuesta')"
# shellcheck disable=SC1090
source "$ENVF"
echo ">> URL del conector: https://$HOSTPUB/${!VAR}/mcp"
