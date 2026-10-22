"""Skills: archivos .md con conocimiento reutilizable que se inyecta en los
prompts cuando la tarea coincide con sus palabras clave.

Formato de cada archivo en skills/:
    ---
    nombre: autenticacion
    palabras: login, contraseña, password
    ---
    Texto con reglas y buenas prácticas...
"""
import os
from dataclasses import dataclass
from typing import List

DIR_POR_DEFECTO = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills")


@dataclass
class Skill:
    nombre: str
    palabras: List[str]
    cuerpo: str


def _parsear(texto: str, respaldo: str) -> Skill:
    nombre, palabras, cuerpo = respaldo, [], texto.strip()
    if texto.startswith("---"):
        partes = texto.split("---", 2)
        if len(partes) == 3:
            for linea in partes[1].splitlines():
                clave, _, valor = linea.partition(":")
                if clave.strip() == "nombre":
                    nombre = valor.strip() or respaldo
                elif clave.strip() == "palabras":
                    palabras = [p.strip().lower() for p in valor.split(",") if p.strip()]
            cuerpo = partes[2].strip()
    return Skill(nombre, palabras, cuerpo)


def cargar_skills(directorio: str = DIR_POR_DEFECTO) -> List[Skill]:
    if not os.path.isdir(directorio):
        return []
    skills = []
    for archivo in sorted(os.listdir(directorio)):
        if archivo.endswith(".md"):
            with open(os.path.join(directorio, archivo), encoding="utf-8") as f:
                skills.append(_parsear(f.read(), archivo[:-3]))
    return skills


def seleccionar(tarea: str, skills: List[Skill], maximo: int = 2) -> List[Skill]:
    t = tarea.lower()
    puntuadas = [(sum(p in t for p in s.palabras), s) for s in skills]
    puntuadas = [x for x in puntuadas if x[0] > 0]
    puntuadas.sort(key=lambda x: -x[0])
    return [s for _, s in puntuadas[:maximo]]


def como_contexto(skills: List[Skill]) -> str:
    if not skills:
        return ""
    return "REGLAS Y BUENAS PRÁCTICAS A RESPETAR:\n" + "\n\n".join(
        f"[{s.nombre}]\n{s.cuerpo}" for s in skills
    )
