# Motor Multi-Agente

Arquitecto -> Desarrollador -> Revisor, en bucle hasta que el revisor aprueba.

- `python main.py` corre con un LLM simulado (sin red). Si existe `ANTHROPIC_API_KEY`
  (y `pip install anthropic`) usa Claude.
- `python -m unittest discover -s tests` corre los tests.
- Revisor: análisis estático con `ast` (sintaxis, TODO, funciones vacías, eval/exec,
  shell=True, secretos hardcodeados) + segunda opinión opcional de un LLM en JSON.
  Una respuesta no parseable cuenta como rechazo.
