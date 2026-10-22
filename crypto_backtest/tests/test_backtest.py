import numpy as np
import pandas as pd
import pytest

from backtest import make_weights, run_backtest, simulate, validar_datos
from robustness import GATES, cost_sensitivity, evaluar_gates, param_sensitivity, robustez, walk_forward


def datos(n=700, drift=(0.0015, 0.0012), crash_desde=None, crash=0.012, ruido=0.04, dip=False):
    """Sintético y determinista. NO es mercado real."""
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    t = np.arange(n)
    out = {}
    for (sym, base, ph), mu in zip((("BTCUSDT", 10000, 0.0), ("ETHUSDT", 800, 0.7)), drift):
        c = base * np.exp(mu * t + ruido * np.sin(t / 17 + ph))
        if crash_desde is not None:
            c = c * np.where(t > crash_desde, np.exp(-crash * (t - crash_desde)), 1.0)
        if dip:  # caída del ~26% en 10 días (día 450-460) y la tendencia sigue después
            c = c * np.where(t <= 450, 1.0, np.where(t <= 460, np.exp(-0.03 * (t - 450)), np.exp(-0.3)))
        out[sym] = pd.DataFrame({"open": c * 0.998, "high": c * 1.01, "low": c * 0.99,
                                 "close": c, "volume": 1000.0}, index=idx)
    return out


# ---------------------------------------------------------------- señal
def test_pesos_largo_solo_y_tope():
    close = pd.DataFrame({"BTCUSDT": np.linspace(100, 300, 300), "ETHUSDT": np.linspace(10, 60, 300)})
    w = make_weights(close)
    assert (w >= 0).all().all() and (w <= 0.5).all().all()
    assert (w.sum(axis=1) <= 1.0 + 1e-12).all()


# ------------------------------------------------------- sin mirar el futuro
def test_equity_no_depende_de_datos_futuros():
    a = datos()
    T = a["BTCUSDT"].index[500]
    b = {s: d.copy() for s, d in a.items()}
    for d in b.values():
        d.loc[d.index > T, ["open", "high", "low", "close"]] *= 3.0  # futuro alterado
    _, sa, _ = run_backtest(a, eval_start="2021-03-01")
    _, sb, _ = run_backtest(b, eval_start="2021-03-01")
    pd.testing.assert_series_equal(sa.equity.loc[:T], sb.equity.loc[:T])
    assert not sa.equity.equals(sb.equity)  # y el futuro alterado sí cambia lo posterior


# ------------------------------------------------------------ contabilidad
def test_mercado_bajista_se_queda_en_efectivo():
    rep, strat, bench = run_backtest(datos(drift=(-0.003, -0.003)))
    assert strat.equity.eq(1000.0).all()
    assert strat.turnover_usdt.sum() == 0
    assert bench.equity.iloc[-1] < 1000.0  # el benchmark sí sufre


def test_costos_reducen_el_resultado():
    d = datos()
    barato, _, _ = run_backtest(d, fee=0.0, slippage=0.0)
    caro, _, _ = run_backtest(d, fee=0.01, slippage=0.005)
    assert caro["strategy"]["ending_equity_usdt"] < barato["strategy"]["ending_equity_usdt"]
    assert caro["benchmark_50_50"]["ending_equity_usdt"] < barato["benchmark_50_50"]["ending_equity_usdt"]


def test_sin_costos_ni_kill_switch_la_comision_acumulada_es_cero():
    rep, strat, _ = run_backtest(datos(), fee=0.0, slippage=0.0)
    assert rep["strategy"]["total_costs_usdt"] == 0.0


def test_efectivo_nunca_negativo_y_pesos_validos():
    _, strat, bench = run_backtest(datos())
    for log in (strat, bench):
        assert (log.exposure <= 1.0 + 1e-9).all()
        assert np.isfinite(log.equity).all() and (log.equity > 0).all()


# ------------------------------------------------------------ kill switch
def test_kill_switch_liquida_con_costo_y_no_vuelve():
    _, strat, _ = run_backtest(datos(crash_desde=450), kill_dd=0.15)
    activo = strat.kill_switch_active
    assert activo.any()
    k = activo.values.argmax()
    salida = strat.iloc[k + 1]
    assert salida.turnover_usdt > 0 and salida.cost_usdt > 0       # la salida cuesta
    assert (strat.exposure.iloc[k + 1:] < 1e-9).all()              # queda en efectivo
    assert strat.equity.iloc[k + 2:].nunique() == 1                # equity plana después


def test_kill_switch_enfriamiento_y_rearme():
    d = datos(dip=True)
    _, con, _ = run_backtest(d, kill_dd=0.15, kill_cooldown_days=30)
    _, perm, _ = run_backtest(d, kill_dd=0.15, kill_cooldown_days=None)
    k = con.kill_switch_active.values.argmax()
    assert (con.exposure.iloc[k + 1:k + 31] < 1e-9).all()        # 30 días fuera
    assert con.exposure.iloc[k + 31:].max() > 0.3                 # y después vuelve a invertir
    assert perm.exposure.iloc[k + 1:].max() < 1e-9                # permanente: nunca vuelve


def test_kill_switch_apagado_no_liquida():
    _, strat, _ = run_backtest(datos(crash_desde=450), kill_dd=None)
    assert not strat.kill_switch_active.any()


# ------------------------------------------------------- rebalanceo por desvío
def test_benchmark_paga_rebalanceo_por_desvio():
    rep, _, bench = run_backtest(datos(drift=(0.004, 0.0), ruido=0.0), drift_band=0.05)
    assert rep["benchmark_50_50"]["trade_events"] > 1


# ------------------------------------------------------------- calentamiento
def test_eval_start_sin_historia_previa_falla():
    with pytest.raises(ValueError, match="historia previa"):
        run_backtest(datos(), eval_start="2020-02-20")


def test_historia_corta_falla():
    with pytest.raises(ValueError, match="220"):
        run_backtest(datos(100))


def test_con_calentamiento_la_estrategia_invierte_desde_el_inicio():
    _, strat, _ = run_backtest(datos(), eval_start="2021-01-01")
    assert strat.exposure.iloc[1] > 0.3


# ------------------------------------------------------------------ datos
def test_validacion_detecta_huecos_y_precios_malos():
    d = datos()["BTCUSDT"]
    with pytest.raises(ValueError, match="faltan días"):
        validar_datos(d.drop(d.index[10]), "X")
    malo = d.copy()
    malo.iloc[5, malo.columns.get_loc("close")] = -1
    with pytest.raises(ValueError, match="no positivos"):
        validar_datos(malo, "X")
    nan = d.copy()
    nan.iloc[5, 0] = np.nan
    with pytest.raises(ValueError, match="faltantes"):
        validar_datos(nan, "X")


def test_reproducible():
    d = datos()
    a, b = run_backtest(d)[0], run_backtest(d)[0]
    assert a == b and a["configuration"]["real_orders_enabled"] is False


def test_parametros_invalidos():
    with pytest.raises(ValueError):
        run_backtest(datos(), fast=200, slow=50)
    with pytest.raises(ValueError):
        run_backtest(datos(), fee=-0.1)


# --------------------------------------------------------------- robustez
def test_robustez_estructura_y_gates():
    d = datos(900)
    kw = dict(eval_start="2021-01-01")
    assert len(walk_forward(d, n_windows=3)) == 3
    assert len(cost_sensitivity(d, **kw)) == 4
    assert sum(p["es_base"] for p in param_sensitivity(d, **kw)) == 1
    r = robustez(d, **kw)
    assert set(r["gates"]) == set(GATES)
    assert isinstance(r["aprobado"], bool)


def test_gate_con_sharpe_nulo_no_aprueba():
    d = datos(900, drift=(-0.003, -0.003))  # estrategia siempre en efectivo: sharpe None
    r = robustez(d, eval_start="2021-01-01")
    assert r["aprobado"] is False
    assert r["gates"]["sharpe_con_costos_3x"]["ok"] is False
