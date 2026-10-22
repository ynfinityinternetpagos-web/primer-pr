import re

from core.models import ErrorAgente

_BLOQUE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def extraer_codigo(texto: str) -> str:
    m = _BLOQUE.search(texto)
    return (m.group(1) if m else texto).strip()


class AgenteDesarrollador:
    def __init__(self, llm):
        self.llm = llm
        self.intentos = 0

    def procesar(self, plan: str, feedback: str = "") -> str:
        self.intentos += 1
        prompt = f"Implementá en Python siguiendo este plan:\n{plan}\n"
        if feedback:
            prompt += f"\nFEEDBACK DEL REVISOR (corregí todo):\n{feedback}\n"
        prompt += "\nRespondé solo con un bloque ```python."
        try:
            codigo = extraer_codigo(self.llm.completar(prompt))
        except Exception as e:
            raise ErrorAgente(f"Desarrollador falló: {e}") from e
        if not codigo:
            raise ErrorAgente("El desarrollador devolvió código vacío")
        return codigo
