import ast
import contextlib
import os
import sqlite3

DB_PATH = os.environ.get("USUARIOS_DB", "usuarios.db")


def promedio(numeros: list[float]) -> float:
    """Devuelve el promedio de una lista no vacía de números."""
    if not numeros:
        raise ValueError("No se puede calcular el promedio de una lista vacía")
    return sum(numeros) / len(numeros)


def buscar_usuario(nombre: str) -> list[tuple]:
    """Busca usuarios por nombre exacto usando una consulta parametrizada.

    Lanza FileNotFoundError si la base no existe y sqlite3.Error si la
    consulta falla (por ejemplo, si falta la tabla).
    """
    if not os.path.isfile(DB_PATH):
        raise FileNotFoundError(f"No existe la base de datos: {DB_PATH}")
    with contextlib.closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.execute(
            "SELECT id, nombre FROM usuarios WHERE nombre = ?", (nombre,)
        )
        return cur.fetchall()


def leer_config(ruta: str) -> dict:
    """Lee un archivo con un literal de Python (sin ejecutar código).

    Lanza ValueError si el contenido no es un literal válido o no es un dict.
    """
    with open(ruta, encoding="utf-8") as f:
        try:
            datos = ast.literal_eval(f.read())
        except (ValueError, SyntaxError) as e:
            raise ValueError(f"Config inválida en {ruta}: {e}") from e
    if not isinstance(datos, dict):
        raise ValueError(f"La config en {ruta} debe ser un dict")
    return datos


def es_mayor(edad: int) -> bool:
    """True si la persona tiene 18 años o más."""
    return edad >= 18


def main() -> None:
    print(promedio([10, 20, 30]))
    try:
        print(buscar_usuario(input("Nombre: ")))
    except (FileNotFoundError, sqlite3.Error) as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
