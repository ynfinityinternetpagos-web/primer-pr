import logging
import os

from core.orchestrator import Orquestador

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    llm = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        from core.llm import LLMAnthropic
        llm = LLMAnthropic()
    r = Orquestador(llm=llm).ejecutar("Crear un sistema de autenticación básico.")
    print("ÉXITO" if r.exito else f"FALLO: {r.error}")
    if r.codigo:
        print(r.codigo)
