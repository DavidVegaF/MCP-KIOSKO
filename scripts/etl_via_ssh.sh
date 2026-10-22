#!/bin/bash
# Lanza el ETL de una empresa entrando por ssh a esta misma Mac (localhost).
#   scripts/etl_via_ssh.sh korner
# Por que: macOS bloquea el acceso a la red local (Firebird por ZeroTier) a los procesos lanzados por launchd
# ("No route to host"), pero no a los que corren dentro de una sesion ssh. Preparar con scripts/instalar_ssh_local.sh.
set -u
EMP="${1:?uso: etl_via_ssh.sh <empresa>}"
exec /usr/bin/ssh -i "$HOME/.ssh/etl_local_$EMP" -o BatchMode=yes -o IdentitiesOnly=yes \
     -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 "$USER@localhost"
