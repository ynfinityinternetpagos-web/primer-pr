"""Corrida diaria de paper trading: una vez por día UTC, después de las 00:00.

Flujo: datos -> señal (la MISMA del backtest) -> kill switch -> plan de rebalanceo (la MISMA
regla del backtest) -> RiskGuard -> PaperBroker -> estado + bitácora. Una falla de datos aborta
sin tocar el estado; la corrida es idempotente por día.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from backtest import FAST, SLOW, SYMBOLS, make_weights, plan_rebalance, validar_datos
from paper_trading.broker import Order, PaperBroker
from paper_trading.market import MarketData
from paper_trading.risk import Limits, revisar, revisar_mercado

BUFFER_COSTOS = 0.0005  # reserva para spread al dimensionar (el spread real se mide aparte)
SLIPPAGE_MODELADO_PCT = 0.05


# ------------------------------------------------------------------ persistencia
def _escribir_atomico(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)  # nunca queda un estado a medio escribir


def cargar_estado(path: Path, capital: float, fee: float) -> Tuple[PaperBroker, dict]:
    if path.exists():
        d = json.loads(path.read_text())
        return PaperBroker.from_dict(d["broker"]), d["meta"]
    meta = {"inception": None, "initial_capital": capital, "last_run_date": None,
            "last_target": {s: 0.0 for s in SYMBOLS}, "peak": None, "prev_equity": None,
            "killed": False, "kill_reason": None}
    return PaperBroker(capital, fee), meta


def guardar_estado(path: Path, broker: PaperBroker, meta: dict) -> None:
    _escribir_atomico(path, {"broker": broker.to_dict(), "meta": meta})


def journal(path: Path, entrada: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entrada, default=str) + "\n")


def leer_journal(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


# ---------------------------------------------------------------------- corrida
def ejecutar_dia(mercado: MarketData, estado_path: Path, journal_path: Path,
                 limites: Limits = Limits(), now: Optional[datetime] = None,
                 capital: float = 1000.0, fee: float = 0.001, drift_band: float = 0.10,
                 fast: int = FAST, slow: int = SLOW) -> dict:
    now = now or datetime.now(timezone.utc)
    hoy, ts = now.date(), now.isoformat()
    broker, meta = cargar_estado(estado_path, capital, fee)
    if meta["last_run_date"] == hoy.isoformat():
        return {"status": "skipped", "motivo": "ya se corrió hoy (UTC)"}

    # ---- 1. datos (cualquier problema aborta SIN tocar el estado)
    try:
        crudo = {s: mercado.candles(s, hoy) for s in SYMBOLS}
        for s, df in crudo.items():
            validar_datos(df, s)
        closes = pd.concat({s: d["close"] for s, d in crudo.items()}, axis=1).dropna(how="any")
        if closes.index[-1].date() != hoy - timedelta(days=1):
            raise RuntimeError(f"datos desactualizados: última vela {closes.index[-1].date()}")
        if len(closes) < slow + 20:
            raise RuntimeError("historia insuficiente para la SMA lenta")
        quotes = {s: mercado.quote(s) for s in SYMBOLS}
        opens = {s: mercado.day_open(s, hoy) for s in SYMBOLS}
        motivos = revisar_mercado(quotes, opens, limites)
        if motivos:
            raise RuntimeError("mercado sospechoso: " + "; ".join(motivos))
    except Exception as e:
        journal(journal_path, {"ts": ts, "date": hoy.isoformat(), "status": "error", "error": str(e)})
        return {"status": "error", "error": str(e)}

    # ---- 2. estado de la cuenta y kill switch
    mids = {s: quotes[s].mid for s in SYMBOLS}
    equity_pre = broker.equity(mids)
    if meta["inception"] is None:
        meta["inception"] = hoy.isoformat()
    if meta["peak"] is None:
        meta["peak"] = equity_pre
    meta["peak"] = max(meta["peak"], equity_pre)
    dd = equity_pre / meta["peak"] - 1.0
    ultimo = meta["last_run_date"]
    sin_correr = (hoy - date.fromisoformat(ultimo)).days - 1 if ultimo else 0
    if not meta["killed"]:
        if limites.kill_dd is not None and dd <= -limites.kill_dd:
            meta["killed"], meta["kill_reason"] = True, f"drawdown {dd:.1%} desde el pico"
        elif (limites.max_daily_loss is not None and meta["prev_equity"]
              and equity_pre / meta["prev_equity"] - 1 <= -limites.max_daily_loss):
            meta["killed"], meta["kill_reason"] = True, "pérdida diaria sobre el límite"

    # ---- 3. señal y plan (misma lógica que el backtest)
    senal = make_weights(closes[list(SYMBOLS)], fast, slow).iloc[-1].to_numpy(float)
    tgt = np.zeros(len(SYMBOLS)) if meta["killed"] else senal
    units = np.array([broker.units.get(s, 0.0) for s in SYMBOLS])
    px = np.array([mids[s] for s in SYMBOLS])
    last_t = np.array([meta["last_target"][s] for s in SYMBOLS])
    delta = plan_rebalance(tgt, last_t, units, px, broker.cash, fee + BUFFER_COSTOS, drift_band)
    ordenes = []
    if delta is not None:
        for s, d, p in zip(SYMBOLS, delta, px):
            if abs(d) / p > 0:
                ordenes.append(Order(s, "buy" if d > 0 else "sell", abs(d) / p, float(p)))
        ordenes.sort(key=lambda o: o.side != "sell")  # primero se vende (libera efectivo)

    # ---- 4. RiskGuard y ejecución simulada
    aprobadas, polvo, rechazos = revisar(ordenes, equity_pre, broker.units, mids, limites)
    fills, costo_spread, desvio = [], [], []
    for o in aprobadas:
        f = broker.place_order(o, quotes[o.symbol], ts)
        if f:
            fills.append(f.__dict__)
            sg = 1 if f.side == "buy" else -1  # positivo = adverso para nosotros
            costo_spread.append(sg * (f.price / mids[o.symbol] - 1) * 100)   # costo de ejecución (spread)
            desvio.append(sg * (mids[o.symbol] / opens[o.symbol] - 1) * 100)  # precio vs apertura (mercado + demora)
    broker.verificar()
    if delta is not None and not rechazos:
        meta["last_target"] = {s: float(t) for s, t in zip(SYMBOLS, tgt)}  # si se rechazó algo, se reintenta

    equity = broker.equity(mids)
    meta["last_run_date"], meta["prev_equity"] = hoy.isoformat(), equity
    entrada = {
        "ts": ts, "date": hoy.isoformat(), "status": "ok", "equity_pre": equity_pre,
        "equity": equity, "peak": meta["peak"], "drawdown": dd, "senal": dict(zip(SYMBOLS, senal)),
        "targets": dict(zip(SYMBOLS, tgt)), "prices": mids, "day_open": opens,
        "orders": [o.__dict__ for o in aprobadas], "fills": fills, "polvo": polvo,
        "rechazos": rechazos, "costo_spread_pct": costo_spread,
        "desvio_vs_apertura_pct": desvio,
        "min_desde_00utc": now.hour * 60 + now.minute,
        "fees_usdt": sum(f["fee"] for f in fills), "killed": meta["killed"],
        "kill_reason": meta["kill_reason"], "dias_sin_correr": sin_correr,
        "cash": broker.cash, "units": broker.units,
    }
    journal(journal_path, entrada)
    guardar_estado(estado_path, broker, meta)
    return {"status": "ok", **{k: entrada[k] for k in ("equity", "drawdown", "targets", "killed", "rechazos")},
            "n_fills": len(fills)}


def rearmar(estado_path: Path, journal_path: Path, now: Optional[datetime] = None) -> None:
    """Rearme MANUAL del kill switch. El pico se reinicia en la próxima corrida."""
    broker, meta = cargar_estado(estado_path, 1000.0, 0.001)
    if not meta["killed"]:
        raise RuntimeError("El kill switch no está activo")
    previo = meta["kill_reason"]
    meta["killed"], meta["kill_reason"], meta["peak"] = False, None, None
    guardar_estado(estado_path, broker, meta)
    journal(journal_path, {"ts": (now or datetime.now(timezone.utc)).isoformat(),
                           "status": "rearme_manual", "motivo_previo": previo})


# ------------------------------------------------------------------- reporte
def resumen(journal_path: Path) -> dict:
    ent = leer_journal(journal_path)
    oks = [e for e in ent if e["status"] == "ok"]
    errores = [e for e in ent if e["status"] == "error"]
    if not oks:
        return {"dias_corridos": 0, "errores": len(errores)}
    eq = pd.Series([e["equity"] for e in oks], index=[e["date"] for e in oks])
    capital0 = oks[0]["equity_pre"]
    spreads = [x for e in oks for x in e["costo_spread_pct"]]
    desvios = [x for e in oks for x in e["desvio_vs_apertura_pct"]]
    return {
        "desde": oks[0]["date"], "hasta": oks[-1]["date"], "dias_corridos": len(oks),
        "errores": len(errores), "capital_inicial": round(capital0, 2),
        "equity_final": round(float(eq.iloc[-1]), 2),
        "retorno_pct": round((eq.iloc[-1] / capital0 - 1) * 100, 3),
        "max_drawdown_pct": round(float((pd.concat([pd.Series([capital0]), eq.reset_index(drop=True)])
                                         .pipe(lambda x: x / x.cummax() - 1)).min()) * 100, 3),
        "comisiones_usdt": round(sum(e["fees_usdt"] for e in oks), 2),
        "operaciones": sum(len(e["fills"]) for e in oks),
        "slippage_prom_adverso_pct": round(float(np.mean(spreads)), 4) if spreads else None,
        "desvio_prom_vs_apertura_pct": round(float(np.mean(desvios)), 4) if desvios else None,
        "max_retraso_min": max(e["min_desde_00utc"] for e in oks),
        "rechazos_riskguard": sum(len(e["rechazos"]) for e in oks),
        "max_dias_sin_correr": max(e["dias_sin_correr"] for e in oks),
        "kill_switch_activo": oks[-1]["killed"], "kill_motivo": oks[-1]["kill_reason"],
    }


# Criterios de la etapa 1 (DISENO.md). Fijados de antemano; no se mueven al ver resultados.
ETAPA1 = {
    "dias_corridos": (">=", 90),
    "fallas_pct": ("<=", 3.0),
    "max_dias_sin_correr": ("<=", 3),
    "slippage_prom_adverso_pct": ("<=", 2 * SLIPPAGE_MODELADO_PCT),
    "rechazos_riskguard": ("==", 0),
    "max_retraso_min": ("<=", 120),  # el backtest supone ejecutar en la apertura: no correr tarde
}


def evaluar_etapa1(r: dict) -> dict:
    corridas = r.get("dias_corridos", 0) + r.get("errores", 0)
    valores = {
        "dias_corridos": r.get("dias_corridos", 0),
        "fallas_pct": round(100 * r.get("errores", 0) / corridas, 2) if corridas else None,
        "max_dias_sin_correr": r.get("max_dias_sin_correr"),
        "slippage_prom_adverso_pct": r.get("slippage_prom_adverso_pct"),
        "rechazos_riskguard": r.get("rechazos_riskguard"),
        "max_retraso_min": r.get("max_retraso_min"),
    }
    out = {}
    for k, v in valores.items():
        op, lim = ETAPA1[k]
        ok = v is not None and {">=": v >= lim, "<=": v <= lim, "==": v == lim}[op]
        out[k] = {"valor": v, "criterio": f"{op} {lim}", "ok": bool(ok)}
    return out
