"""Ejecución aislada (best-effort) de código generado.

Capas: el revisor solo llama esto si el análisis estático no encontró nada
peligroso; el código corre en un subproceso con `python -I`, directorio
temporal propio, entorno mínimo, timeout y salida truncada, y en POSIX con
límites de CPU/memoria. NO es un sandbox de seguridad fuerte: para código
realmente no confiable hace falta un contenedor/VM sin red.
"""
import os
import subprocess
import sys
import tempfile
from typing import Tuple

MAX_SALIDA = 2000


def _limites_posix():
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024,) * 2)


def ejecutar_aislado(codigo: str, pruebas: str = "", timeout: float = 5.0) -> Tuple[bool, str]:
    """Devuelve (ok, salida). Importa el código y luego corre `pruebas`
    (asserts en Python que pueden usar los nombres definidos en el código)."""
    with tempfile.TemporaryDirectory(prefix="motor_") as d:
        with open(os.path.join(d, "solucion.py"), "w", encoding="utf-8") as f:
            f.write(codigo)
        with open(os.path.join(d, "pruebas_run.py"), "w", encoding="utf-8") as f:
            f.write("import sys, os\nsys.path.insert(0, os.getcwd())\n"
                    "from solucion import *\n" + pruebas + "\n")

        env = {"PYTHONIOENCODING": "utf-8"}
        if os.name == "nt":
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
        try:
            p = subprocess.run(
                [sys.executable, "-I", "pruebas_run.py"],
                cwd=d, env=env, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout,
                preexec_fn=_limites_posix if os.name == "posix" else None,
            )
        except subprocess.TimeoutExpired:
            return False, f"Timeout: el código tardó más de {timeout}s (¿bucle infinito?)"
        salida = ((p.stdout or "") + (p.stderr or "")).strip()[-MAX_SALIDA:]
        return p.returncode == 0, salida
