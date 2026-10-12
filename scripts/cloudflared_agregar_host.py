"""Agrega un hostname al ingress de cloudflared SIN tocar los existentes (respaldo + validacion + reversa).

    python3 scripts/cloudflared_agregar_host.py ~/.cloudflared/config.yml korner.latienditarosa.mx 8101            # simula
    python3 scripts/cloudflared_agregar_host.py ~/.cloudflared/config.yml korner.latienditarosa.mx 8101 --aplicar  # escribe

Despues: `cloudflared tunnel route dns <ID-del-tunel> <hostname>` y reiniciar cloudflared.
"""
from __future__ import annotations

import datetime as dt
import re
import shutil
import subprocess
import sys
from pathlib import Path

CATCH_ALL = re.compile(r"^(\s*)-\s*service:\s*http_status:\d+\s*$")


def insertar(texto: str, hostname: str, puerto: int) -> str:
    lineas = texto.splitlines()
    if any(re.match(rf"^\s*-\s*hostname:\s*{re.escape(hostname)}\s*$", l) for l in lineas):
        raise ValueError(f"{hostname} ya esta en el ingress; no se cambia nada")
    for i in range(len(lineas) - 1, -1, -1):          # la regla final (404) debe seguir al final
        m = CATCH_ALL.match(lineas[i])
        if m:
            sangria = m.group(1)
            bloque = [f"{sangria}- hostname: {hostname}", f"{sangria}  service: http://localhost:{puerto}"]
            return "\n".join(lineas[:i] + bloque + lineas[i:]) + "\n"
    raise ValueError("No encontre la regla final '- service: http_status:404' en el ingress; edita a mano")


def main(argv):
    if len(argv) < 3:
        raise SystemExit(__doc__)
    cfg, host, puerto = Path(argv[0]).expanduser(), argv[1], int(argv[2])
    nuevo = insertar(cfg.read_text(encoding="utf-8"), host, puerto)
    if "--aplicar" not in argv:
        print(nuevo)
        print("(simulacion: no se escribio nada; agrega --aplicar)")
        return 0
    bak = cfg.with_name(cfg.name + ".bak-" + dt.datetime.now().strftime("%Y%m%d%H%M%S"))
    shutil.copy2(cfg, bak)
    cfg.write_text(nuevo, encoding="utf-8")
    exe = shutil.which("cloudflared") or "/opt/homebrew/bin/cloudflared"
    r = subprocess.run([exe, "tunnel", "--config", str(cfg), "ingress", "validate"], capture_output=True, text=True)
    if r.returncode != 0:
        shutil.copy2(bak, cfg)
        print("VALIDACION FALLO, se restauro el archivo original:\n", r.stdout, r.stderr)
        return 1
    print(f"OK. Respaldo en {bak}. Validacion: {r.stdout.strip() or r.stderr.strip()}")
    print(f"Siguiente: cloudflared tunnel route dns <ID-del-tunel> {host}  y reiniciar cloudflared.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
