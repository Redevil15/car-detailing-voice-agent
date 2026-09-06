"""Genera la base de datos mock con datos sintéticos.

Idempotente: borra la BD y la reconstruye desde cero en cada ejecución.
No usa NINGÚN dato real de clientes del negocio.

    uv run mcp_server/db/seed.py
"""

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DIRECTORIO = Path(__file__).parent
RUTA_BD = DIRECTORIO / "detailing.db"
RUTA_SCHEMA = DIRECTORIO / "schema.sql"

# Semilla fija: los datos son aleatorios pero REPRODUCIBLES. Necesario para
# que las métricas de evaluación de Fase 5 se puedan comparar entre corridas.
random.seed(42)

SERVICIOS = [
    ("Lavado básico", "Lavado exterior a mano y secado con microfibra", 350, 45),
    ("Lavado premium", "Lavado exterior, interior, llantas y cristales", 650, 90),
    ("Encerado", "Aplicación de cera protectora con pulidora orbital", 1200, 120),
    ("Pulido completo", "Corrección de pintura en tres pasos", 2800, 300),
    ("Limpieza de interiores", "Aspirado profundo, shampoo de asientos y tapetes", 900, 150),
    ("Tratamiento cerámico", "Recubrimiento cerámico con garantía de 2 años", 8500, 480),
    ("Descontaminación de pintura", "Barra de arcilla y descontaminante ferroso", 1500, 180),
]

NOMBRES = [
    "María Hernández", "José Ramírez", "Guadalupe Torres", "Antonio Flores",
    "Rosa Martínez", "Francisco Gómez", "Carmen Díaz", "Roberto Sánchez",
]

HORARIOS = ["09:00", "11:00", "13:00", "15:00", "17:00"]
CUPOS_POR_FRANJA = 2
DIAS_A_GENERAR = 30


def construir() -> None:
    if RUTA_BD.exists():
        RUTA_BD.unlink()

    conexion = sqlite3.connect(RUTA_BD)
    conexion.executescript(RUTA_SCHEMA.read_text(encoding="utf-8"))

    conexion.executemany(
        "INSERT INTO servicios (nombre, descripcion, precio_mxn, duracion_min)"
        " VALUES (?, ?, ?, ?)",
        SERVICIOS,
    )

    conexion.executemany(
        "INSERT INTO clientes (nombre, telefono) VALUES (?, ?)",
        [(nombre, f"55{random.randint(10000000, 99999999)}") for nombre in NOMBRES],
    )

    # Agenda de los próximos 30 días. El taller cierra los domingos.
    hoy = date.today()
    franjas = []
    for offset in range(DIAS_A_GENERAR):
        dia = hoy + timedelta(days=offset)
        if dia.weekday() == 6:  # domingo
            continue
        for hora in HORARIOS:
            franjas.append((dia.isoformat(), hora, CUPOS_POR_FRANJA))

    conexion.executemany(
        "INSERT INTO disponibilidad (fecha, hora, cupo_total) VALUES (?, ?, ?)",
        franjas,
    )

    # Ocupación parcial: ~35% de las franjas con al menos una cita. Sin esto,
    # checar_disponibilidad() diría "todo libre" siempre y no probaría nada.
    ids_servicio = [fila[0] for fila in conexion.execute("SELECT id FROM servicios")]
    ids_cliente = [fila[0] for fila in conexion.execute("SELECT id FROM clientes")]

    citas = []
    for fecha, hora, cupo in franjas:
        for _ in range(cupo):
            if random.random() < 0.35:
                citas.append(
                    (
                        random.choice(ids_cliente),
                        random.choice(ids_servicio),
                        fecha,
                        hora,
                    )
                )

    conexion.executemany(
        "INSERT INTO citas (cliente_id, servicio_id, fecha, hora) VALUES (?, ?, ?, ?)",
        citas,
    )

    conexion.commit()

    print(f"Base creada en {RUTA_BD}")
    for tabla in ("servicios", "clientes", "disponibilidad", "citas"):
        total = conexion.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
        print(f"  {tabla:<16} {total:>5} filas")

    conexion.close()


if __name__ == "__main__":
    construir()
