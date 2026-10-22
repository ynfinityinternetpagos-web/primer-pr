import logging

from agents.architect import AgenteArquitecto
from agents.developer import AgenteDesarrollador
from agents.reviewer import AgenteRevisor
from agents.security import AgenteSeguridad
from agents.tester import AgenteProbador
from core import skills as skills_mod
from core.llm import LLMSimulado
from core.models import ErrorAgente, Resultado

log = logging.getLogger("motor")


class Orquestador:
    """Flujo: skills -> arquitecto -> [probador] -> (desarrollador -> revisor
    -> [seguridad]) en bucle. Los corchetes son opcionales."""

    def __init__(self, llm=None, revisor_llm=None, seguridad_llm=None,
                 probador_llm=None, skills_dir=skills_mod.DIR_POR_DEFECTO):
        llm = llm or LLMSimulado()
        self.arquitecto = AgenteArquitecto(llm)
        self.desarrollador = AgenteDesarrollador(llm)
        self.revisor = AgenteRevisor(revisor_llm)
        self.seguridad = AgenteSeguridad(seguridad_llm) if seguridad_llm else None
        self.probador = AgenteProbador(probador_llm) if probador_llm else None
        self.skills = skills_mod.cargar_skills(skills_dir) if skills_dir else []

    def ejecutar(self, tarea: str, max_intentos: int = 3, pruebas: str = "") -> Resultado:
        """`pruebas`: asserts que el código debe cumplir. Si no se pasan y hay
        probador, se generan a partir de la tarea y el plan."""
        log.info("Iniciando motor multi-agente")
        usadas = skills_mod.seleccionar(tarea, self.skills)
        contexto = skills_mod.como_contexto(usadas)
        if usadas:
            log.info("Skills aplicadas: %s", ", ".join(s.nombre for s in usadas))
        try:
            plan = self.arquitecto.procesar(tarea, contexto)
            if not pruebas and self.probador:
                pruebas = self.probador.procesar(tarea, plan)
                log.info("Pruebas generadas:\n%s", pruebas)
        except ErrorAgente as e:
            return Resultado(False, None, 0, error=str(e))
        log.info("Plan:\n%s", plan)

        feedback, revision = "", None
        for i in range(1, max_intentos + 1):
            log.info("Vuelta %d/%d", i, max_intentos)
            try:
                codigo = self.desarrollador.procesar(plan, feedback, contexto)
                revision = self.revisor.procesar(codigo, pruebas)
                if revision.aprobado and self.seguridad:
                    revision = self.seguridad.procesar(codigo)
            except ErrorAgente as e:
                return Resultado(False, None, i, revision, error=str(e))
            log.info("Revisión: %s", revision.como_feedback())
            if revision.aprobado:
                return Resultado(True, codigo, i, revision)
            feedback = revision.como_feedback()
        return Resultado(False, None, max_intentos, revision,
                         error="No se aprobó tras el máximo de intentos")
