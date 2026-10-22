import unittest

from agents.security import AgenteSeguridad
from agents.tester import AgenteProbador, validar_pruebas
from core.llm import LLMSimulado
from core.models import ErrorAgente
from core.orchestrator import Orquestador
from core.skills import como_contexto, cargar_skills, seleccionar


class Espia:
    """LLM que guarda los prompts y delega en el simulado."""

    def __init__(self):
        self.prompts = []
        self._base = LLMSimulado()

    def completar(self, prompt):
        self.prompts.append(prompt)
        return self._base.completar(prompt)


class TestSkills(unittest.TestCase):
    def test_seleccion_por_palabras(self):
        skills = cargar_skills()
        self.assertGreaterEqual(len(skills), 2)
        nombres = [s.nombre for s in seleccionar("Crear login con contraseña", skills)]
        self.assertIn("autenticacion", nombres)
        self.assertEqual(seleccionar("algo sin relación alguna", skills), [])
        self.assertEqual(como_contexto([]), "")

    def test_skills_llegan_a_los_prompts(self):
        llm = Espia()
        Orquestador(llm).ejecutar("Crear un login con contraseña")
        self.assertTrue(all("hash con sal" in p for p in llm.prompts[:2]))

    def test_sin_skills_no_hay_contexto(self):
        llm = Espia()
        Orquestador(llm, skills_dir=None).ejecutar("Crear un login")
        self.assertFalse(any("BUENAS PRÁCTICAS" in p for p in llm.prompts))


class TestProbador(unittest.TestCase):
    def test_solo_asserts(self):
        validar_pruebas("assert 1 == 1")
        for malo in ["import os", "x = 1", "print(1)", "assert (", ""]:
            with self.assertRaises(ErrorAgente):
                validar_pruebas(malo)

    def test_pruebas_generadas_se_usan(self):
        r = Orquestador(LLMSimulado(), probador_llm=LLMSimulado()).ejecutar("tarea")
        self.assertTrue(r.exito)

    def test_pruebas_generadas_invalidas_abortan(self):
        class Malo:
            def completar(self, p):
                return "```python\nimport os\n```"
        r = Orquestador(LLMSimulado(), probador_llm=Malo()).ejecutar("tarea")
        self.assertFalse(r.exito)
        self.assertIn("assert", r.error)

    def test_probador_directo(self):
        self.assertIn("assert", AgenteProbador(LLMSimulado()).procesar("t", "plan"))


class TestSeguridad(unittest.TestCase):
    def test_rechazo_de_seguridad_vuelve_como_feedback(self):
        class Estricto:
            def __init__(self):
                self.n = 0

            def completar(self, p):
                self.n += 1
                if self.n == 1:
                    return '{"aprobado": false, "comentarios": ["falta validar"]}'
                return '{"aprobado": true, "comentarios": []}'

        r = Orquestador(LLMSimulado(), seguridad_llm=Estricto()).ejecutar("tarea")
        self.assertTrue(r.exito)
        self.assertEqual(r.intentos, 3)

    def test_respuesta_basura_es_rechazo(self):
        class Basura:
            def completar(self, p):
                return "todo bien, APROBADO"
        self.assertFalse(AgenteSeguridad(Basura()).procesar("x = 1").aprobado)

    def test_llm_caido(self):
        class Roto:
            def completar(self, p):
                raise RuntimeError("x")
        with self.assertRaises(ErrorAgente):
            AgenteSeguridad(Roto()).procesar("x = 1")


if __name__ == "__main__":
    unittest.main()
