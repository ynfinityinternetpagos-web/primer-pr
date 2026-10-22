from core.models import ErrorAgente


class AgenteArquitecto:
    def __init__(self, llm):
        self.llm = llm

    def procesar(self, tarea: str, contexto: str = "") -> str:
        if not tarea or not tarea.strip():
            raise ErrorAgente("La tarea está vacía")
        prompt = (
            "Sos un arquitecto de software. Dividí esta tarea en pasos "
            f"numerados y breves:\n{tarea}\n"
        )
        if contexto:
            prompt += f"\n{contexto}\n"
        try:
            plan = self.llm.completar(prompt)
        except Exception as e:
            raise ErrorAgente(f"Arquitecto falló: {e}") from e
        if not plan.strip():
            raise ErrorAgente("El arquitecto devolvió un plan vacío")
        return plan
