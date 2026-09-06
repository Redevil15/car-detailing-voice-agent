"""Las tres herramientas de negocio, como funciones Python puras.

Este módulo NO importa nada de MCP a propósito: la lógica se puede probar
sin levantar el servidor. El registro en el protocolo ocurre en server.py.

Las docstrings de las funciones públicas no son documentación decorativa:
son el texto que el LLM lee para decidir si llamar la herramienta. Escribir
una docstring vaga aquí es un bug funcional.
"""

import unicodedata
from datetime import date

from pydantic import BaseModel, Field

from mcp_server.db.conexion import conectar

CONSULTA_LIBRES = """
    SELECT d.hora, d.cupo_total - COUNT(c.id) AS libres
    FROM disponibilidad d
    LEFT JOIN citas c
      ON c.fecha = d.fecha AND c.hora = d.hora AND c.estado = 'confirmada'
    WHERE d.fecha = ?
    GROUP BY d.hora
    ORDER BY d.hora
"""


def _normalizar(texto: str) -> str:
    """Minúsculas y sin acentos.

    El texto llega de un motor de voz: 'lavado básico', 'Lavado Basico' y
    'LAVADO BASICO' deben tratarse igual. Por eso el emparejamiento se hace
    en Python y no con LIKE de SQL: SQLite solo ignora mayúsculas en ASCII,
    así que 'basico' nunca coincidiría con 'básico'.
    """
    descompuesto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn").strip()


class ResultadoPrecio(BaseModel):
    encontrado: bool = Field(description="True si se identificó un único servicio")
    servicio: str | None = Field(default=None, description="Nombre oficial del servicio")
    precio_mxn: int | None = Field(default=None, description="Precio en pesos mexicanos")
    duracion_min: int | None = Field(default=None, description="Duración estimada en minutos")
    descripcion: str | None = Field(default=None, description="Qué incluye el servicio")
    sugerencias: list[str] = Field(
        default_factory=list,
        description="Servicios candidatos cuando no hubo una coincidencia única",
    )


def consultar_precio(servicio: str) -> ResultadoPrecio:
    """Consulta el precio y la duración de un servicio de car detailing.

    Úsala cuando el cliente pregunte cuánto cuesta algo, cuánto tarda, o qué
    incluye un servicio. El nombre puede venir aproximado o incompleto.

    Si el texto coincide con varios servicios, devuelve encontrado=False y la
    lista de candidatos en 'sugerencias' para que se le pregunte al cliente
    cuál quiere. No adivines por él.
    """
    conexion = conectar()
    try:
        filas = conexion.execute(
            "SELECT nombre, descripcion, precio_mxn, duracion_min"
            " FROM servicios WHERE activo = 1 ORDER BY precio_mxn"
        ).fetchall()
    finally:
        conexion.close()

    buscado = _normalizar(servicio)
    coincidencias = [
        fila for fila in filas
        if buscado and (buscado in _normalizar(fila["nombre"])
                        or _normalizar(fila["nombre"]) in buscado)
    ]

    if len(coincidencias) == 1:
        fila = coincidencias[0]
        return ResultadoPrecio(
            encontrado=True,
            servicio=fila["nombre"],
            precio_mxn=fila["precio_mxn"],
            duracion_min=fila["duracion_min"],
            descripcion=fila["descripcion"],
        )

    candidatos = coincidencias if coincidencias else filas
    return ResultadoPrecio(
        encontrado=False,
        sugerencias=[fila["nombre"] for fila in candidatos],
    )


class ResultadoDisponibilidad(BaseModel):
    fecha: str = Field(description="Fecha consultada en formato AAAA-MM-DD")
    abierto: bool = Field(description="True si el taller opera ese día")
    horas_libres: list[str] = Field(description="Horas con al menos un cupo libre")
    mensaje: str = Field(description="Explicación en lenguaje natural del resultado")


def checar_disponibilidad(fecha: str) -> ResultadoDisponibilidad:
    """Consulta qué horarios tienen cupo libre en una fecha dada.

    La fecha debe ir en formato AAAA-MM-DD. Si el cliente dice 'el sábado' o
    'mañana', conviértelo a fecha absoluta antes de llamar esta herramienta.

    El taller cierra los domingos y solo tiene agenda para los próximos 30
    días; fuera de ese rango devuelve abierto=False.
    """
    try:
        dia = date.fromisoformat(fecha)
    except ValueError:
        return ResultadoDisponibilidad(
            fecha=fecha, abierto=False, horas_libres=[],
            mensaje="Formato de fecha inválido, se esperaba AAAA-MM-DD.",
        )

    if dia < date.today():
        return ResultadoDisponibilidad(
            fecha=fecha, abierto=False, horas_libres=[],
            mensaje="Esa fecha ya pasó.",
        )

    conexion = conectar()
    try:
        filas = conexion.execute(CONSULTA_LIBRES, (fecha,)).fetchall()
    finally:
        conexion.close()

    if not filas:
        return ResultadoDisponibilidad(
            fecha=fecha, abierto=False, horas_libres=[],
            mensaje="El taller no tiene agenda para esa fecha (cierra domingos).",
        )

    libres = [fila["hora"] for fila in filas if fila["libres"] > 0]
    if not libres:
        return ResultadoDisponibilidad(
            fecha=fecha, abierto=True, horas_libres=[],
            mensaje="Ese día está completamente lleno.",
        )

    return ResultadoDisponibilidad(
        fecha=fecha, abierto=True, horas_libres=libres,
        mensaje=f"Hay {len(libres)} horarios disponibles.",
    )


class ResultadoRegistro(BaseModel):
    exito: bool = Field(description="True si la cita quedó agendada")
    cita_id: int | None = Field(default=None, description="Folio de la cita creada")
    mensaje: str = Field(description="Confirmación o motivo del rechazo")


def registrar_servicio(
    cliente: str, telefono: str, servicio: str, fecha: str, hora: str
) -> ResultadoRegistro:
    """Agenda una cita para un cliente. Tiene efectos: crea un registro real.

    Antes de llamarla debes tener los cinco datos confirmados con el cliente.
    Verifica la disponibilidad con checar_disponibilidad primero: esta
    herramienta rechaza la cita si la franja ya no tiene cupo.

    'fecha' va en AAAA-MM-DD y 'hora' en HH:MM de 24 horas.
    """
    precio = consultar_precio(servicio)
    if not precio.encontrado:
        opciones = ", ".join(precio.sugerencias)
        return ResultadoRegistro(
            exito=False,
            mensaje=f"No identifiqué el servicio de forma única. Opciones: {opciones}",
        )

    conexion = conectar()
    try:
        # BEGIN IMMEDIATE toma el bloqueo de escritura AL ABRIR la transacción,
        # no en el primer INSERT. Sin esto, dos llamadas simultáneas podrían
        # leer "queda 1 cupo" a la vez y ambas insertar: sobreventa clásica.
        conexion.execute("BEGIN IMMEDIATE")

        fila = conexion.execute(
            CONSULTA_LIBRES.replace("GROUP BY d.hora", "AND d.hora = ? GROUP BY d.hora"),
            (fecha, hora),
        ).fetchone()

        if fila is None:
            conexion.execute("ROLLBACK")
            return ResultadoRegistro(
                exito=False, mensaje=f"El taller no abre el {fecha} a las {hora}."
            )

        if fila["libres"] <= 0:
            conexion.execute("ROLLBACK")
            return ResultadoRegistro(
                exito=False, mensaje=f"Ya no hay cupo el {fecha} a las {hora}."
            )

        existente = conexion.execute(
            "SELECT id FROM clientes WHERE telefono = ?", (telefono,)
        ).fetchone()
        if existente:
            cliente_id = existente["id"]
        else:
            cliente_id = conexion.execute(
                "INSERT INTO clientes (nombre, telefono) VALUES (?, ?)",
                (cliente, telefono),
            ).lastrowid

        servicio_id = conexion.execute(
            "SELECT id FROM servicios WHERE nombre = ?", (precio.servicio,)
        ).fetchone()["id"]

        cita_id = conexion.execute(
            "INSERT INTO citas (cliente_id, servicio_id, fecha, hora)"
            " VALUES (?, ?, ?, ?)",
            (cliente_id, servicio_id, fecha, hora),
        ).lastrowid

        conexion.execute("COMMIT")
    finally:
        conexion.close()

    return ResultadoRegistro(
        exito=True,
        cita_id=cita_id,
        mensaje=(
            f"Cita confirmada para {cliente}: {precio.servicio} el {fecha} "
            f"a las {hora}. Costo {precio.precio_mxn} pesos, "
            f"duración aproximada {precio.duracion_min} minutos. Folio {cita_id}."
        ),
    )
