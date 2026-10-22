import unittest

from agents.reviewer import AgenteRevisor, analisis_estatico, parsear_revision_llm
from core.llm import LLMSimulado
from core.sandbox import ejecutar_aislado
from core.orchestrator import Orquestador


class LLMRoto:
    def completar(self, prompt):
        raise RuntimeError("sin red")


class LLMSiempreMalo:
    def completar(self, prompt):
        return "```python\ndef f():\n    pass\n```"


class TestRevisor(unittest.TestCase):
    def test_detecta_problemas(self):
        self.assertTrue(analisis_estatico("def f(:\n"))
        self.assertTrue(analisis_estatico("def f():\n    # TODO x\n    return 1"))
        self.assertTrue(analisis_estatico("def f():\n    pass"))
        self.assertTrue(analisis_estatico("def f(x):\n    return eval(x)"))
        self.assertTrue(analisis_estatico("password = 'abc123'"))

    def test_codigo_limpio(self):
        self.assertEqual(analisis_estatico("def f(x):\n    return x + 1"), [])

    def test_respuesta_llm_ambigua_es_rechazo(self):
        self.assertFalse(parsear_revision_llm('{"aprobado": false}').aprobado)
        self.assertFalse(parsear_revision_llm("no APROBADO").aprobado)
        self.assertFalse(parsear_revision_llm("basura").aprobado)
        self.assertTrue(parsear_revision_llm('ok {"aprobado": true}').aprobado)

    def test_llm_rechaza(self):
        class L:
            def completar(self, p):
                return '{"aprobado": false, "comentarios": ["bug"]}'
        r = AgenteRevisor(L()).procesar("def f():\n    return 1")
        self.assertFalse(r.aprobado)
        self.assertIn("bug", r.comentarios)


class TestOrquestador(unittest.TestCase):
    def test_exito_usando_feedback(self):
        r = Orquestador(LLMSimulado()).ejecutar("tarea")
        self.assertTrue(r.exito)
        self.assertEqual(r.intentos, 2)

    def test_falla_tras_max_intentos(self):
        r = Orquestador(LLMSiempreMalo()).ejecutar("tarea", max_intentos=2)
        self.assertFalse(r.exito)
        self.assertEqual(r.intentos, 2)

    def test_llm_caido(self):
        r = Orquestador(LLMRoto()).ejecutar("tarea")
        self.assertFalse(r.exito)
        self.assertIn("Arquitecto", r.error)

    def test_tarea_vacia(self):
        self.assertFalse(Orquestador().ejecutar("  ").exito)


class LLMLogicaMala:
    """Primero devuelve código válido pero con bug de lógica; con feedback lo arregla."""

    def completar(self, prompt):
        if "FEEDBACK DEL REVISOR" in prompt:
            return "```python\ndef suma(a, b):\n    return a + b\n```"
        return "```python\ndef suma(a, b):\n    return a - b\n```"


class TestEjecucion(unittest.TestCase):
    def test_bug_de_logica_detectado_por_pruebas_y_corregido(self):
        r = Orquestador(LLMLogicaMala()).ejecutar("sumar", pruebas="assert suma(2, 3) == 5")
        self.assertTrue(r.exito)
        self.assertEqual(r.intentos, 2)

    def test_bug_sin_correccion_falla(self):
        class Fijo:
            def completar(self, p):
                return "```python\ndef suma(a, b):\n    return a - b\n```"
        r = Orquestador(Fijo()).ejecutar("sumar", 2, "assert suma(2, 3) == 5")
        self.assertFalse(r.exito)
        self.assertIn("AssertionError", r.ultima_revision.comentarios[0])

    def test_bucle_infinito_corta_por_timeout(self):
        ok, salida = ejecutar_aislado("while True:\n    pass", timeout=1)
        self.assertFalse(ok)
        self.assertIn("Timeout", salida)

    def test_codigo_peligroso_no_se_ejecuta(self):
        r = AgenteRevisor().procesar("import os\nos.system('echo hola')")
        self.assertFalse(r.aprobado)
        self.assertNotIn("Falla al ejecutar", r.comentarios[0])

    def test_error_en_ejecucion(self):
        self.assertFalse(AgenteRevisor().procesar("x = 1 / 0").aprobado)

    def test_estatico_extra(self):
        self.assertTrue(analisis_estatico("def f(a=[]):\n    return a"))
        self.assertTrue(analisis_estatico("try:\n    x = 1\nexcept:\n    x = 2"))


if __name__ == "__main__":
    unittest.main()
