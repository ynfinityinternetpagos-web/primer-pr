from core.models import ErrorAgente, Revision
from agents.reviewer import parsear_revision_llm


class AgenteSeguridad:
    """Revisor de seguridad separado, con su propio prompt y su propio LLM
    (conviene que sea distinto al que escribió el código)."""

    def __init__(self, llm):
        self.llm = llm

    def procesar(self, codigo: str) -> Revision:
        try:
            texto = self.llm.completar(
                "REVISIÓN DE SEGURIDAD. Buscá únicamente vulnerabilidades: inyección, "
                "secretos, manejo inseguro de contraseñas o archivos, validación faltante. "
                'Respondé solo JSON {"aprobado": true|false, "comentarios": ["..."]}:\n'
                + codigo
            )
        except Exception as e:
            raise ErrorAgente(f"Agente de seguridad falló: {e}") from e
        r = parsear_revision_llm(texto)
        return Revision(r.aprobado, [f"[seguridad] {c}" for c in r.comentarios])
