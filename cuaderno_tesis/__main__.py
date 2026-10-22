"""CLI:  python -m cuaderno_tesis <comando>   (desde la raíz del repo)

  plantilla                       imprime un JSON de ejemplo para completar
  abrir --archivo tesis.json      registra la tesis (toma precios de referencia automáticamente)
  nota T-0001 "texto"             agrega una nota fechada (no edita la tesis original)
  cerrar T-0001                   salida discrecional anticipada (queda marcada como 'manual')
  resolver                        cierra por stop/objetivo/horizonte las que correspondan
  listar                          muestra las tesis
  reporte                         métricas y criterios de evidencia
  verificar                       comprueba que el cuaderno no fue modificado
"""
import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from cuaderno_tesis import metricas, resolver
from cuaderno_tesis.modelo import (COSTO_IDA_VUELTA_PCT, LIQUIDEZ_MIN_ARS, MAX_EXPOSICION_PCT, MAX_TAMANO_PCT,
                                   RUTA_POR_DEFECTO, Cuaderno, ErrorTesis, validar_nueva)
from cuaderno_tesis.precios import Yahoo

PLANTILLA = {
    "ticker": "AAPL", "autor": "yo | claude",
    "tesis": "Por qué debería subir en el horizonte, con el mecanismo concreto (mínimo 80 caracteres).",
    "catalizador": "Qué evento o dato concreto lo dispararía y cuándo",
    "evidencia": ["https://... fuente 1 (resultado, filing, nota)", "https://... fuente 2"],
    "riesgos": ["Qué me haría equivocarme #1", "Qué me haría equivocarme #2"],
    "stop_pct": 8, "objetivo_pct": 15, "horizonte_dias": 60, "prob_exito": 40,
    "tamano_pct": 2,
}


def main(argv=None, precios=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("cmd", choices=["plantilla", "abrir", "nota", "cerrar", "resolver", "listar", "reporte", "verificar"])
    p.add_argument("args", nargs="*")
    p.add_argument("--archivo", help="JSON con la tesis (abrir)")
    p.add_argument("--cuaderno", default=str(RUTA_POR_DEFECTO), help="Ruta del cuaderno (por defecto fuera del repo)")
    a = p.parse_args(argv)
    c, precios = Cuaderno(Path(a.cuaderno)), precios or Yahoo()

    try:
        if a.cmd == "plantilla":
            print(json.dumps(PLANTILLA, indent=2, ensure_ascii=False))
            print(f"\n# Límites: tamano_pct <= {MAX_TAMANO_PCT}, exposición abierta total <= {MAX_EXPOSICION_PCT}%, "
                  f"costo supuesto {COSTO_IDA_VUELTA_PCT}% ida y vuelta (podés cargar costo_ida_vuelta_pct).", file=sys.stderr)
        elif a.cmd == "abrir":
            if not a.archivo:
                raise ErrorTesis("falta --archivo")
            nueva = validar_nueva(json.loads(Path(a.archivo).read_text(encoding="utf-8")), c.abiertas())
            u, b = precios.ultimo(nueva["ticker"]), precios.ultimo("SPY")
            mercado = {"precio_ref": u["precio"], "bench_ref": b["precio"],
                       "liquidez_diaria_ars": u["liquidez_diaria_ars"], "ccl_ref": precios.ccl()}
            if (u["liquidez_diaria_ars"] or 0) < LIQUIDEZ_MIN_ARS:
                print(f"AVISO: liquidez diaria baja ({u['liquidez_diaria_ars']}). Puede costar más salir.")
            tid = c.abrir(nueva, mercado)
            print(f"{tid} registrada: {nueva['ticker']} a {u['precio']} ARS | stop {nueva['stop_pct']}% | "
                  f"objetivo {nueva['objetivo_pct']}% | fin {c.tesis()[tid]['fecha_fin']}")
        elif a.cmd == "nota":
            c.nota(a.args[0], " ".join(a.args[1:]))
            print("nota agregada")
        elif a.cmd == "cerrar":
            t = c.tesis()[a.args[0]]
            px = precios.ultimo(t["ticker"])["precio"]
            bx = precios.ultimo("SPY")["precio"]
            res = resolver.construir_cierre(t, "manual", date.today(), px, [(date.today(), bx)])
            c.cerrar(t["id"], res)
            print(json.dumps(res, indent=2))
        elif a.cmd == "resolver":
            hechas = resolver.resolver_todo(c, precios)
            for tid, r in hechas:
                print(f"{tid}: {r['motivo']} el {r['fecha']} | neto {r['retorno_neto_pct']}% | "
                      f"vs SPY {r['exceso_vs_bench_pct']:+}%")
            print(f"{len(hechas)} tesis cerradas; {len(c.abiertas())} siguen abiertas")
        elif a.cmd == "listar":
            for t in c.tesis().values():
                est = t["estado"] if not t["cierre"] else f"{t['cierre']['motivo']} {t['cierre']['retorno_neto_pct']}%"
                print(f"{t['id']} {t['ticker']:6} {t['autor']:6} {t['fecha_apertura']} -> {t['fecha_fin']} [{est}]")
        elif a.cmd == "reporte":
            r = metricas.reporte(c.tesis())
            print(json.dumps(r, indent=2, ensure_ascii=False))
            print(json.dumps(metricas.evaluar_gates(r["total"]), indent=2))
            print("Superar los criterios NO prueba ventaja: solo habilita considerar posiciones reales mínimas.")
        elif a.cmd == "verificar":
            ok, msg = c.verificar()
            print(msg)
            return 0 if ok else 1
    except (ErrorTesis, KeyError, IndexError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # red, formato, etc.
        print(f"ERROR inesperado: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
