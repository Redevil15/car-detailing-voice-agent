"""Punto único de acceso a la base de datos mock."""

import sqlite3
from pathlib import Path

RUTA_BD = Path(__file__).parent / "detailing.db"


def conectar() -> sqlite3.Connection:
    """Abre una conexión configurada correctamente.

    Existe para que las tres opciones de abajo NUNCA se olviden. Cada una
    es una fuente clásica de bugs silenciosos.
    """
    if not RUTA_BD.exists():
        raise FileNotFoundError(
            f"No existe {RUTA_BD}. Genérala con: uv run mcp_server/db/seed.py"
        )

    conexion = sqlite3.connect(RUTA_BD)

    # 1. Filas accesibles por nombre de columna: fila["precio_mxn"].
    conexion.row_factory = sqlite3.Row

    # 2. SQLite trae las claves foráneas DESACTIVADAS por defecto, y el ajuste
    #    es por conexión, no por base de datos. Sin esto se pueden insertar
    #    citas con servicio_id inexistente y SQLite no protesta.
    conexion.execute("PRAGMA foreign_keys = ON")

    # 3. Autocommit: desactiva el manejo implícito de transacciones de Python
    #    para poder abrirlas explícitamente con BEGIN IMMEDIATE donde importa.
    conexion.isolation_level = None

    return conexion
