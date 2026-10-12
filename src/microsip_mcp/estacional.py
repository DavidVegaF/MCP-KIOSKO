"""Factor de estacionalidad: re-estacionaliza la demanda base (ultimos 90 dias) hacia el horizonte de compra.

El indice mensual (1.0 = mes normal) viene de la tabla `estacionalidad_mes`, que se llena desde `[estacionalidad]` del toml.
No se aprende de la venta de ruta (la ruta formal tiene pocos meses de historia): ver docs/DISENO-RUTA.md.
"""
from __future__ import annotations

from datetime import date, timedelta


def indice_medio(indices: dict[int, float], desde: date, dias: int) -> float:
    """Indice promedio de los `dias` dias que empiezan en `desde` (cada dia toma el indice de su mes)."""
    if dias <= 0:
        raise ValueError("dias debe ser > 0")
    return sum(indices.get((desde + timedelta(days=i)).month, 1.0) for i in range(dias)) / dias


def factor_estacional(indices: dict[int, float], hoy: date, horizonte_dias: int,
                      piso: float = 0.5, techo: float = 2.0) -> tuple[float, float, float]:
    """(factor, indice_horizonte, indice_base).

    base = misma ponderacion 50/30/20 de las ventanas 0-30, 31-60 y 61-90 dias atras (contra la fecha de corte);
    horizonte = los `horizonte_dias` dias siguientes. factor = horizonte / base, acotado a [piso, techo]."""
    base = (0.5 * indice_medio(indices, hoy - timedelta(days=29), 30)
            + 0.3 * indice_medio(indices, hoy - timedelta(days=59), 30)
            + 0.2 * indice_medio(indices, hoy - timedelta(days=89), 30))
    horizonte = indice_medio(indices, hoy + timedelta(days=1), horizonte_dias)
    f = horizonte / base if base > 0 else 1.0
    return max(piso, min(techo, f)), horizonte, base
