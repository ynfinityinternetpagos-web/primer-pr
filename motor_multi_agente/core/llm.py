"""LLMs intercambiables: cualquier objeto con `completar(prompt) -> str`."""
import os


class LLMSimulado:
    """Funciona sin red. Devuelve código con TODO salvo que el prompt traiga
    feedback del revisor, para demostrar que el bucle realmente lo usa."""

    def completar(self, prompt: str) -> str:
        if "GENERAR PRUEBAS" in prompt:
            return "```python\nassert hacer_tarea('a')['ok'] is True\n```"
        if "REVISIÓN DE SEGURIDAD" in prompt:
            return '{"aprobado": true, "comentarios": []}'
        if "FEEDBACK DEL REVISOR" in prompt:
            return (
                "```python\n"
                "def hacer_tarea(entrada):\n"
                "    if not isinstance(entrada, str) or not entrada:\n"
                "        raise ValueError('entrada inválida')\n"
                "    return {'ok': True, 'dato': entrada}\n"
                "```"
            )
        return "```python\ndef hacer_tarea(entrada):\n    # TODO: implementar\n    pass\n```"


class LLMAnthropic:
    """Requiere `pip install anthropic` y la variable ANTHROPIC_API_KEY."""

    def __init__(self, modelo: str = "claude-sonnet-5-5", max_tokens: int = 2000):
        import anthropic  # import perezoso: solo si se usa

        self._cliente = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self._modelo = modelo
        self._max_tokens = max_tokens

    def completar(self, prompt: str) -> str:
        r = self._cliente.messages.create(
            model=self._modelo,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in r.content if b.type == "text")
