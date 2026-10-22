# Crypto Spot Backtest (BTC/USDT + ETH/USDT)

Backtest diario de **solo investigación**: no contiene código de órdenes ni manejo de claves.
Leé `DISENO.md` antes de pensar en dinero real.

## Estrategia (baseline v2)
- Velas diarias BTC/ETH, largo solo, sin apalancamiento ni shorts.
- Activo elegible si `close > SMA200` y `SMA50 > SMA200`; los elegibles se reparten el capital
  en partes iguales (tope 50 % por activo, el resto queda en efectivo).
- **Señal al cierre t-1, ejecución a la apertura t**, con comisión 0,10 % + slippage 0,05 %.
- Cartera simulada con efectivo y unidades: los pesos se desvían con el precio y se rebalancea
  (con costo) si cambia la señal o el desvío supera 10 %.
- Kill switch: drawdown de cierre ≥ 15 % -> liquida en la apertura siguiente (con costo), 30 días
  en efectivo, luego se rearma con pico nuevo.
- Benchmark: 50/50 BTC/ETH con el **mismo motor, costos y ventana**.
- La descarga incluye 260 días previos para que las SMA estén listas al empezar a evaluar.

## Uso
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q
python backtest.py --start 2021-01-01 --end 2026-10-15 --robustness
```
Opciones: `--fee`, `--slippage`, `--capital`, `--use-cache` (reusa datos descargados),
`--out`, `--cache-dir`. Datos: endpoint público de Binance (`data-api.binance.vision`, con
respaldo en `api.binance.com`); sin clave.

Salidas en `results/`: `metrics.json`, `equity_curve.csv`, `trades.csv` (log diario simulado),
`robustness.json` (con `--robustness`) y `experiments.jsonl` (bitácora de todas las corridas).

## Robustez (`robustness.py`)
Walk-forward en ventanas independientes, sensibilidad a costos (x1, x2, x3, x5) y a parámetros
vecinos (30/150, 50/200, 70/250) y 5 criterios de aprobación fijados de antemano.
**No optimiza nada**: solo mide estabilidad. Cumplir los criterios no prueba ventaja.

## Cambios respecto al prototipo original
Salida del kill switch sin costo (corregido), benchmark inconsistente y sin calentamiento (ahora
mismo motor y ventana), costos de rebalanceo por desvío (ahora se cobran), ejecución en el mismo
cierre (ahora a la apertura siguiente), kill switch permanente que dejaba la estrategia fuera del
mercado (ahora con enfriamiento), endpoint bloqueable por región, validación de datos, hash de
datos y bitácora de experimentos, y 18 tests (antes 3).

## Paper trading (`paper.py`) — órdenes simuladas, uso personal
Señales y precios reales y públicos, **órdenes simuladas**: no hay claves ni código que opere en un exchange.

```bash
python paper.py run                 # una corrida por día UTC (idempotente: repetirla el mismo día no hace nada)
python paper.py status              # estado y equity actual
python paper.py report              # métricas + criterios de la etapa 1 (agregá --vs-backtest para comparar)
python paper.py rearm --confirmo    # rearme MANUAL del kill switch (nunca automático)
```
Estado y bitácora en `paper_state/` (`state.json`, `journal.jsonl`; ignorados por git).

**Cómo funciona una corrida:** baja velas cerradas -> valida datos (huecos, frescura, spread y precio
sospechosos abortan sin tocar el estado) -> misma señal y misma regla de rebalanceo que el backtest
(`plan_rebalance`) -> kill switch -> `RiskGuard` (límites duros) -> `PaperBroker` (compra al ask, vende al
bid, comisión 0,10 %) -> bitácora. Un test verifica que opera los mismos días que el backtest.

**Programarlo (Windows, una vez por día poco después de las 00:00 UTC)** — el backtest asume ejecutar en la
apertura, así que correr tarde invalida la comparación (el criterio `max_retraso_min` lo controla). Ejemplo
con el Programador de tareas, ajustando rutas y la hora a tu zona (00:10 UTC = 21:10 en UTC-3):
```powershell
$a = New-ScheduledTaskAction -Execute "C:\ruta\.venv\Scripts\python.exe" -Argument "paper.py run" -WorkingDirectory "C:\ruta\crypto_backtest"
$t = New-ScheduledTaskTrigger -Daily -At 21:10
Register-ScheduledTask -TaskName "PaperTrading" -Action $a -Trigger $t
```
La PC tiene que estar encendida a esa hora; si no, la corrida se pierde (queda registrada como día sin correr).
