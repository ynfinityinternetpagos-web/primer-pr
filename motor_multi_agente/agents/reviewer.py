import ast
import json
import re
from typing import List, Optional

from core.models import ErrorAgente, Revision
from core.sandbox import ejecutar_aislado

_SECRETO = re.compile(r"pass(word|wd)?|secret|token|api_?key", re.I)
_LLAMADAS_PELIGROSAS = {"eval", "exec", "compile", "__import__"}


def _es_vacia(fn) -> bool:
    cuerpo = [
        n for n in fn.body
        if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))
    ]
    return not cuerpo or all(isinstance(n, ast.Pass) for n in cuerpo)


def analisis_estatico(codigo: str) -> List[str]:
    problemas: List[str] = []
    try:
        arbol = ast.parse(codigo)
    except SyntaxError as e:
        return [f"Error de sintaxis en línea {e.lineno}: {e.msg}"]

    for i, linea in enumerate(codigo.splitlines(), 1):
        if re.search(r"#.*\b(TODO|FIXME|XXX)\b", linea):
            problemas.append(f"Línea {i}: tarea pendiente (TODO/FIXME)")

    for n in ast.walk(arbol):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _es_vacia(n):
                problemas.append(f"Función '{n.name}' sin implementación")
            for d in n.args.defaults + [x for x in n.args.kw_defaults if x]:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    problemas.append(f"Función '{n.name}': argumento por defecto mutable")
        elif isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id in _LLAMADAS_PELIGROSAS:
                problemas.append(f"Línea {n.lineno}: uso peligroso de {f.id}()")
            if isinstance(f, ast.Attribute) and f.attr == "system":
                problemas.append(f"Línea {n.lineno}: uso de os.system")
            for kw in n.keywords:
                if kw.arg == "shell" and getattr(kw.value, "value", False) is True:
                    problemas.append(f"Línea {n.lineno}: subprocess con shell=True")
        elif isinstance(n, ast.ExceptHandler) and n.type is None:
            problemas.append(f"Línea {n.lineno}: 'except:' sin tipo oculta errores")
        elif isinstance(n, ast.Assign):
            v = n.value
            if isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value:
                for t in n.targets:
                    if isinstance(t, ast.Name) and _SECRETO.search(t.id):
                        problemas.append(
                            f"Línea {n.lineno}: posible secreto hardcodeado en '{t.id}'"
                        )
    return problemas


def parsear_revision_llm(texto: str) -> Revision:
    """Espera JSON {"aprobado": bool, "comentarios": [...]}.
    Cualquier respuesta que no se pueda parsear cuenta como RECHAZO."""
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    try:
        d = json.loads(m.group(0)) if m else None
        if not isinstance(d, dict) or not isinstance(d.get("aprobado"), bool):
            raise ValueError
        com = [str(c) for c in d.get("comentarios", [])]
        return Revision(d["aprobado"], com)
    except (ValueError, TypeError):
        return Revision(False, ["La revisión del LLM no tiene formato JSON válido"])


class AgenteRevisor:
    def __init__(self, llm: Optional[object] = None):
        self.llm = llm  # opcional: segunda opinión semántica

    def procesar(self, codigo: str, pruebas: str = "") -> Revision:
        problemas = analisis_estatico(codigo)
        if problemas:
            # Código con problemas estáticos: no se ejecuta nunca.
            return Revision(False, problemas)
        ok, salida = ejecutar_aislado(codigo, pruebas)
        if not ok:
            return Revision(False, [f"Falla al ejecutar{' con pruebas' if pruebas else ''}: {salida}"])
        if self.llm is not None:
            try:
                texto = self.llm.completar(
                    "Revisá este código por bugs y seguridad. Respondé solo JSON "
                    '{"aprobado": true|false, "comentarios": ["..."]}:\n' + codigo
                )
            except Exception as e:
                raise ErrorAgente(f"Revisor falló: {e}") from e
            r = parsear_revision_llm(texto)
            if not r.aprobado:
                problemas += r.comentarios
        return Revision(not problemas, problemas)
