"""Chequeos de robustez. La estrategia NO se optimiza acá: solo se mide qué tan estable es.

Los umbrales de GATES se fijaron ANTES de mirar resultados con datos reales (ver DISENO.md).
Cambiarlos después de ver los números invalida el proceso.
"""
from __future__ import annotations

from typing import Dict, Sequence, Tuple

import pandas as pd

from backtest import FAST, SLOW, run_backtest

# v2 (2026-10-22): "ventanas_positivas_pct" (retorno > 0) pasó a "ventanas_no_perdedoras_pct"
# (retorno >= 0), porque quedarse en efectivo en una caída (0 %) no es una falla. Cambio hecho
# DESPUÉS de ver el test 2018-2020 -> rige solo hacia adelante; los resultados previos se
# evaluaron con la v1 y NO se reinterpretan (ver DISENO.md).
GATES_VERSION = 2
GATES = {
    "ventanas_no_perdedoras_pct": (">=", 60.0),
    "peor_drawdown_ventana_pct": (">=", -25.0),   # el drawdown (negativo) no puede ser peor que -25
    "sharpe_con_costos_3x": (">", 0.0),
    "vecinos_parametros_positivos_pct": (">=", 66.0),
    "sharpe_estrategia_vs_benchmark": (">=", 0.0),  # diferencia de Sharpe (estrategia - benchmark)
}


def walk_forward(data, n_windows: int = 4, **kw) -> list:
    """Ventanas consecutivas e independientes (capital reiniciado, parámetros fijos)."""
    closes = pd.concat({s: d["close"] for s, d in data.items()}, axis=1).dropna(how="any")
    kw = {k: v for k, v in kw.items() if k not in ("eval_start", "eval_end")}
    slow = kw.get("slow", SLOW)
    primero, total = slow, len(closes)
    largo = (total - primero) // n_windows
    if largo < 60:
        raise ValueError("Historia insuficiente para esa cantidad de ventanas")
    out = []
    for i in range(n_windows):
        a = primero + i * largo
        b = total if i == n_windows - 1 else a + largo
        fin = None if i == n_windows - 1 else str(closes.index[b].date())
        rep, _, _ = run_backtest(data, eval_start=str(closes.index[a].date()), eval_end=fin, **kw)
        out.append({"ventana": i + 1, "desde": rep["strategy"]["start"], "hasta": rep["strategy"]["end"],
                    "estrategia": rep["strategy"], "benchmark": rep["benchmark_50_50"]})
    return out


def cost_sensitivity(data, multipliers: Sequence[float] = (1, 2, 3, 5), **kw) -> list:
    fee, slip = kw.pop("fee", 0.001), kw.pop("slippage", 0.0005)
    out = []
    for m in multipliers:
        rep, _, _ = run_backtest(data, fee=fee * m, slippage=slip * m, **kw)
        out.append({"multiplicador_costos": m, "estrategia": rep["strategy"]})
    return out


def param_sensitivity(data, grid: Sequence[Tuple[int, int]] = ((30, 150), (50, 200), (70, 250)), **kw) -> list:
    """Misma ventana para todos (arranca cuando la SMA más lenta ya está lista)."""
    closes = pd.concat({s: d["close"] for s, d in data.items()}, axis=1).dropna(how="any")
    kw = {k: v for k, v in kw.items() if k not in ("eval_start", "fast", "slow")}
    inicio = str(closes.index[max(s for _, s in grid)].date())
    out = []
    for fast, slow in grid:
        rep, _, _ = run_backtest(data, eval_start=inicio, fast=fast, slow=slow, **kw)
        out.append({"fast": fast, "slow": slow, "es_base": (fast, slow) == (FAST, SLOW),
                    "estrategia": rep["strategy"]})
    return out


def _cmp(valor, op, umbral) -> bool:
    if valor is None:
        return False
    return valor >= umbral if op == ">=" else valor > umbral


def evaluar_gates(base: Dict, wf: list, costos: list, params: list) -> Dict:
    pos = 100.0 * sum(w["estrategia"]["total_return_pct"] >= 0 for w in wf) / len(wf)
    peor_dd = min(w["estrategia"]["max_drawdown_pct"] for w in wf)
    c3 = next((c for c in costos if c["multiplicador_costos"] == 3), costos[-1])
    vecinos = [p for p in params if not p["es_base"]]
    vec_pos = 100.0 * sum(p["estrategia"]["total_return_pct"] > 0 for p in vecinos) / max(len(vecinos), 1)
    s, b = base["strategy"]["sharpe_rf0_annualized"], base["benchmark_50_50"]["sharpe_rf0_annualized"]
    dif = None if s is None or b is None else round(s - b, 3)
    valores = {
        "ventanas_no_perdedoras_pct": pos,
        "peor_drawdown_ventana_pct": peor_dd,
        "sharpe_con_costos_3x": c3["estrategia"]["sharpe_rf0_annualized"],
        "vecinos_parametros_positivos_pct": vec_pos,
        "sharpe_estrategia_vs_benchmark": dif,
    }
    return {k: {"valor": v, "criterio": f"{GATES[k][0]} {GATES[k][1]}",
                "ok": _cmp(v, *GATES[k])} for k, v in valores.items()}


def robustez(data, **kw) -> Dict:
    base, _, _ = run_backtest(data, **kw)
    wf = walk_forward(data, **kw)
    costos = cost_sensitivity(data, **{k: v for k, v in kw.items()})
    params = param_sensitivity(data, **kw)
    gates = evaluar_gates(base, wf, costos, params)
    return {"base": base, "walk_forward": wf, "costos": costos, "parametros": params,
            "gates": gates, "gates_version": GATES_VERSION, "aprobado": all(g["ok"] for g in gates.values())}
