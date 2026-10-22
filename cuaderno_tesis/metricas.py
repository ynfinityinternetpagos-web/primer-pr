"""Métricas del cuaderno y criterios para decidir si hay evidencia de ventaja.

Fijados de antemano (no se mueven al ver resultados). Superarlos NO prueba ventaja: solo
habilita considerar posiciones reales mínimas, con los límites de tamaño del cuaderno.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

N_MIN_CERRADAS = 50
BRIER_MAX = 0.25  # 0.25 = siempre decir 50%; hay que calibrar mejor que eso

GATES = {
    "cerradas": (">=", N_MIN_CERRADAS),
    "exceso_vs_bench_prom_pct": (">", 0.0),
    "exceso_ic90_inferior_pct": (">", 0.0),
    "brier": ("<=", BRIER_MAX),
}


def _ic90_media(x: np.ndarray, n_boot: int = 5000) -> Optional[tuple]:
    if len(x) < 10:
        return None
    rng = np.random.default_rng(0)
    medias = rng.choice(x, size=(n_boot, len(x)), replace=True).mean(axis=1)
    return float(np.percentile(medias, 5)), float(np.percentile(medias, 95))


def _resumen(cerradas: List[dict]) -> Dict:
    if not cerradas:
        return {"cerradas": 0}
    neto = np.array([t["cierre"]["retorno_neto_pct"] for t in cerradas])
    exceso = np.array([t["cierre"]["exceso_vs_bench_pct"] for t in cerradas])
    hit = np.array([1.0 if t["cierre"]["objetivo_alcanzado"] else 0.0 for t in cerradas])
    prob = np.array([t["prob_exito"] / 100 for t in cerradas])
    ic = _ic90_media(exceso)
    return {
        "cerradas": len(cerradas),
        "aciertos_objetivo_pct": round(float(hit.mean()) * 100, 1),
        "retorno_neto_prom_pct": round(float(neto.mean()), 3),
        "retorno_neto_mediana_pct": round(float(np.median(neto)), 3),
        "peor_jugada_pct": round(float(neto.min()), 3),
        "exceso_vs_bench_prom_pct": round(float(exceso.mean()), 3),
        "exceso_ic90_inferior_pct": round(ic[0], 3) if ic else None,
        "exceso_ic90_superior_pct": round(ic[1], 3) if ic else None,
        "brier": round(float(((prob - hit) ** 2).mean()), 4),
        "prob_prom_declarada_pct": round(float(prob.mean()) * 100, 1),
    }


def reporte(tesis: Dict[str, dict]) -> Dict:
    todas = list(tesis.values())
    cerradas = [t for t in todas if t["estado"] == "cerrada"]
    abiertas = [t for t in todas if t["estado"] == "abierta"]
    out = {
        "abiertas": len(abiertas),
        "exposicion_abierta_pct": round(sum(t["tamano_pct"] for t in abiertas), 2),
        "total": _resumen(cerradas),
        "por_autor": {a: _resumen([t for t in cerradas if t["autor"] == a]) for a in ("yo", "claude")},
    }
    if len(cerradas) < 30:
        out["aviso"] = (f"Solo {len(cerradas)} jugadas cerradas: con tan pocas, aciertos y retornos son "
                        "mayormente suerte. No saques conclusiones antes de ~50.")
    return out


def evaluar_gates(total: Dict) -> Dict:
    out = {}
    for k, (op, lim) in GATES.items():
        v = total.get(k)
        ok = v is not None and (v >= lim if op == ">=" else v > lim if op == ">" else v <= lim)
        out[k] = {"valor": v, "criterio": f"{op} {lim}", "ok": bool(ok)}
    return out
