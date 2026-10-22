# Motor Multi-Agente

Flujo: skills -> Arquitecto -> [Probador] -> (Desarrollador -> Revisor -> [Seguridad]) en bucle
hasta aprobar. Lo que va entre corchetes es opcional.

- `python main.py` corre con un LLM simulado (sin red). Si existe `ANTHROPIC_API_KEY`
  (y `pip install anthropic`) usa Claude.
- `python -m unittest discover -s tests` corre los tests.

## Piezas
- **Revisor**: análisis estático con `ast` (sintaxis, TODO, funciones vacías, eval/exec,
  shell=True, secretos, except desnudo, defaults mutables) y, si el código está limpio,
  ejecución en subproceso (`core/sandbox.py`, best-effort, no es un sandbox fuerte) con las
  `pruebas` opcionales. Segunda opinión LLM opcional (`revisor_llm`).
- **Probador** (`probador_llm`): genera asserts desde la tarea y el plan. Solo se aceptan
  sentencias `assert`. Mejor con un LLM distinto al del desarrollador.
- **Seguridad** (`seguridad_llm`): revisor separado enfocado en vulnerabilidades.
- **Skills** (`skills/*.md`): reglas con `palabras` clave; las que coinciden con la tarea se
  inyectan en los prompts del arquitecto y el desarrollador. Se agregan sin tocar código.
- Una respuesta de LLM que no sea JSON válido cuenta siempre como rechazo.
