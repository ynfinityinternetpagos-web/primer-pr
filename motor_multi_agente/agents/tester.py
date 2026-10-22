import ast

from agents.developer import extraer_codigo
from core.models import ErrorAgente


def validar_pruebas(pruebas: str) -> str:
    """Solo se aceptan sentencias `assert`: las pruebas generadas por un LLM
    no pueden importar módulos ni ejecutar otra cosa."""
    try:
        arbol = ast.parse(pruebas)
    except SyntaxError as e:
        raise ErrorAgente(f"Pruebas generadas con sintaxis inválida: {e.msg}") from e
    if not arbol.body:
        raise ErrorAgente("El probador no generó ninguna prueba")
    if not all(isinstance(n, ast.Assert) for n in arbol.body):
        raise ErrorAgente("Las pruebas generadas solo pueden contener 'assert'")
    return pruebas


class AgenteProbador:
    """Genera asserts a partir de la tarea y el plan (no del código).
    Ojo: si usa el mismo LLM que el desarrollador, pueden compartir el mismo
    malentendido; usar un LLM distinto o pruebas escritas a mano es más fuerte."""

    def __init__(self, llm):
        self.llm = llm

    def procesar(self, tarea: str, plan: str) -> str:
        try:
            texto = self.llm.completar(
                "GENERAR PRUEBAS. Escribí solo sentencias `assert` en Python (sin imports) "
                "para verificar el comportamiento pedido. Si la tarea no especifica nombres "
                "de funciones, usá los del plan.\n"
                f"Tarea: {tarea}\nPlan:\n{plan}\nRespondé solo con un bloque ```python."
            )
        except Exception as e:
            raise ErrorAgente(f"Probador falló: {e}") from e
        return validar_pruebas(extraer_codigo(texto))
