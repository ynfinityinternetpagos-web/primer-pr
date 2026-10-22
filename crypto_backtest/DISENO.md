# Diseño responsable: de backtest a dinero real

> Esto es ingeniería de un proceso de validación, **no asesoramiento financiero**. Nada acá
> garantiza ganancias. Usá solo dinero que puedas perder por completo y consultá a un
> contador/asesor sobre impuestos y regulación de tu país.

## 1. Principio rector
El dinero real entra por **etapas**, y cada etapa tiene criterios de pasaje **escritos antes de
ver los resultados**. Si un criterio falla, no se mueven los umbrales: se vuelve a investigar o
se descarta la estrategia. Un backtest que "funciona" es la hipótesis más barata de refutar y la
más fácil de autoengañarse.

| Etapa | Qué es | Se pasa a la siguiente si... |
|---|---|---|
| 0. Investigación (hoy) | Backtest + robustez (`python backtest.py --robustness`) | Se cumplen los 5 criterios de `robustness.GATES` |
| 1. Paper trading | Señales en vivo con datos reales, **órdenes simuladas**, mínimo 90 días | Resultado y slippage dentro de lo modelado; cero fallas operativas; sin divergencia inexplicada |
| 2. Real mínimo | Capital pequeño (ej. ≤ 5-10 % de lo que podés perder), límites duros | 6+ meses sin violar límites y con costos reales ≈ modelados |
| 3. Escalar | Subir capital gradualmente | Solo con criterios nuevos, escritos de antemano |

**Estado actual: etapa 0, criterios NO cumplidos** (ver sección 6). No corresponde pasar a dinero real.

## 2. Uso responsable de la información
- **Datos públicos y de punto en el tiempo**: solo velas cerradas; la vela abierta se descarta.
- **Sin mirar el futuro**: señal al cierre t-1, ejecución a la apertura t. Hay un test que altera
  los datos posteriores a un día T y exige que la equity hasta T no cambie.
- **Datos validados**: huecos, precios no positivos, NaN o `high < low` abortan la corrida.
- **Reproducibilidad**: cada corrida guarda el hash SHA-256 de los datos y toda la configuración.
- **Bitácora de experimentos** (`results/experiments.jsonl`): se registra *cada* corrida. Cuantas
  más variantes se prueban, menos vale la mejor (sesgo de selección). Hasta ahora: **3 corridas
  sobre datos reales** al 22-oct-2026 (la tercera fue el test 2018-2020, ver abajo); entre la 1 y la 2 se cambió el kill switch de permanente a con
  enfriamiento de 30 días, porque con el permanente la estrategia quedaba en efectivo para siempre
  (un defecto de diseño, no un ajuste de rendimiento). El valor de 30 días se eligió a priori, no
  se optimizó. **No se afinan más parámetros mirando estos resultados.**
- **El período 2021-2026 ya está "contaminado"** por haberlo visto. La validación genuinamente
  fuera de muestra es el paper trading hacia adelante (etapa 1).
- **Los umbrales de aprobación** (`GATES`) se fijaron antes de correr con datos reales y no se
  cambian después de verlos.
- Cumplir los criterios **no prueba ventaja**: solo habilita la etapa siguiente.

## 3. Lo que el modelo cubre y lo que no
Cubre: comisión + slippage sobre lo operado, rebalanceo por desvío, ejecución a la apertura,
kill switch con enfriamiento, benchmark con el mismo motor y costos.

**No cubre** (riesgos reales, algunos pueden ser mayores que la estrategia misma):
- Riesgo de la plataforma/custodia (quiebra, hackeo, bloqueo de retiros) y de stablecoin (depeg de USDT).
- Impuestos, comisiones de retiro y de red, regulación local.
- Spread variable, liquidez en crisis, órdenes parciales, caídas de la API, gaps de fin de semana.
- Que el comportamiento pasado de BTC/ETH (pocos ciclos, 2 activos muy correlacionados) no se repita.
- El kill switch **no es un tope garantizado**: se evalúa al cierre y, al rearmarse con pico nuevo,
  la pérdida acumulada medida desde el máximo histórico puede superar el 15 % (en el backtest real: -39 %).

## 4. Arquitectura de ejecución (PaperBroker implementado; LiveBroker NO)
Principio: **el código de estrategia nunca toca claves ni el exchange**.

```
datos -> señal (pura, la misma del backtest) -> órdenes deseadas
      -> RiskGuard (límites duros, independiente) -> Broker (interfaz) -> exchange
```
- **Broker como interfaz** con dos implementaciones: `PaperBroker` (por defecto) y `LiveBroker`.
  El modo vivo exige bandera explícita **y** variable de entorno **y** confirmación interactiva.
- **Claves**: API key con permiso *solo trading*, **sin retiros**, con lista blanca de IP; vive en
  variables de entorno o gestor de secretos, jamás en el repo (`.env` ya está ignorado). Nunca se
  loguea ni se pasa a un LLM.
- **RiskGuard** (límites que la estrategia no puede saltear): máximo notional por orden, máxima
  exposición total, máxima pérdida diaria y semanal, máximo de órdenes por día, y **kill switch con
  rearme manual** (en vivo no hay enfriamiento automático).
- **Robustez operativa**: ID de orden idempotente (cliente), reconciliación de saldos contra el
  exchange antes de operar, si la API o los datos fallan → **no operar** y alertar, log inmutable de
  cada decisión, alerta por divergencia live vs. backtest.
- **Sin apalancamiento, sin shorts, sin auto-optimización** de parámetros en vivo.
- **Implementado:** `paper_trading/` con `Broker` (interfaz), `PaperBroker`, `RiskGuard`, datos públicos
  y el runner diario (`paper.py`). El kill switch en paper también es de **rearme manual**.
- **Criterios de la etapa 1** (`paper_trading/runner.ETAPA1`, fijados antes de empezar): ≥ 90 días corridos,
  ≤ 3 % de corridas fallidas, ≤ 3 días seguidos sin correr, costo de spread promedio ≤ 0,10 % (el doble de
  lo modelado), 0 rechazos del RiskGuard y corridas a ≤ 120 min de las 00:00 UTC.
- El "slippage" se mide **separado** del movimiento de mercado: costo de spread (ejecución) por un lado y
  desvío contra la apertura (mercado + demora) por otro. Mezclarlos daría números sin sentido.
- Antes de escribir el `LiveBroker`: que la etapa 1 apruebe, y recién ahí decidir.

## 5. Preguntas que tenés que responder antes de la etapa 2
- ¿Cuánto podés perder por completo sin que afecte tu vida? (ese es el techo, no el punto de partida)
- ¿Qué plataforma y qué custodia? ¿Cómo tributa y qué regulación aplica en tu país?
- ¿Qué pérdida te haría apagar todo, y quién (vos) lo decide con la cabeza fría?

## 6. Resultados de la etapa 0 (datos reales 2021-01-01 a 2026-10-14, corrida #2)
Capital 1.000 USDT, costos 0,10 % + 0,05 %. **Criterios: NO cumplidos (3 de 5).**

| | Estrategia | Benchmark 50/50 |
|---|---|---|
| Retorno total | +105,6 % | +248,9 % |
| Máx. drawdown | -39,5 % | -76,8 % |
| Sharpe (rf=0) | 0,56 | 0,66 |
| Costos pagados | 99 USDT (63 eventos) | 8 USDT |

Criterios: ventanas positivas 75 % (OK) · peor drawdown de ventana -39 % vs límite -25 % (**FALLA**) ·
Sharpe con costos x3 0,49 (OK) · vecinos de parámetros positivos 100 % (OK) · Sharpe vs benchmark
-0,10 (**FALLA**). Con costos x5 el retorno cae a +8 %: la estrategia es muy sensible a los costos.
Lectura honesta: reduce el drawdown respecto de comprar y mantener, pero no mejora el retorno
ajustado por riesgo y no hay evidencia de ventaja. Un resultado así es información útil, no un fracaso.

## 7. Test fuera de muestra 2018-2020 (corrida #3, 22-oct-2026)
Parámetros y criterios sin tocar. Estrategia +425 % (DD -35 %, Sharpe 1,87) vs benchmark +143 % (DD -75 %, Sharpe 0,85).
Criterios con la **v1: NO cumplidos** (4 de 5): ventanas positivas 50 % < 60 %. Una de las 4 ventanas (2018) dio
exactamente 0 % porque la estrategia se quedó en efectivo durante una caída del -63 % del benchmark.
Sensibilidad a parámetros muy alta: 30/150 -> +680 %, 50/200 -> +425 %, 70/250 -> +169 %.

**Cambio de criterios (v2), posterior a ver estos resultados y por eso transparente:** "ventanas positivas" (retorno > 0)
pasó a "ventanas no perdedoras" (retorno >= 0), porque quedarse en efectivo en una caída no es una falla. Rige
**solo hacia adelante**. Los resultados 2021-2026 y 2018-2020 se evaluaron con la v1 y no se reinterpretan: bajo la
v1 ninguno cumplió. Cualquier cambio de criterio hecho tras ver resultados debe registrarse así.

La bitácora de experimentos es ahora única y versionada: `experiments_log/experiments.jsonl` (las 3 corridas previas
se cargaron a mano con la marca `backfill`).
