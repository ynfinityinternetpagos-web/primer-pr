#!/usr/bin/env python3
"""Backtest de investigación para cripto spot (BTC/ETH). No contiene código de órdenes.

Modelo de ejecución (v2):
  - La señal se calcula con el cierre del día t-1.
  - La orden se ejecuta a la APERTURA del día t, pagando comisión + slippage.
  - Se simula cartera real (efectivo + unidades), así que los pesos se desvían con
    los precios y se rebalancea (con costo) solo si la señal cambia o el desvío
    supera `drift_band`.
  - Estrategia y benchmark usan el mismo motor, costos y ventana de evaluación.
  - Kill switch: si el drawdown al cierre llega a `kill_dd`, se liquida todo en la
    apertura siguiente (con costo) y se queda en efectivo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd
import requests

SYMBOLS = ("BTCUSDT", "ETHUSDT")
# data-api.binance.vision sirve datos públicos y no se bloquea por región como api.binance.com.
BASE_URLS = (
    "https://data-api.binance.vision/api/v3/klines",
    "https://api.binance.com/api/v3/klines",
)
INTERVAL = "1d"
COLUMNS = ["open_time", "open", "high", "low", "close", "volume",
           "close_time", "quote_volume", "trades", "taker_base",
           "taker_quote", "ignore"]
FAST, SLOW, MAX_WEIGHT, KILL_DD = 50, 200, 0.50, 0.15
KILL_COOLDOWN_DAYS = 30  # None = permanente (en vivo: revisión manual obligatoria)
WARMUP_DAYS = 260  # historia extra que se descarga antes de la fecha de inicio


# ----------------------------------------------------------------- datos
def _fetch(url: str, symbol: str, start_ms: int, end_ms: int) -> list:
    rows, cursor = [], start_ms
    session = requests.Session()
    while cursor < end_ms:
        response = session.get(
            url,
            params={"symbol": symbol, "interval": INTERVAL, "startTime": cursor,
                    "endTime": end_ms - 1, "limit": 1000},
            timeout=20,
        )
        response.raise_for_status()
        batch = response.json()
        if not batch:
            break
        rows.extend(batch)
        next_cursor = int(batch[-1][0]) + 86_400_000
        if next_cursor <= cursor:
            raise RuntimeError(f"La paginación dejó de avanzar para {symbol}")
        cursor = next_cursor
        if len(batch) < 1000:
            break
        time.sleep(0.15)
    return rows


def download_klines(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Velas diarias públicas; fechas UTC, `end` exclusivo. Descarta la vela aún abierta."""
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)
    last_error: Optional[Exception] = None
    rows: list = []
    for url in BASE_URLS:
        try:
            rows = _fetch(url, symbol, start_ms, end_ms)
            break
        except requests.RequestException as exc:
            last_error = exc
    else:
        raise RuntimeError(f"No se pudo descargar {symbol}: {last_error}")
    if not rows:
        raise RuntimeError(f"Sin velas para {symbol} entre {start} y {end}")
    df = pd.DataFrame(rows, columns=COLUMNS)
    now_ms = int(time.time() * 1000)
    df = df[pd.to_numeric(df["close_time"]) < now_ms]  # solo velas cerradas
    df["date"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.floor("D")
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="raise")
    df = df.set_index("date")[["open", "high", "low", "close", "volume"]]
    return df[~df.index.duplicated(keep="last")].sort_index()


def validar_datos(df: pd.DataFrame, nombre: str) -> None:
    """Falla fuerte ante datos sospechosos: preferimos no correr a correr con basura."""
    if df.isna().any().any():
        raise ValueError(f"{nombre}: hay valores faltantes")
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError(f"{nombre}: hay precios no positivos")
    if (df["high"] < df["low"]).any():
        raise ValueError(f"{nombre}: high < low en alguna vela")
    if df.index.has_duplicates or not df.index.is_monotonic_increasing:
        raise ValueError(f"{nombre}: índice duplicado o desordenado")
    saltos = df.index.to_series().diff().dropna()
    if (saltos != pd.Timedelta(days=1)).any():
        raise ValueError(f"{nombre}: faltan días (cripto opera 24/7, no debería haber huecos)")


def cargar_datos(start: str, end: str, cache_dir: Optional[Path] = None,
                 usar_cache: bool = False) -> Dict[str, pd.DataFrame]:
    """Descarga desde `start - WARMUP_DAYS` para que las SMA estén listas al evaluar."""
    desde = (pd.Timestamp(start, tz="UTC") - pd.Timedelta(days=WARMUP_DAYS)).date().isoformat()
    data = {}
    for s in SYMBOLS:
        archivo = cache_dir / f"{s}_{desde}_{end}.csv" if cache_dir else None
        if archivo and usar_cache and archivo.exists():
            df = pd.read_csv(archivo, index_col="date", parse_dates=True)
            df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
        else:
            df = download_klines(s, desde, end)
            if archivo:
                archivo.parent.mkdir(parents=True, exist_ok=True)
                df.to_csv(archivo, index_label="date")
        data[s] = df
    return data


def hash_datos(data: Dict[str, pd.DataFrame]) -> str:
    h = hashlib.sha256()
    for s in sorted(data):
        h.update(s.encode())
        h.update(pd.util.hash_pandas_object(data[s], index=True).values.tobytes())
    return h.hexdigest()


# ----------------------------------------------------------------- señal
def make_weights(close: pd.DataFrame, fast: int = FAST, slow: int = SLOW,
                 max_weight: float = MAX_WEIGHT) -> pd.DataFrame:
    """Pesos objetivo derivados del cierre del día t (el llamador debe desplazarlos 1 barra)."""
    sma_f = close.rolling(fast, min_periods=fast).mean()
    sma_s = close.rolling(slow, min_periods=slow).mean()
    raw = ((close > sma_s) & (sma_f > sma_s)).astype(float)
    counts = raw.sum(axis=1).replace(0, np.nan)
    weights = raw.div(counts, axis=0).fillna(0.0)
    return weights.clip(upper=max_weight)  # lo no asignado queda en efectivo


# ------------------------------------------------------------- simulación
def plan_rebalance(tgt: np.ndarray, last_target: np.ndarray, units: np.ndarray, px: np.ndarray,
                   cash: float, cost_rate: float, drift_band: float) -> Optional[np.ndarray]:
    """Regla única de rebalanceo (la usan el backtest y el paper trading).
    Devuelve el cambio de posición en USDT por activo, o None si no hay que operar.
    Rebalancea si cambia el objetivo o el desvío supera `drift_band`."""
    held = units * px
    v = cash + held.sum()
    cur_w = held / v if v > 0 else np.zeros(len(tgt))
    if not ((np.abs(tgt - last_target) > 1e-12).any() or (np.abs(cur_w - tgt) > drift_band).any()):
        return None
    v_eff = v - cost_rate * np.abs(tgt * v - held).sum()  # reserva para costos
    return tgt * v_eff - held


def simulate(opens: pd.DataFrame, closes: pd.DataFrame, targets: pd.DataFrame,
             capital: float, fee: float, slippage: float,
             drift_band: float = 0.10, kill_dd: Optional[float] = None,
             kill_cooldown_days: Optional[int] = None) -> pd.DataFrame:
    """Cartera con efectivo y unidades. `targets[t]` = pesos decididos al cierre t-1."""
    cost_rate = fee + slippage
    cols = list(closes.columns)
    n = len(cols)
    cash, peak = float(capital), float(capital)
    units, last_target = np.zeros(n), np.zeros(n)
    killed, resume_i = False, 0
    rows = []
    for i, date in enumerate(closes.index):
        o = opens.loc[date].to_numpy(float)
        c = closes.loc[date].to_numpy(float)
        if killed and kill_cooldown_days is not None and i >= resume_i:
            killed = False                      # fin del enfriamiento: se rearma el kill switch
            peak = cash + float((units * o).sum())  # con un pico nuevo (ya estamos en efectivo)
        tgt = np.zeros(n) if killed else targets.loc[date].to_numpy(float)
        turnover = cost = 0.0
        delta = plan_rebalance(tgt, last_target, units, o, cash, cost_rate, drift_band)
        if delta is not None:
            turnover = float(np.abs(delta).sum())
            cost = turnover * cost_rate
            cash -= float(delta.sum()) + cost
            units = units + delta / o
            last_target = tgt
        v_close = cash + float((units * c).sum())
        peak = max(peak, v_close)
        dd = v_close / peak - 1.0
        if kill_dd is not None and not killed and dd <= -kill_dd:
            killed = True  # se liquida en la apertura de la barra siguiente
            resume_i = i + 1 + (kill_cooldown_days or 0)
        row = {"date": date, "equity": v_close, "turnover_usdt": turnover, "cost_usdt": cost,
               "drawdown": dd, "kill_switch_active": killed,
               "exposure": (units * c).sum() / v_close if v_close > 0 else 0.0}
        row.update({f"w_{s}": float(u * px / v_close) if v_close > 0 else 0.0
                    for s, u, px in zip(cols, units, c)})
        rows.append(row)
    return pd.DataFrame(rows).set_index("date")


def calculate_metrics(log: pd.DataFrame, capital: float) -> Dict:
    equity = log["equity"]
    if len(equity) < 2:
        raise ValueError("Pocas observaciones para calcular métricas")
    rets = equity.pct_change()
    rets.iloc[0] = equity.iloc[0] / capital - 1.0
    total_return = float(equity.iloc[-1] / capital - 1)
    years = len(equity) / 365.0
    cagr = float((equity.iloc[-1] / capital) ** (1 / years) - 1) if equity.iloc[-1] > 0 else -1.0
    full = pd.concat([pd.Series([float(capital)]), equity.reset_index(drop=True)])
    max_dd = float((full / full.cummax() - 1).min())
    vol = float(rets.std(ddof=1) * np.sqrt(365))
    sharpe = float(rets.mean() * 365 / vol) if vol > 0 else None
    return {
        "start": str(equity.index[0].date()), "end": str(equity.index[-1].date()),
        "observations": int(len(equity)),
        "ending_equity_usdt": round(float(equity.iloc[-1]), 2),
        "total_return_pct": round(total_return * 100, 3), "cagr_pct": round(cagr * 100, 3),
        "max_drawdown_pct": round(max_dd * 100, 3),
        "annualized_volatility_pct": round(vol * 100, 3),
        "sharpe_rf0_annualized": round(sharpe, 3) if sharpe is not None else None,
        "trade_events": int((log["turnover_usdt"] > 1e-9).sum()),
        "cumulative_turnover_usdt": round(float(log["turnover_usdt"].sum()), 2),
        "total_costs_usdt": round(float(log["cost_usdt"].sum()), 2),
        "avg_exposure_pct": round(float(log["exposure"].mean()) * 100, 2),
    }


def run_backtest(data: Dict[str, pd.DataFrame], capital: float = 1000.0, fee: float = 0.001,
                 slippage: float = 0.0005, eval_start: Optional[str] = None,
                 eval_end: Optional[str] = None, fast: int = FAST, slow: int = SLOW,
                 kill_dd: Optional[float] = KILL_DD, drift_band: float = 0.10,
                 kill_cooldown_days: Optional[int] = KILL_COOLDOWN_DAYS):
    """Devuelve (reporte, log_estrategia, log_benchmark)."""
    if capital <= 0 or fee < 0 or slippage < 0 or fast >= slow:
        raise ValueError("Capital positivo, costos no negativos y fast < slow")
    for s, d in data.items():
        validar_datos(d, s)
    closes = pd.concat({s: d["close"] for s, d in data.items()}, axis=1).sort_index().dropna(how="any")
    opens = pd.concat({s: d["open"] for s, d in data.items()}, axis=1).reindex(closes.index)
    if len(closes) < slow + 20:
        raise ValueError(f"Se necesitan al menos {slow + 20} velas diarias superpuestas")

    # Señal de t-1 -> ejecución en la apertura de t. Primera barra sin señal = efectivo.
    targets = make_weights(closes, fast, slow).shift(1).fillna(0.0)

    start_pos = slow  # primera barra con SMA lenta ya calculada en t-1
    if eval_start is not None:
        start_pos = int(closes.index.searchsorted(pd.Timestamp(eval_start, tz="UTC")))
        if start_pos < slow:
            raise ValueError(f"eval_start requiere al menos {slow} días de historia previa "
                             f"(hay {start_pos}); descargá más historia")
    end_pos = len(closes)
    if eval_end is not None:
        end_pos = int(closes.index.searchsorted(pd.Timestamp(eval_end, tz="UTC")))
    if end_pos - start_pos < 30:
        raise ValueError("Ventana de evaluación demasiado corta (< 30 días)")
    sl = slice(start_pos, end_pos)
    o, c, t = opens.iloc[sl], closes.iloc[sl], targets.iloc[sl]

    strat = simulate(o, c, t, capital, fee, slippage, drift_band, kill_dd, kill_cooldown_days)
    bench_targets = pd.DataFrame(1.0 / closes.shape[1], index=c.index, columns=c.columns)
    bench = simulate(o, c, bench_targets, capital, fee, slippage, drift_band, None)

    report = {
        "configuration": {
            "capital_usdt": capital, "symbols": list(data.keys()), "interval": "1d",
            "fee_pct_per_trade": fee * 100, "slippage_pct_per_trade": slippage * 100,
            "sma_fast": fast, "sma_slow": slow, "max_weight_per_asset": MAX_WEIGHT,
            "execution": "señal al cierre t-1, ejecución en apertura t, costos sobre lo operado",
            "rebalance": f"solo si cambia la señal o el desvío supera {drift_band:.0%}",
            "kill_switch_drawdown_pct": None if kill_dd is None else kill_dd * 100,
            "kill_switch_cooldown_days": kill_cooldown_days,
            "eval_window": [str(c.index[0].date()), str(c.index[-1].date())],
            "data_sha256": hash_datos(data),
            "real_orders_enabled": False,
        },
        "strategy": calculate_metrics(strat, capital),
        "benchmark_50_50": calculate_metrics(bench, capital),
        "risk_note": "El kill switch se evalúa al cierre y liquida en la apertura siguiente; "
                     "los gaps pueden exceder el límite.",
    }
    return report, strat, bench


# ------------------------------------------------------------------- CLI
LOG_EXPERIMENTOS = Path(__file__).resolve().parent / "experiments_log" / "experiments.jsonl"


def _registrar_experimento(report: Dict) -> int:
    """Bitácora ÚNICA de TODAS las corridas sobre datos reales (versionada en git):
    cuantas más variantes se prueban, menos vale la mejor."""
    archivo = LOG_EXPERIMENTOS
    archivo.parent.mkdir(parents=True, exist_ok=True)
    previas = sum(1 for _ in archivo.open()) if archivo.exists() else 0
    entrada = {"ts": datetime.now(timezone.utc).isoformat(), "config": report["configuration"],
               "strategy": report["strategy"]}
    with archivo.open("a") as f:
        f.write(json.dumps(entrada) + "\n")
    return previas + 1


def main():
    from robustness import robustez

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--start", default="2021-01-01", help="Inicio de la evaluación (UTC)")
    p.add_argument("--end", default=pd.Timestamp.now(tz="UTC").date().isoformat(),
                   help="Fin exclusivo (UTC)")
    p.add_argument("--capital", type=float, default=1000.0)
    p.add_argument("--fee", type=float, default=0.001, help="0.001 = 0.10%%")
    p.add_argument("--slippage", type=float, default=0.0005, help="0.0005 = 0.05%%")
    p.add_argument("--out", default="results")
    p.add_argument("--cache-dir", default="data_cache")
    p.add_argument("--use-cache", action="store_true", help="Reusar datos descargados")
    p.add_argument("--robustness", action="store_true",
                   help="Walk-forward, sensibilidad a costos/parámetros y criterios de aprobación")
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        data = cargar_datos(args.start, args.end, Path(args.cache_dir), args.use_cache)
    except Exception as exc:
        raise SystemExit(f"No se pudieron obtener las velas públicas. No se corrió nada. Detalle: {exc}")

    kw = dict(capital=args.capital, fee=args.fee, slippage=args.slippage, eval_start=args.start)
    report, strat, bench = run_backtest(data, **kw)
    report["experiment_number"] = _registrar_experimento(report)
    (out / "metrics.json").write_text(json.dumps(report, indent=2))
    pd.concat([strat["equity"].rename("strategy_equity"),
               bench["equity"].rename("benchmark_equity")], axis=1).to_csv(out / "equity_curve.csv", index_label="date")
    strat.to_csv(out / "trades.csv", index_label="date")
    print(json.dumps(report, indent=2))

    if args.robustness:
        rob = robustez(data, **kw)
        (out / "robustness.json").write_text(json.dumps(rob, indent=2, default=str))
        print(json.dumps(rob["gates"], indent=2))
        print("CRITERIOS:", "CUMPLIDOS" if rob["aprobado"] else "NO CUMPLIDOS",
              "(cumplirlos solo habilita pasar a paper trading; no prueba ventaja)")
    print(f"Resultados en: {out.resolve()}")


if __name__ == "__main__":
    main()
