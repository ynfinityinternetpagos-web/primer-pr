"""Cuaderno de tesis: registro append-only con cadena de hashes.

Cada idea se registra ANTES de actuar. La cadena de hashes (cada línea incluye el hash de la
anterior) hace detectable cualquier edición o reordenamiento posterior: no se puede "mejorar"
una tesis después de ver el resultado sin que `verificar` lo marque.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

MAX_TAMANO_PCT = 5.0        # % máximo del capital por jugada
MAX_EXPOSICION_PCT = 30.0   # % máximo sumando todas las jugadas abiertas
COSTO_IDA_VUELTA_PCT = 1.2  # supuesto de comisiones+derechos ida y vuelta: verificá la tarifa real
LIQUIDEZ_MIN_ARS = 10_000_000  # monto operado diario promedio por debajo del cual se advierte
RUTA_POR_DEFECTO = Path.home() / ".cuaderno_tesis" / "tesis.jsonl"  # FUERA del repo (es público)


class ErrorTesis(ValueError):
    pass


def _texto(d: dict, k: str, minimo: int) -> str:
    v = d.get(k)
    if not isinstance(v, str) or len(v.strip()) < minimo:
        raise ErrorTesis(f"'{k}' es obligatorio (mínimo {minimo} caracteres)")
    return v.strip()


def _lista(d: dict, k: str, minimo: int, largo: int) -> List[str]:
    v = d.get(k)
    if not isinstance(v, list) or len(v) < minimo or any(not isinstance(x, str) or len(x.strip()) < largo for x in v):
        raise ErrorTesis(f"'{k}' necesita al menos {minimo} ítems de {largo}+ caracteres")
    return [x.strip() for x in v]


def _num(d: dict, k: str, lo: float, hi: float) -> float:
    v = d.get(k)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not (lo < v <= hi):
        raise ErrorTesis(f"'{k}' debe ser un número en ({lo}, {hi}]")
    return float(v)


def validar_nueva(d: dict, abiertas: List[dict]) -> dict:
    """Valida los campos que PONE el autor (el precio de referencia lo agrega el sistema)."""
    ticker = d.get("ticker", "")
    if not isinstance(ticker, str) or not ticker.isalpha() or not (1 <= len(ticker) <= 6):
        raise ErrorTesis("'ticker' debe ser el símbolo del CEDEAR (solo letras, ej. AAPL)")
    autor = d.get("autor")
    if autor not in ("yo", "claude"):
        raise ErrorTesis("'autor' debe ser 'yo' o 'claude' (para medir quién acierta más)")
    out = {
        "ticker": ticker.upper(), "autor": autor,
        "tesis": _texto(d, "tesis", 80),
        "catalizador": _texto(d, "catalizador", 10),
        "evidencia": _lista(d, "evidencia", 1, 8),
        "riesgos": _lista(d, "riesgos", 2, 10),
        "stop_pct": _num(d, "stop_pct", 0, 30),
        "objetivo_pct": _num(d, "objetivo_pct", 0, 200),
        "horizonte_dias": int(_num(d, "horizonte_dias", 4, 365)),
        "prob_exito": _num(d, "prob_exito", 0.99, 99),  # % de llegar al objetivo antes que al stop
        "tamano_pct": _num(d, "tamano_pct", 0, MAX_TAMANO_PCT),
        "costo_ida_vuelta_pct": float(d.get("costo_ida_vuelta_pct", COSTO_IDA_VUELTA_PCT)),
    }
    if out["objetivo_pct"] <= out["stop_pct"] * 0.5:
        raise ErrorTesis("el objetivo es demasiado chico frente al stop (riesgo/beneficio muy malo)")
    if any(t["ticker"] == out["ticker"] for t in abiertas):
        raise ErrorTesis(f"ya hay una tesis abierta para {out['ticker']}")
    expuesto = sum(t["tamano_pct"] for t in abiertas) + out["tamano_pct"]
    if expuesto > MAX_EXPOSICION_PCT:
        raise ErrorTesis(f"exposición abierta total {expuesto:.1f}% > máximo {MAX_EXPOSICION_PCT}%")
    return out


def _hash(prev: str, core: dict) -> str:
    return hashlib.sha256((prev + json.dumps(core, sort_keys=True, ensure_ascii=False)).encode("utf-8")).hexdigest()


class Cuaderno:
    def __init__(self, ruta: Path = RUTA_POR_DEFECTO):
        self.ruta = Path(ruta)

    # ---------------------------------------------------------------- bajo nivel
    def _leer(self) -> List[dict]:
        if not self.ruta.exists():
            return []
        return [json.loads(l) for l in self.ruta.read_text(encoding="utf-8").splitlines() if l.strip()]

    def _agregar(self, tipo: str, tid: str, datos: dict, ts: datetime) -> dict:
        ev = self._leer()
        prev = ev[-1]["hash"] if ev else "0" * 64
        core = {"n": len(ev) + 1, "ts": ts.isoformat(), "tipo": tipo, "id": tid, "datos": datos}
        linea = {**core, "prev": prev, "hash": _hash(prev, core)}
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with self.ruta.open("a", encoding="utf-8") as f:
            f.write(json.dumps(linea, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return linea

    def verificar(self) -> Tuple[bool, str]:
        prev = "0" * 64
        for i, e in enumerate(self._leer(), 1):
            core = {k: e[k] for k in ("n", "ts", "tipo", "id", "datos")}
            if e["n"] != i or e["prev"] != prev or e["hash"] != _hash(prev, core):
                return False, f"cadena rota en la línea {i}: el cuaderno fue modificado"
            prev = e["hash"]
        return True, "cadena íntegra"

    # ------------------------------------------------------------------- estado
    def tesis(self) -> Dict[str, dict]:
        out: Dict[str, dict] = {}
        for e in self._leer():
            if e["tipo"] == "abrir":
                out[e["id"]] = {**e["datos"], "id": e["id"], "abierta_ts": e["ts"], "estado": "abierta",
                                "notas": [], "cierre": None}
            elif e["tipo"] == "nota":
                out[e["id"]]["notas"].append({"ts": e["ts"], "texto": e["datos"]["texto"]})
            elif e["tipo"] == "cerrar":
                out[e["id"]]["estado"], out[e["id"]]["cierre"] = "cerrada", e["datos"]
        return out

    def abiertas(self) -> List[dict]:
        return [t for t in self.tesis().values() if t["estado"] == "abierta"]

    # ----------------------------------------------------------------- acciones
    def abrir(self, nueva: dict, mercado: dict, ts: Optional[datetime] = None) -> str:
        """`nueva` ya validada; `mercado` lo aporta el sistema (precios de referencia)."""
        ts = ts or datetime.now(timezone.utc)
        ok, msg = self.verificar()
        if not ok:
            raise ErrorTesis(msg)
        tid = f"T-{len(self.tesis()) + 1:04d}"
        apertura = ts.date()
        datos = {**nueva, **mercado, "fecha_apertura": apertura.isoformat(),
                 "fecha_fin": (apertura + timedelta(days=nueva["horizonte_dias"])).isoformat()}
        self._agregar("abrir", tid, datos, ts)
        return tid

    def nota(self, tid: str, texto: str, ts: Optional[datetime] = None) -> None:
        if tid not in self.tesis() or len(texto.strip()) < 5:
            raise ErrorTesis("tesis inexistente o nota vacía")
        self._agregar("nota", tid, {"texto": texto.strip()}, ts or datetime.now(timezone.utc))

    def cerrar(self, tid: str, resultado: dict, ts: Optional[datetime] = None) -> None:
        t = self.tesis().get(tid)
        if not t or t["estado"] != "abierta":
            raise ErrorTesis("tesis inexistente o ya cerrada")
        self._agregar("cerrar", tid, resultado, ts or datetime.now(timezone.utc))
