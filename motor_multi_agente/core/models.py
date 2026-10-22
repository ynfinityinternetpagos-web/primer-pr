from dataclasses import dataclass, field
from typing import List, Optional


class ErrorAgente(Exception):
    """Fallo de un agente (LLM caído, respuesta inválida, etc.)."""


@dataclass
class Revision:
    aprobado: bool
    comentarios: List[str] = field(default_factory=list)

    def como_feedback(self) -> str:
        if self.aprobado:
            return "APROBADO"
        return "RECHAZADO:\n" + "\n".join(f"- {c}" for c in self.comentarios)


@dataclass
class Resultado:
    exito: bool
    codigo: Optional[str]
    intentos: int
    ultima_revision: Optional[Revision] = None
    error: Optional[str] = None
