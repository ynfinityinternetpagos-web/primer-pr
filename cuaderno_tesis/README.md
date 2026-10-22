# Cuaderno de tesis (CEDEARs)

Registrás cada idea **antes** de actuar, con evidencia, riesgos y condiciones de salida. El sistema la
resuelve de forma mecánica con precios reales y, con el tiempo, te dice si tus jugadas (o las de Claude)
tienen ventaja real o solo suerte. **No opera ni se conecta a ningún broker** (ni Cocos ni otro): es un
cuaderno de análisis y paper trading. No es asesoramiento financiero.

## Flujo
```bash
python -m cuaderno_tesis plantilla > tesis.json    # completás el JSON (desde la raíz del repo)
python -m cuaderno_tesis abrir --archivo tesis.json
python -m cuaderno_tesis nota T-0001 "salió el balance, sin cambios en la tesis"
python -m cuaderno_tesis resolver     # cierra por stop / objetivo / horizonte (corrélo seguido)
python -m cuaderno_tesis listar
python -m cuaderno_tesis reporte
python -m cuaderno_tesis verificar    # detecta si el cuaderno fue modificado
```
Requiere `pip install requests numpy`. Los tests: `python -m pytest cuaderno_tesis`.

## Qué tiene que traer cada tesis
`ticker`, `autor` (`yo` o `claude`, para medir quién acierta más), `tesis` (mecanismo concreto, 80+ caracteres),
`catalizador`, `evidencia` (fuentes), `riesgos` (al menos 2: qué te haría equivocar), `stop_pct`, `objetivo_pct`,
`horizonte_dias`, `prob_exito` (tu probabilidad de llegar al objetivo antes que al stop, para medir calibración)
y `tamano_pct`. El precio de referencia, el del benchmark (SPY) y la liquidez los toma el sistema al registrar.

## Reglas que se aplican solas
- **Tamaño**: máximo 5 % por jugada y 30 % de exposición abierta total. Una tesis abierta por ticker.
- **Costos**: se restan 1,2 % ida y vuelta por defecto (supuesto: verificá la tarifa real de tu broker y cargá
  `costo_ida_vuelta_pct` si difiere).
- **Resolución mecánica**: con el cierre diario de cada día posterior a la apertura. Stop o objetivo según
  el primer cierre que los cruza (al precio de ese cierre, con gaps). Si no pasa nada, sale en la fecha fin.
  Se ignora la vela del día actual. No hay discreción posterior; `cerrar` manual queda marcado como `manual`.
- **Integridad**: el cuaderno es append-only con cadena de hashes; cambiar, borrar o reordenar algo hace
  fallar `verificar`. La tesis original nunca se edita: se agregan notas fechadas.
- **Benchmark**: el CEDEAR de SPY en pesos, para comparar en la misma moneda (incluye el efecto del dólar).

## Cómo se decide si hay evidencia (criterios fijados de antemano)
Con `reporte`: al menos **50 jugadas cerradas**, exceso promedio sobre SPY **> 0**, límite inferior del intervalo
de confianza del 90 % **> 0** y puntaje de Brier **≤ 0,25** (calibrar mejor que decir siempre 50 %). Con menos
de 30 jugadas el reporte avisa que lo que ves es mayormente suerte. Superar los criterios **no prueba ventaja**:
solo habilita considerar posiciones reales mínimas, siempre con los límites de tamaño y bajo tu responsabilidad.

## Privacidad
El cuaderno se guarda en `~/.cuaderno_tesis/tesis.jsonl`, **fuera del repo** (el repo es público). No lo subas.
Los `*.jsonl` están ignorados por git en esta carpeta.

## Límites honestos
- Precios: Yahoo Finance no es una API oficial y puede cambiar o fallar; el CCL sale de dolarapi.com.
- Cierres diarios: un stop intradía no se detecta hasta el cierre.
- Las tesis de Claude se basan en fuentes públicas y en conocimiento con fecha de corte: son ideas a verificar
  y medir, no recomendaciones. Backtestear "Claude lee noticias" sobre el pasado no es válido (conoce lo que
  pasó después); por eso esta medición es solo hacia adelante.
