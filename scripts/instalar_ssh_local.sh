#!/bin/bash
# Prepara la entrada ssh local que usa etl_via_ssh.sh (requiere Sesion remota activa en la Mac).
#   scripts/instalar_ssh_local.sh korner
# Crea una llave sin contraseña SOLO para esta empresa y la autoriza con command= y restrict: esa llave unicamente
# puede ejecutar etl_mac.sh <empresa>, nada mas. Luego corre el ETL completo como prueba.
set -eu
EMP="${1:?uso: instalar_ssh_local.sh <empresa>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY="$HOME/.ssh/etl_local_$EMP"
mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
[ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N "" -C "etl_local_$EMP" -f "$KEY"
touch "$HOME/.ssh/authorized_keys" && chmod 600 "$HOME/.ssh/authorized_keys"
if ! grep -q "etl_local_$EMP\$" "$HOME/.ssh/authorized_keys"; then
  echo "restrict,command=\"$ROOT/scripts/etl_mac.sh $EMP\" $(cat "$KEY.pub")" >> "$HOME/.ssh/authorized_keys"
fi
echo "Probando (corre el ETL completo, ~30 s)..."
"$ROOT/scripts/etl_via_ssh.sh" "$EMP"
grep -E 'INICIO|ERROR|FIN|No route' "$ROOT/data/$EMP/etl_last_run.log" | tail -5
