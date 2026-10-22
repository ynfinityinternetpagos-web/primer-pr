import logging

from agents.architect import AgenteArquitecto
from agents.developer import AgenteDesarrollador
from agents.reviewer import AgenteRevisor
from core.llm import LLMSimulado
from core.models import ErrorAgente, Resultado

log = logging.getLogger("motor")


class Orquestador:
    def __init__(self, llm=None, revisor_llm=None):
        llm = llm or LLMSimulado()
        self.arquitecto = AgenteArquitecto(llm)
        self.desarrollador = AgenteDesarrollador(llm)
        self.revisor = AgenteRevisor(revisor_llm)

    def ejecutar(self, tarea: str, max_intentos: int = 3, pruebas: str = "") -> Resultado:
        """`pruebas`: asserts en Python que el código generado debe cumplir."""
        log.info("Iniciando motor multi-agente")
        try:
            plan = self.arquitecto.procesar(tarea)
        except ErrorAgente as e:
            return Resultado(False, None, 0, error=str(e))
        log.info("Plan:\n%s", plan)

        feedback, revision = "", None
        for i in range(1, max_intentos + 1):
            log.info("Vuelta %d/%d", i, max_intentos)
            try:
                codigo = self.desarrollador.procesar(plan, feedback)
                revision = self.revisor.procesar(codigo, pruebas)
            except ErrorAgente as e:
                return Resultado(False, None, i, revision, error=str(e))
            log.info("Revisión: %s", revision.como_feedback())
            if revision.aprobado:
                return Resultado(True, codigo, i, revision)
            feedback = revision.como_feedback()
        return Resultado(False, None, max_intentos, revision,
                         error="No se aprobó tras el máximo de intentos")
