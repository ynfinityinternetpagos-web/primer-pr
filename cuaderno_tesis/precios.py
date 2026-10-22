"""Fuentes de precios. Yahoo Finance NO es una API oficial: puede cambiar o bloquear.
Si falla, el cuaderno permite cargar el precio de referencia a mano (queda marcado)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Protocol, Tuple

import requests

UA = {"User-Agent": "Mozilla/5.0"}


class Precios(Protocol):
    def ultimo(self, ticker: str) -> dict:
        """{'precio': float (ARS), 'liquidez_diaria_ars': float|None}"""

    def cierres(self, ticker: str, desde: date) -> List[Tuple[date, float]]:
        """Cierres diarios (fecha, precio) desde `desde`."""

    def ccl(self) -> Optional[float]: ...


class Yahoo:
    URL = "https://query1.finance.yahoo.com/v8/finance/chart/{s}.BA"

    def _chart(self, ticker: str, rango: str) -> dict:
        r = requests.get(self.URL.format(s=ticker), params={"range": rango, "interval": "1d"},
                         headers=UA, timeout=20)
        r.raise_for_status()
        res = r.json()["chart"]["result"]
        if not res:
            raise RuntimeError(f"Yahoo no devolvió datos para {ticker}.BA")
        return res[0]

    def ultimo(self, ticker: str) -> dict:
        c = self._chart(ticker, "3mo")
        q = c["indicators"]["quote"][0]
        valores = [p * v for p, v in zip(q["close"][-20:], q["volume"][-20:]) if p and v]
        return {"precio": float(c["meta"]["regularMarketPrice"]),
                "liquidez_diaria_ars": sum(valores) / len(valores) if valores else None}

    def cierres(self, ticker: str, desde: date) -> List[Tuple[date, float]]:
        dias = (date.today() - desde).days
        c = self._chart(ticker, "1y" if dias <= 330 else "2y")
        off = c["meta"].get("gmtoffset", 0)
        out = []
        for ts, px in zip(c["timestamp"], c["indicators"]["quote"][0]["close"]):
            if px is not None:
                d = (datetime.fromtimestamp(ts, timezone.utc) + timedelta(seconds=off)).date()
                if d >= desde:
                    out.append((d, float(px)))
        return out

    def ccl(self) -> Optional[float]:
        try:
            r = requests.get("https://dolarapi.com/v1/dolares/contadoconliqui", timeout=20)
            r.raise_for_status()
            return float(r.json()["venta"])
        except Exception:
            return None
