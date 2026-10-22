import importlib.util
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("cf", RAIZ / "scripts" / "cloudflared_agregar_host.py")
cf = importlib.util.module_from_spec(spec); spec.loader.exec_module(cf)

CONFIG_REAL = """tunnel: 35308fcd-0000-0000-0000-000000000000
credentials-file: /Users/x/.cloudflared/35308fcd.json
ingress:
  - hostname: microsip.latienditarosa.mx
    service: http://localhost:8899
  - service: http_status:404
"""


def test_agrega_antes_del_404_y_conserva_lo_existente():
    out = cf.insertar(CONFIG_REAL, "korner.latienditarosa.mx", 8101)
    lineas = out.splitlines()
    assert lineas[-1] == "  - service: http_status:404"
    assert "  - hostname: microsip.latienditarosa.mx" in lineas and "    service: http://localhost:8899" in lineas
    i = lineas.index("  - hostname: korner.latienditarosa.mx")
    assert lineas[i + 1] == "    service: http://localhost:8101" and i < len(lineas) - 1
    assert out.startswith("tunnel: ") and "credentials-file:" in out


def test_no_duplica_ni_inventa():
    out = cf.insertar(CONFIG_REAL, "korner.latienditarosa.mx", 8101)
    with pytest.raises(ValueError, match="ya esta"):
        cf.insertar(out, "korner.latienditarosa.mx", 8101)
    with pytest.raises(ValueError, match="regla final"):
        cf.insertar("ingress:\n  - hostname: a.b\n    service: http://localhost:1\n", "k.b", 2)


def test_simulacion_no_escribe(tmp_path):
    f = tmp_path / "config.yml"; f.write_text(CONFIG_REAL)
    assert cf.main([str(f), "korner.latienditarosa.mx", "8101"]) == 0
    assert f.read_text() == CONFIG_REAL


def test_scripts_bash_con_sintaxis_valida():
    for s in ("rebuild.sh", "run_mcp.sh", "instalar_mac.sh", "etl_mac.sh", "etl_via_ssh.sh", "instalar_ssh_local.sh"):
        assert subprocess.run(["bash", "-n", str(RAIZ / "scripts" / s)]).returncode == 0, s
