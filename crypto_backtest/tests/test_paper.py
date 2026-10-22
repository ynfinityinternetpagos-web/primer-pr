from datetime import datetime, timezone

import pandas as pd
import pytest

from backtest import run_backtest
from paper_trading import runner
from paper_trading.broker import Order, PaperBroker, Quote
from paper_trading.risk import Limits, revisar
from test_backtest import datos

SIN_LIMITES = Limits(kill_dd=None, max_daily_loss=None, max_order_pct=10, min_order_usdt=0.0)


class MercadoFalso:
    """Reproduce datos sintéticos día por día: a las 00:10 UTC de `dia` el precio es la apertura."""

    def __init__(self, data, spread_pct=0.0, atrasar_dias=0, falla=False):
        self.data, self.spread, self.atraso, self.falla, self.dia = data, spread_pct, atrasar_dias, falla, None

    def candles(self, symbol, hasta):
        if self.falla:
            raise ConnectionError("sin red")
        df = self.data[symbol]
        corte = pd.Timestamp(hasta, tz="UTC") - pd.Timedelta(days=self.atraso)
        return df[df.index < corte].tail(320)

    def _open(self, symbol):
        return float(self.data[symbol].loc[pd.Timestamp(self.dia, tz="UTC"), "open"])

    def quote(self, symbol):
        o, h = self._open(symbol), self.spread / 200
        return Quote(bid=o * (1 - h), ask=o * (1 + h))

    def day_open(self, symbol, dia):
        return self._open(symbol)


def a_las(dia):
    return datetime(dia.year, dia.month, dia.day, 0, 10, tzinfo=timezone.utc)


def correr(mercado, tmp_path, dias, **kw):
    out = []
    for d in dias:
        mercado.dia = d.date()
        out.append(runner.ejecutar_dia(mercado, tmp_path / "s.json", tmp_path / "j.jsonl", now=a_las(d), **kw))
    return out


# ------------------------------------------------------------------- broker
def test_broker_compra_al_ask_vende_al_bid_con_comision():
    b = PaperBroker(1000.0, fee=0.001)
    q = Quote(bid=99.0, ask=101.0)
    f = b.place_order(Order("X", "buy", 5.0, 100.0), q, "t")
    assert f.price == 101.0 and f.fee == pytest.approx(0.505)
    assert b.cash == pytest.approx(1000 - 505 - 0.505)
    b.place_order(Order("X", "sell", 5.0, 100.0), q, "t")
    assert b.cash < 1000.0  # ida y vuelta sin cambio de precio cuesta spread + comisiones
    b.verificar()


def test_broker_compra_parcial_y_sin_shorts():
    b = PaperBroker(100.0, fee=0.0)
    f = b.place_order(Order("X", "buy", 10.0, 100.0), Quote(100.0, 100.0), "t")
    assert f.partial and f.qty == pytest.approx(1.0)
    s = b.place_order(Order("X", "sell", 99.0, 100.0), Quote(100.0, 100.0), "t")
    assert s.partial and s.qty == pytest.approx(1.0)  # nunca se vende más de lo que hay
    assert b.place_order(Order("X", "sell", 1.0, 100.0), Quote(100.0, 100.0), "t") is None


def test_broker_serializa_sin_perdida():
    b = PaperBroker(1000.0, fee=0.001)
    b.place_order(Order("X", "buy", 3.0, 100.0), Quote(99.0, 101.0), "t")
    c = PaperBroker.from_dict(b.to_dict())
    assert c.cash == b.cash and c.units == b.units and c.fee == b.fee


# ---------------------------------------------------------------- riskguard
def test_riskguard_limites():
    lim = Limits()
    mids = {"A": 100.0, "B": 100.0}
    grande = Order("A", "buy", 7.0, 100.0)  # 700 > 60% de 1000
    ok = Order("A", "buy", 5.0, 100.0)
    polvo = Order("B", "buy", 0.05, 100.0)  # 5 USDT < mínimo
    venta = Order("A", "sell", 9.0, 100.0)  # vender nunca se bloquea
    apr, pol, rech = revisar([grande, ok, polvo], 1000.0, {}, mids, lim)
    assert apr == [ok] and len(pol) == 1 and len(rech) == 1
    apr, _, rech = revisar([venta], 1000.0, {"A": 9.0}, mids, lim)
    assert apr == [venta] and not rech
    cinco = [Order("A", "buy", 1.0, 100.0)] * 5
    assert revisar(cinco, 1000.0, {}, mids, lim)[0] == []  # demasiadas órdenes
    # ya hay 500 USDT en A; comprar 400 más en B llevaría la exposición a 112% de la equity (800)
    apr, _, rech = revisar([Order("B", "buy", 4.0, 100.0)], 800.0, {"A": 5.0}, mids, lim)
    assert apr == [] and "exposición" in rech[-1]


# -------------------------------------------------------------- corrida diaria
def test_paridad_de_decisiones_con_el_backtest(tmp_path):
    d = datos(900, ruido=0.25)  # ruido alto: la señal cambia muchas veces
    idx = d["BTCUSDT"].index
    dias = list(idx[220:])
    res = correr(MercadoFalso(d), tmp_path, dias, limites=SIN_LIMITES)
    assert all(r["status"] == "ok" for r in res)
    ent = runner.leer_journal(tmp_path / "j.jsonl")
    dias_paper = {e["date"] for e in ent if e["fills"]}
    _, strat, _ = run_backtest(d, eval_start=str(idx[220].date()), slippage=0.0005, kill_dd=None)
    dias_bt = {str(x.date()) for x in strat.index[strat.turnover_usdt > 1e-9]}
    assert dias_paper == dias_bt and len(dias_bt) > 15
    broker, meta = runner.cargar_estado(tmp_path / "s.json", 1000.0, 0.001)  # el estado persistió
    assert meta["last_run_date"] == str(idx[-1].date())
    assert ent[-1]["equity"] == pytest.approx(broker.equity({s: float(d[s]["open"].iloc[-1]) for s in d}))


def test_slippage_medido_contra_la_apertura(tmp_path):
    d = datos()
    dias = list(d["BTCUSDT"].index[220:300])
    correr(MercadoFalso(d, spread_pct=0.04), tmp_path, dias, limites=SIN_LIMITES)
    r = runner.resumen(tmp_path / "j.jsonl")
    assert r["operaciones"] > 0
    assert r["slippage_prom_adverso_pct"] == pytest.approx(0.02, abs=1e-6)  # medio spread


def test_idempotente_por_dia(tmp_path):
    d = datos()
    dia = d["BTCUSDT"].index[300]
    m = MercadoFalso(d)
    r = correr(m, tmp_path, [dia, dia])
    assert [x["status"] for x in r] == ["ok", "skipped"]
    assert len(runner.leer_journal(tmp_path / "j.jsonl")) == 1


def test_falla_de_datos_no_toca_el_estado_y_se_reintenta(tmp_path):
    d = datos()
    dia = d["BTCUSDT"].index[300]
    m = MercadoFalso(d, falla=True)
    assert correr(m, tmp_path, [dia])[0]["status"] == "error"
    assert not (tmp_path / "s.json").exists()
    m.falla = False
    assert correr(m, tmp_path, [dia])[0]["status"] == "ok"  # mismo día: reintenta
    assert [e["status"] for e in runner.leer_journal(tmp_path / "j.jsonl")] == ["error", "ok"]


def test_datos_desactualizados_abortan(tmp_path):
    d = datos()
    r = correr(MercadoFalso(d, atrasar_dias=3), tmp_path, [d["BTCUSDT"].index[300]])[0]
    assert r["status"] == "error" and "desactualizados" in r["error"]


def test_mercado_sospechoso_aborta(tmp_path):
    d = datos()
    r = correr(MercadoFalso(d, spread_pct=5.0), tmp_path, [d["BTCUSDT"].index[300]])[0]
    assert r["status"] == "error" and "spread" in r["error"]


def test_kill_switch_liquida_y_solo_se_rearma_a_mano(tmp_path):
    d = datos(crash_desde=450)
    idx = d["BTCUSDT"].index
    m = MercadoFalso(d)
    correr(m, tmp_path, list(idx[220:520]))
    ent = runner.leer_journal(tmp_path / "j.jsonl")
    k = next(i for i, e in enumerate(ent) if e["killed"])
    assert sum(ent[k]["units"].values()) < 1e-9                      # liquidó todo
    assert all(e["killed"] and not any(f["side"] == "buy" for f in e["fills"]) for e in ent[k:])
    runner.rearmar(tmp_path / "s.json", tmp_path / "j.jsonl")
    with pytest.raises(RuntimeError):
        runner.rearmar(tmp_path / "s.json", tmp_path / "j.jsonl")    # ya no estaba activo
    _, meta = runner.cargar_estado(tmp_path / "s.json", 1000.0, 0.001)
    assert meta["killed"] is False and meta["peak"] is None


def test_dias_sin_correr_se_registran(tmp_path):
    d = datos()
    idx = d["BTCUSDT"].index
    correr(MercadoFalso(d), tmp_path, [idx[300], idx[303]])
    assert runner.leer_journal(tmp_path / "j.jsonl")[-1]["dias_sin_correr"] == 2


# ------------------------------------------------------------------ reporte
def test_criterios_etapa1(tmp_path):
    d = datos()
    correr(MercadoFalso(d, spread_pct=0.04), tmp_path, list(d["BTCUSDT"].index[220:330]))
    ev = runner.evaluar_etapa1(runner.resumen(tmp_path / "j.jsonl"))
    assert set(ev) == set(runner.ETAPA1)
    assert all(v["ok"] for v in ev.values())            # 110 días, sin fallas, slippage 0.02%
    corto = runner.evaluar_etapa1({"dias_corridos": 10, "errores": 5})
    assert not corto["dias_corridos"]["ok"] and not corto["fallas_pct"]["ok"]
    assert not runner.evaluar_etapa1({})["slippage_prom_adverso_pct"]["ok"]  # sin datos = no aprueba


def test_retraso_y_desvio_se_miden_aparte_del_spread(tmp_path):
    d = datos()
    dia = d["BTCUSDT"].index[300]
    m = MercadoFalso(d, spread_pct=0.04)
    m.dia = dia.date()
    tarde = datetime(dia.year, dia.month, dia.day, 15, 30, tzinfo=timezone.utc)
    runner.ejecutar_dia(m, tmp_path / "s.json", tmp_path / "j.jsonl", now=tarde, limites=SIN_LIMITES)
    r = runner.resumen(tmp_path / "j.jsonl")
    assert r["max_retraso_min"] == 15 * 60 + 30
    assert not runner.evaluar_etapa1(r)["max_retraso_min"]["ok"]  # correr tarde no aprueba
    assert r["slippage_prom_adverso_pct"] == pytest.approx(0.02, abs=1e-6)
