"""RiskGuard: límites duros e independientes de la estrategia.

La estrategia propone; el guard dispone. Ningún camino de código envía una orden
sin pasar por `revisar`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from paper_trading.broker import Order, Quote


@dataclass(frozen=True)
class Limits:
    max_order_pct: float = 0.60        # una orden no puede superar este % de la equity
    max_exposure_pct: float = 1.00     # exposición total máxima tras operar
    max_orders_per_run: int = 4
    min_order_usdt: float = 10.0       # menos que esto = polvo, se omite
    max_spread_pct: float = 1.0        # libro con spread mayor = mercado raro, no se opera
    max_dev_vs_open_pct: float = 25.0  # precio muy lejos de la apertura = dato sospechoso
    kill_dd: Optional[float] = 0.15    # drawdown vs pico -> kill switch (rearme MANUAL)
    max_daily_loss: Optional[float] = 0.10  # pérdida entre corridas -> kill switch


def revisar_mercado(quotes: Dict[str, Quote], opens: Dict[str, float], lim: Limits) -> List[str]:
    """Chequeos de cordura de datos. Devuelve motivos de rechazo (vacío = OK)."""
    motivos = []
    for s, q in quotes.items():
        if not (q.bid > 0 and q.ask >= q.bid):
            motivos.append(f"{s}: libro inválido bid={q.bid} ask={q.ask}")
            continue
        if q.spread_pct > lim.max_spread_pct:
            motivos.append(f"{s}: spread {q.spread_pct:.2f}% > {lim.max_spread_pct}%")
        dev = abs(q.mid / opens[s] - 1) * 100
        if dev > lim.max_dev_vs_open_pct:
            motivos.append(f"{s}: precio {dev:.1f}% lejos de la apertura (dato sospechoso)")
    return motivos


def revisar(orders: List[Order], equity: float, units: Dict[str, float],
            mids: Dict[str, float], lim: Limits) -> Tuple[List[Order], List[str], List[str]]:
    """Devuelve (aprobadas, omitidas_por_polvo, rechazos)."""
    aprobadas, polvo, rechazos = [], [], []
    for o in orders:
        notional = o.qty * o.ref_price
        if notional < lim.min_order_usdt:
            polvo.append(f"{o.side} {o.symbol} {notional:.2f} USDT")
        elif o.side == "buy" and notional > lim.max_order_pct * equity:  # vender (reducir riesgo) nunca se bloquea
            rechazos.append(f"{o.side} {o.symbol}: {notional:.2f} > {lim.max_order_pct:.0%} de la equity")
        else:
            aprobadas.append(o)
    if len(aprobadas) > lim.max_orders_per_run:
        rechazos.append(f"{len(aprobadas)} órdenes > máximo {lim.max_orders_per_run}")
        aprobadas = []
    final = dict(units)
    for o in aprobadas:
        final[o.symbol] = final.get(o.symbol, 0.0) + (o.qty if o.side == "buy" else -o.qty)
    expo = sum(max(q, 0) * mids[s] for s, q in final.items())
    if expo > lim.max_exposure_pct * equity * 1.0001:
        rechazos.append(f"exposición {expo / equity:.0%} > {lim.max_exposure_pct:.0%}")
        aprobadas = []
    return aprobadas, polvo, rechazos
