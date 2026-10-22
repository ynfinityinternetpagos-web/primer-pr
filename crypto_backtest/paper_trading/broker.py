"""Interfaz de broker y PaperBroker (simulado).

No existe un LiveBroker a propósito: solo se escribe después de que el paper trading
apruebe la etapa 1 (ver DISENO.md).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_pct(self) -> float:
        return (self.ask - self.bid) / self.mid * 100.0


@dataclass(frozen=True)
class Order:
    symbol: str
    side: str      # "buy" | "sell"
    qty: float     # unidades del activo (> 0)
    ref_price: float  # precio medio usado para dimensionar


@dataclass(frozen=True)
class Fill:
    symbol: str
    side: str
    qty: float
    price: float
    fee: float
    notional: float
    ts: str
    partial: bool = False


class Broker(ABC):
    @abstractmethod
    def balances(self) -> Dict[str, float]: ...

    @abstractmethod
    def place_order(self, order: Order, quote: Quote, ts: str) -> Optional[Fill]: ...


class PaperBroker(Broker):
    """Cuenta simulada. Compra al ask y vende al bid (spread real del libro) más comisión.
    Ignora la profundidad del libro: válido para montos chicos (cientos de USDT)."""

    def __init__(self, capital: float = 1000.0, fee: float = 0.001):
        if capital <= 0 or fee < 0:
            raise ValueError("capital positivo y comisión no negativa")
        self.fee = fee
        self.cash = float(capital)
        self.units: Dict[str, float] = {}

    def balances(self) -> Dict[str, float]:
        return {"USDT": self.cash, **self.units}

    def equity(self, mids: Dict[str, float]) -> float:
        return self.cash + sum(q * mids[s] for s, q in self.units.items())

    def place_order(self, order: Order, quote: Quote, ts: str) -> Optional[Fill]:
        if order.qty <= 0 or order.side not in ("buy", "sell"):
            raise ValueError(f"orden inválida: {order}")
        qty, partial = order.qty, False
        if order.side == "buy":
            precio = quote.ask
            max_qty = self.cash / (precio * (1 + self.fee))
            if qty > max_qty:                      # fondos insuficientes: compra parcial
                qty, partial = max_qty, True
            if qty <= 0:
                return None
            notional = qty * precio
            fee = notional * self.fee
            self.cash -= notional + fee
            self.units[order.symbol] = self.units.get(order.symbol, 0.0) + qty
        else:
            precio = quote.bid
            tengo = self.units.get(order.symbol, 0.0)
            if qty > tengo:                        # nunca se vende más de lo que hay (sin shorts)
                qty, partial = tengo, True
            if qty <= 0:
                return None
            notional = qty * precio
            fee = notional * self.fee
            self.cash += notional - fee
            self.units[order.symbol] = tengo - qty
        return Fill(order.symbol, order.side, qty, precio, fee, notional, ts, partial)

    def verificar(self) -> None:
        """Invariantes de contabilidad: si fallan, algo está mal y hay que parar."""
        if self.cash < -1e-6 or any(q < -1e-12 for q in self.units.values()):
            raise RuntimeError(f"Estado inválido: cash={self.cash}, units={self.units}")

    def to_dict(self) -> dict:
        return {"fee": self.fee, "cash": self.cash, "units": self.units}

    @classmethod
    def from_dict(cls, d: dict) -> "PaperBroker":
        b = cls(capital=1.0, fee=d["fee"])
        b.cash, b.units = float(d["cash"]), {k: float(v) for k, v in d["units"].items()}
        return b


def fill_a_dict(f: Fill) -> dict:
    return asdict(f)
