"""Resolución mecánica de tesis abiertas con cierres diarios (sin discreción posterior).

Reglas, fijas desde la apertura: se mira el cierre de cada día POSTERIOR a la apertura.
  - cierre <= precio_ref * (1 - stop%)      -> sale por "stop" (al precio de ese cierre, con gap)
  - cierre >= precio_ref * (1 + objetivo%)  -> sale por "objetivo"
  - llegó la fecha de fin                   -> sale por "horizonte"
Se ignoran velas del día de hoy (todavía pueden estar abiertas). Los costos se restan del retorno.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional, Tuple

Serie = List[Tuple[date, float]]


def _ultimo_hasta(serie: Serie, d: date) -> Optional[float]:
    previos = [p for f, p in sorted(serie) if f <= d]
    return previos[-1] if previos else None


def construir_cierre(t: dict, motivo: str, fecha: date, px: float, bench: Serie) -> Optional[dict]:
    b_exit = _ultimo_hasta(bench, fecha)
    if b_exit is None:
        return None  # sin benchmark no se puede resolver con rigor: se reintenta luego
    bruto = (px / t["precio_ref"] - 1) * 100
    neto = bruto - t["costo_ida_vuelta_pct"]
    b_ret = (b_exit / t["bench_ref"] - 1) * 100
    return {"fecha": fecha.isoformat(), "motivo": motivo, "precio_salida": px,
            "retorno_bruto_pct": round(bruto, 3), "retorno_neto_pct": round(neto, 3),
            "bench_retorno_pct": round(b_ret, 3), "exceso_vs_bench_pct": round(neto - b_ret, 3),
            "objetivo_alcanzado": motivo == "objetivo"}


def evaluar(t: dict, cierres: Serie, bench: Serie, now: Optional[datetime] = None) -> Optional[dict]:
    now = now or datetime.now(timezone.utc)
    hoy = now.date()
    apertura, fin = date.fromisoformat(t["fecha_apertura"]), date.fromisoformat(t["fecha_fin"])
    stop = t["precio_ref"] * (1 - t["stop_pct"] / 100)
    objetivo = t["precio_ref"] * (1 + t["objetivo_pct"] / 100)
    for d, px in sorted(cierres):
        if d <= apertura or d >= hoy:
            continue
        motivo = "stop" if px <= stop else "objetivo" if px >= objetivo else "horizonte" if d >= fin else None
        if motivo:
            return construir_cierre(t, motivo, d, px, bench)
    return None


def resolver_todo(cuaderno, precios, now: Optional[datetime] = None) -> List[Tuple[str, dict]]:
    """Cierra lo que corresponda. Devuelve [(id, cierre)]."""
    hechas = []
    for t in cuaderno.abiertas():
        desde = date.fromisoformat(t["fecha_apertura"])
        res = evaluar(t, precios.cierres(t["ticker"], desde), precios.cierres("SPY", desde), now)
        if res:
            cuaderno.cerrar(t["id"], res, now)
            hechas.append((t["id"], res))
    return hechas
