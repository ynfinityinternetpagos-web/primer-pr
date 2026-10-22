import json
from datetime import date, datetime, timedelta, timezone

import pytest

from cuaderno_tesis import __main__ as cli
from cuaderno_tesis import metricas, resolver
from cuaderno_tesis.modelo import Cuaderno, ErrorTesis, validar_nueva

T0 = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
MERCADO = {"precio_ref": 100.0, "bench_ref": 1000.0, "liquidez_diaria_ars": 5e7, "ccl_ref": 1500.0}


def base(**kw):
    d = {"ticker": "aapl", "autor": "yo",
         "tesis": "Los servicios crecen más rápido que el hardware y mejoran el margen operativo; el mercado "
                  "todavía lo valúa como una empresa de dispositivos.",
         "catalizador": "Resultados trimestrales del 30/01",
         "evidencia": ["https://ejemplo.com/10-q"], "riesgos": ["Regulación antimonopolio", "Desaceleración en China"],
         "stop_pct": 8, "objetivo_pct": 15, "horizonte_dias": 30, "prob_exito": 40, "tamano_pct": 2}
    d.update(kw)
    return d


def abrir(c, ts=T0, **kw):
    nueva = validar_nueva(base(**kw), c.abiertas())
    return c.abrir(nueva, MERCADO, ts)


class FakePrecios:
    def __init__(self, serie, bench, px=100.0, bx=1000.0):
        self.serie, self.bench, self.px, self.bx = serie, bench, px, bx

    def ultimo(self, t):
        return {"precio": self.bx if t == "SPY" else self.px, "liquidez_diaria_ars": 5e7}

    def cierres(self, t, desde):
        return self.bench if t == "SPY" else self.serie

    def ccl(self):
        return 1500.0


def serie(*pares):
    return [(date(2026, 1, 5) + timedelta(days=d), p) for d, p in pares]


# ------------------------------------------------------------- validación
@pytest.mark.parametrize("campo,valor", [
    ("tesis", "corta"), ("evidencia", []), ("riesgos", ["uno solo"]), ("tamano_pct", 6),
    ("stop_pct", 0), ("stop_pct", 40), ("autor", "otro"), ("prob_exito", 0), ("prob_exito", 100),
    ("horizonte_dias", 2), ("ticker", "AA PL"), ("objetivo_pct", 2),
])
def test_validacion_rechaza(campo, valor):
    with pytest.raises(ErrorTesis):
        validar_nueva(base(**{campo: valor}), [])


def test_validacion_limites_de_cartera(tmp_path):
    c = Cuaderno(tmp_path / "t.jsonl")
    abrir(c)
    with pytest.raises(ErrorTesis, match="ya hay"):
        validar_nueva(base(), c.abiertas())
    for i, tk in enumerate(["MSFT", "KO", "NVDA", "AMZN", "GOOGL"]):
        abrir(c, ticker=tk, tamano_pct=5)            # 2 + 25 = 27%
    with pytest.raises(ErrorTesis, match="exposición"):
        validar_nueva(base(ticker="META", tamano_pct=4), c.abiertas())


# -------------------------------------------------------- integridad
def test_cadena_de_hashes_detecta_ediciones(tmp_path):
    ruta = tmp_path / "t.jsonl"
    c = Cuaderno(ruta)
    abrir(c)
    c.nota("T-0001", "se publicó el balance")
    assert c.verificar()[0]
    ruta.write_text(ruta.read_text(encoding="utf-8").replace("Resultados trimestrales", "Resultados MEJORADOS"), encoding="utf-8")
    ok, msg = c.verificar()
    assert not ok and "modificado" in msg
    with pytest.raises(ErrorTesis):
        abrir(c, ticker="MSFT")                      # no se puede seguir escribiendo sobre una cadena rota


def test_borrar_o_reordenar_lineas_tambien_se_detecta(tmp_path):
    ruta = tmp_path / "t.jsonl"
    c = Cuaderno(ruta)
    abrir(c)
    c.nota("T-0001", "nota uno")
    c.nota("T-0001", "nota dos")
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    ruta.write_text("\n".join([lineas[0], lineas[2], lineas[1]]) + "\n", encoding="utf-8")
    assert not c.verificar()[0]
    ruta.write_text("\n".join([lineas[0], lineas[2]]) + "\n", encoding="utf-8")
    assert not c.verificar()[0]


def test_la_tesis_original_no_se_edita_las_notas_se_suman(tmp_path):
    c = Cuaderno(tmp_path / "t.jsonl")
    abrir(c)
    antes = c.tesis()["T-0001"]["tesis"]
    c.nota("T-0001", "cambió el contexto macro")
    t = c.tesis()["T-0001"]
    assert t["tesis"] == antes and len(t["notas"]) == 1 and t["ticker"] == "AAPL"


# ------------------------------------------------------------ resolución
def tesis_abierta(tmp_path):
    c = Cuaderno(tmp_path / "t.jsonl")
    abrir(c)
    return c, c.tesis()["T-0001"]


NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
BENCH = serie((1, 1000), (10, 1050), (30, 1100))


def test_sale_por_stop_con_gap(tmp_path):
    _, t = tesis_abierta(tmp_path)
    r = resolver.evaluar(t, serie((1, 99), (2, 90), (3, 120)), BENCH, NOW)  # 90 <= stop 92
    assert r["motivo"] == "stop" and r["precio_salida"] == 90 and r["fecha"] == "2026-01-07"
    assert r["retorno_bruto_pct"] == -10 and r["retorno_neto_pct"] == pytest.approx(-11.2)


def test_sale_por_objetivo_y_mide_contra_benchmark(tmp_path):
    _, t = tesis_abierta(tmp_path)
    r = resolver.evaluar(t, serie((1, 101), (10, 116)), BENCH, NOW)
    assert r["motivo"] == "objetivo" and r["objetivo_alcanzado"]
    assert r["bench_retorno_pct"] == pytest.approx(5.0)
    assert r["exceso_vs_bench_pct"] == pytest.approx(16.0 - 1.2 - 5.0)  # salió a 116: +16% bruto


def test_sale_por_horizonte(tmp_path):
    _, t = tesis_abierta(tmp_path)
    r = resolver.evaluar(t, serie((1, 101), (15, 103), (30, 104), (40, 150)), BENCH, NOW)
    assert r["motivo"] == "horizonte" and r["fecha"] == "2026-02-04" and r["precio_salida"] == 104


def test_no_resuelve_si_no_se_cumple_nada_o_es_de_hoy(tmp_path):
    _, t = tesis_abierta(tmp_path)
    assert resolver.evaluar(t, serie((1, 101), (10, 105)), BENCH, NOW) is None
    hoy = datetime(2026, 1, 20, 12, 0, tzinfo=timezone.utc)
    assert resolver.evaluar(t, serie((1, 101), (15, 80)), BENCH, hoy) is None  # la vela de hoy se ignora
    assert resolver.evaluar(t, serie((15, 80)), BENCH, hoy + timedelta(days=1))["motivo"] == "stop"


def test_sin_benchmark_no_se_resuelve(tmp_path):
    _, t = tesis_abierta(tmp_path)
    assert resolver.evaluar(t, serie((2, 90)), [], NOW) is None


def test_resolver_todo_cierra_y_persiste(tmp_path):
    c, _ = tesis_abierta(tmp_path)
    hechas = resolver.resolver_todo(c, FakePrecios(serie((2, 90)), BENCH), NOW)
    assert [h[0] for h in hechas] == ["T-0001"]
    assert c.tesis()["T-0001"]["estado"] == "cerrada" and c.verificar()[0]
    assert resolver.resolver_todo(c, FakePrecios(serie((2, 90)), BENCH), NOW) == []  # idempotente


# --------------------------------------------------------------- métricas
def cerrada(autor, neto, exceso, hit, prob):
    return {"estado": "cerrada", "autor": autor, "prob_exito": prob, "tamano_pct": 2,
            "cierre": {"retorno_neto_pct": neto, "exceso_vs_bench_pct": exceso, "objetivo_alcanzado": hit}}


def test_reporte_avisa_con_pocas_jugadas_y_separa_autores():
    ts = {f"T{i}": cerrada("yo" if i % 2 else "claude", 5.0, 2.0, i % 3 == 0, 50) for i in range(6)}
    r = metricas.reporte(ts)
    assert "aviso" in r and r["total"]["cerradas"] == 6
    assert r["por_autor"]["yo"]["cerradas"] == 3 and r["por_autor"]["claude"]["cerradas"] == 3
    assert metricas.reporte({})["total"] == {"cerradas": 0}


def test_gates_exigen_muestra_ventaja_y_calibracion():
    malos = {f"T{i}": cerrada("yo", -3.0, -2.0, False, 60) for i in range(60)}
    g = metricas.evaluar_gates(metricas.reporte(malos)["total"])
    assert not g["exceso_vs_bench_prom_pct"]["ok"] and not g["brier"]["ok"]
    pocos = {f"T{i}": cerrada("yo", 9.0, 8.0, True, 70) for i in range(20)}
    assert not metricas.evaluar_gates(metricas.reporte(pocos)["total"])["cerradas"]["ok"]
    import random
    random.seed(1)
    buenos = {f"T{i}": cerrada("yo", 6 + random.random(), 3 + random.random(), i % 2 == 0, 50) for i in range(60)}
    g = metricas.evaluar_gates(metricas.reporte(buenos)["total"])
    assert all(v["ok"] for v in g.values())


# -------------------------------------------------------------------- CLI
def test_cli_flujo_completo(tmp_path, capsys):
    ruta, plantilla = tmp_path / "c.jsonl", tmp_path / "t.json"
    plantilla.write_text(json.dumps(base()), encoding="utf-8")
    p = FakePrecios(serie((2, 90)), BENCH)
    run = lambda *a: cli.main(["--cuaderno", str(ruta), *a], precios=p)
    assert run("abrir", "--archivo", str(plantilla)) == 0
    assert run("nota", "T-0001", "salió el balance") == 0
    assert run("listar") == 0 and run("verificar") == 0
    assert run("abrir", "--archivo", str(plantilla)) == 2             # duplicado -> error de validación
    assert run("cerrar", "T-0001") == 0
    assert Cuaderno(ruta).tesis()["T-0001"]["cierre"]["motivo"] == "manual"
    assert run("reporte") == 0
    assert "T-0001" in capsys.readouterr().out
    ruta.write_text(ruta.read_text(encoding="utf-8").replace("AAPL", "MSFT"), encoding="utf-8")
    assert run("verificar") == 1                                      # manipulado -> falla
