#!/usr/bin/env python3
"""Paper trading (órdenes SIMULADAS, señales y precios reales públicos). Uso personal.

  python paper.py run                  # una corrida diaria (idempotente por día UTC)
  python paper.py status               # estado y equity actual
  python paper.py report [--vs-backtest]
  python paper.py rearm --confirmo     # rearme MANUAL del kill switch

Programarlo una vez por día, poco después de las 00:00 UTC (ver README).
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from backtest import SYMBOLS, cargar_datos, run_backtest
from paper_trading.market import BinancePublic
from paper_trading.risk import Limits
from paper_trading import runner


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("cmd", choices=["run", "status", "report", "rearm"])
    p.add_argument("--dir", default="paper_state", help="Carpeta de estado y bitácora")
    p.add_argument("--capital", type=float, default=1000.0, help="Capital inicial simulado (USDT)")
    p.add_argument("--fee", type=float, default=0.001)
    p.add_argument("--vs-backtest", action="store_true")
    p.add_argument("--confirmo", action="store_true", help="Confirmación explícita para rearm")
    a = p.parse_args()
    d = Path(a.dir)
    estado, bitacora = d / "state.json", d / "journal.jsonl"

    if a.cmd == "run":
        r = runner.ejecutar_dia(BinancePublic(), estado, bitacora, Limits(), capital=a.capital, fee=a.fee)
        print(json.dumps(r, indent=2, default=str))
        return 1 if r["status"] == "error" else 0

    if a.cmd == "status":
        broker, meta = runner.cargar_estado(estado, a.capital, a.fee)
        m = BinancePublic()
        mids = {s: m.quote(s).mid for s in SYMBOLS}
        print(json.dumps({"meta": meta, "cash": round(broker.cash, 2), "units": broker.units,
                          "equity_actual": round(broker.equity(mids), 2)}, indent=2))
        return 0

    if a.cmd == "report":
        r = runner.resumen(bitacora)
        print(json.dumps(r, indent=2))
        print(json.dumps(runner.evaluar_etapa1(r), indent=2))
        if a.vs_backtest and r.get("dias_corridos", 0) > 30:
            data = cargar_datos(r["desde"], datetime.now(timezone.utc).date().isoformat(), d / "cache")
            rep, _, _ = run_backtest(data, capital=r["capital_inicial"], fee=a.fee, eval_start=r["desde"],
                                     kill_cooldown_days=None)
            print(f"Backtest misma ventana: {rep['strategy']['total_return_pct']}% | "
                  f"paper: {r['retorno_pct']}% (diferencias chicas son normales; "
                  f"grandes sin explicación = investigar)")
        print("Cumplir los criterios solo habilita la etapa 2; no prueba ventaja.")
        return 0

    if a.cmd == "rearm":
        if not a.confirmo:
            print("Rearmar el kill switch es una decisión manual: revisá por qué saltó y repetí con --confirmo.")
            return 2
        runner.rearmar(estado, bitacora)
        print("Kill switch rearmado; el pico se reinicia en la próxima corrida.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
