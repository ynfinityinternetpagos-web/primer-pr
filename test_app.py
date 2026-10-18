import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import app


class TestPromedio(unittest.TestCase):
    def test_promedio(self):
        self.assertEqual(app.promedio([10, 20, 30]), 20)

    def test_lista_vacia(self):
        with self.assertRaises(ValueError):
            app.promedio([])


class TestEsMayor(unittest.TestCase):
    def test_limites(self):
        self.assertEqual([app.es_mayor(e) for e in (17, 18, 19)], [False, True, True])


class TestBuscarUsuario(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.db = os.path.join(self.dir.name, "test.db")
        patcher = mock.patch.object(app, "DB_PATH", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _crear_base(self):
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE usuarios (id INTEGER, nombre TEXT)")
        conn.executemany("INSERT INTO usuarios VALUES (?, ?)", [(1, "ana"), (2, "luis")])
        conn.commit()
        conn.close()

    def test_base_inexistente_no_crea_archivo(self):
        with self.assertRaises(FileNotFoundError):
            app.buscar_usuario("ana")
        self.assertFalse(os.path.exists(self.db))

    def test_encuentra_usuario(self):
        self._crear_base()
        self.assertEqual(app.buscar_usuario("ana"), [(1, "ana")])

    def test_inyeccion_sql_no_funciona(self):
        self._crear_base()
        self.assertEqual(app.buscar_usuario("' OR '1'='1"), [])

    def test_falta_la_tabla(self):
        sqlite3.connect(self.db).close()
        with self.assertRaises(sqlite3.Error):
            app.buscar_usuario("ana")


class TestLeerConfig(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def _archivo(self, contenido):
        ruta = os.path.join(self.dir.name, "config.txt")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(contenido)
        return ruta

    def test_dict_valido(self):
        self.assertEqual(app.leer_config(self._archivo("{'a': 1}")), {"a": 1})

    def test_rechaza_lo_que_no_es_dict(self):
        with self.assertRaises(ValueError):
            app.leer_config(self._archivo("[1, 2]"))

    def test_rechaza_sintaxis_invalida(self):
        with self.assertRaises(ValueError):
            app.leer_config(self._archivo("{"))

    def test_no_ejecuta_codigo(self):
        with self.assertRaises(ValueError):
            app.leer_config(self._archivo("__import__('os').getcwd()"))


if __name__ == "__main__":
    unittest.main()
