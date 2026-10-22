"""Datos de mercado públicos (sin claves). Interfaz mínima para poder simular en tests."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Protocol

import pandas as pd
import requests

from backtest import BASE_URLS, download_klines
from paper_trading.broker import Quote

HISTORIA_DIAS = 320  # > SMA lenta (200) con margen


class MarketData(Protocol):
    def candles(self, symbol: str, hasta: date) -> pd.DataFrame:
        """Velas diarias CERRADAS hasta `hasta` (exclusivo)."""

    def quote(self, symbol: str) -> Quote: ...

    def day_open(self, symbol: str, dia: date) -> float:
        """Apertura de la vela diaria de `dia` (UTC)."""


def _get(path: str, params: dict):
    base = [u.rsplit("/klines", 1)[0] for u in BASE_URLS]
    ultimo = None
    for b in base:
        try:
            r = requests.get(f"{b}/{path}", params=params, timeout=20)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            ultimo = e
    raise RuntimeError(f"Sin respuesta de los endpoints públicos: {ultimo}")


class BinancePublic:
    def candles(self, symbol: str, hasta: date) -> pd.DataFrame:
        desde = (pd.Timestamp(hasta) - pd.Timedelta(days=HISTORIA_DIAS)).date().isoformat()
        return download_klines(symbol, desde, hasta.isoformat())

    def quote(self, symbol: str) -> Quote:
        d = _get("ticker/bookTicker", {"symbol": symbol})
        return Quote(bid=float(d["bidPrice"]), ask=float(d["askPrice"]))

    def day_open(self, symbol: str, dia: date) -> float:
        ms = int(datetime(dia.year, dia.month, dia.day, tzinfo=timezone.utc).timestamp() * 1000)
        k = _get("klines", {"symbol": symbol, "interval": "1d", "startTime": ms, "limit": 1})
        if not k or int(k[0][0]) != ms:
            raise RuntimeError(f"No hay vela de apertura de {dia} para {symbol}")
        return float(k[0][1])
