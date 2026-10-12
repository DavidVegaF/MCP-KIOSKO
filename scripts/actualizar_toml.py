"""Pone al dia empresas/<emp>.toml con las reglas nuevas (7977 como devolucion, [estacionalidad], [abc]) sin tocar lo demas.

Uso: python3 scripts/actualizar_toml.py korner
"""
import pathlib
import re
import sys

emp = sys.argv[1] if len(sys.argv) > 1 else "korner"
base = pathlib.Path(__file__).resolve().parent.parent / "empresas"
p = base / f"{emp}.toml"
s = p.read_text()
ej = (base / f"{emp}.example.toml").read_text()
s = re.sub(r"conceptos_devolucion\s*=\s*\[[^\]]*\]", "conceptos_devolucion = [7972, 7977]", s)
if "[estacionalidad]" not in s:
    i = ej.index("[estacionalidad]")
    s += "\n" + ej[i:ej.index("# Clase ABC")]
if "[abc]" not in s:
    s += "\n" + ej[ej.index("# Clase ABC"):]
p.write_text(s)
print(f"{p} actualizado")
