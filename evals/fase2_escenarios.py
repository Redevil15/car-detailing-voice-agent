"""Escenarios de evaluación de Fase 2.

Cinco conversaciones, dos de ellas ambiguas, con verificaciones OBJETIVAS:
qué tool se llamó, con qué argumentos, qué ruta tomó el grafo y qué quedó en
la base de datos. Nada se juzga "a ojo". Es la base de las métricas de Fase 5.

La base se regenera al empezar, para que cada corrida sea comparable.
Requiere el servidor MCP corriendo en el puerto 8000.

    uv run evals/fase2_escenarios.py
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from agent.grafo import construir_agente, entrada_de_turno
from core.settings import obtener_ajustes
from mcp_server.db.conexion import conectar
from mcp_server.db.seed import construir as regenerar_base

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


# ------------------------------------------------------------------ fechas

def en_palabras(dia: date) -> str:
    return f"el {DIAS[dia.weekday()]} {dia.day} de {MESES[dia.month - 1]}"


def proximo(dia_semana: int) -> date:
    """El próximo día de la semana dado, al menos dos días en el futuro."""
    dia = date.today() + timedelta(days=2)
    while dia.weekday() != dia_semana:
        dia += timedelta(days=1)
    return dia


def fecha_con_cupo(hora: str) -> date:
    """Primer día desde pasado mañana con cupo libre a esa hora.

    Las fechas del seed son relativas al día en que se generó la base, así que
    los escenarios también deben serlo: una fecha fija caducaría en una semana.
    """
    conexion = conectar()
    try:
        fila = conexion.execute(
            """
            SELECT d.fecha FROM disponibilidad d
            LEFT JOIN citas c
              ON c.fecha = d.fecha AND c.hora = d.hora AND c.estado = 'confirmada'
            WHERE d.hora = ? AND d.fecha >= ?
            GROUP BY d.fecha, d.hora
            HAVING d.cupo_total - COUNT(c.id) > 0
            ORDER BY d.fecha LIMIT 1
            """,
            (hora, (date.today() + timedelta(days=2)).isoformat()),
        ).fetchone()
    finally:
        conexion.close()
    return date.fromisoformat(fila["fecha"])


# ----------------------------------------------------------- modelo de datos

@dataclass
class ResultadoTurno:
    frase: str
    ruta: list[str]
    respuesta: str
    llamadas: list[tuple[str, dict]]
    segundos: float


# Una verificación devuelve None si pasa, o el motivo del fallo.
Verificacion = Callable[[ResultadoTurno], "str | None"]


@dataclass
class Escenario:
    nombre: str
    turnos: list[tuple[str, Verificacion | None]]
    final: Callable[[], "str | None"] | None = None
    ambiguo: bool = False


# ------------------------------------------------------------ verificaciones

def llamo(nombre: str, **esperados) -> Verificacion:
    def verificar(r: ResultadoTurno):
        for n, args in r.llamadas:
            if n == nombre and all(args.get(k) == v for k, v in esperados.items()):
                return None
        return f"se esperaba {nombre}({esperados or ''}); hubo {r.llamadas or 'ninguna tool'}"
    return verificar


def no_llamo(nombre: str) -> Verificacion:
    def verificar(r: ResultadoTurno):
        if any(n == nombre for n, _ in r.llamadas):
            return f"llamó {nombre} sin tener todos los datos"
        return None
    return verificar


def termina_en(nodo: str) -> Verificacion:
    def verificar(r: ResultadoTurno):
        return None if r.ruta[-1:] == [nodo] else f"la ruta debía terminar en {nodo}: {r.ruta}"
    return verificar


def menciona(*alternativas: str) -> Verificacion:
    def verificar(r: ResultadoTurno):
        texto = r.respuesta.lower()
        return None if any(a in texto for a in alternativas) else f"no menciona {alternativas}"
    return verificar


def todas(*verificaciones: Verificacion) -> Verificacion:
    def verificar(r: ResultadoTurno):
        for v in verificaciones:
            if (motivo := v(r)) is not None:
                return motivo
        return None
    return verificar


def cita_unica(fecha: date, hora: str, sufijo_telefono: str, servicio: str):
    """Verifica en la BASE, no en lo que dijo el agente: exactamente una cita."""
    def verificar():
        conexion = conectar()
        try:
            filas = conexion.execute(
                """
                SELECT s.nombre FROM citas c
                JOIN clientes cl ON cl.id = c.cliente_id
                JOIN servicios s ON s.id = c.servicio_id
                WHERE c.fecha = ? AND c.hora = ? AND c.estado = 'confirmada'
                  AND REPLACE(REPLACE(cl.telefono, ' ', ''), '-', '') LIKE ?
                """,
                (fecha.isoformat(), hora, f"%{sufijo_telefono}"),
            ).fetchall()
        finally:
            conexion.close()
        if not filas:
            return "no se creó la cita en la base"
        if len(filas) > 1:
            return f"se crearon {len(filas)} citas: agendó por duplicado"
        if filas[0]["nombre"] != servicio:
            return f"servicio equivocado en la base: {filas[0]['nombre']}"
        return None
    return verificar


# ---------------------------------------------------------------- ejecución

async def correr_turno(grafo, config: dict, frase: str) -> ResultadoTurno:
    previo = await grafo.aget_state(config)
    ya_habia = len(previo.values.get("messages", [])) if previo.values else 0

    inicio = time.perf_counter()
    ruta: list[str] = []
    async for paso in grafo.astream(entrada_de_turno(frase), config, stream_mode="updates"):
        ruta.extend(paso.keys())
    segundos = time.perf_counter() - inicio

    estado = await grafo.aget_state(config)
    nuevos = estado.values["messages"][ya_habia:]
    llamadas = [
        (c["name"], c["args"])
        for m in nuevos if m.type == "ai"
        for c in (m.tool_calls or [])
    ]
    return ResultadoTurno(frase, ruta, str(nuevos[-1].content), llamadas, segundos)


def construir_escenarios() -> list[Escenario]:
    jueves = proximo(3)
    dia_cita = fecha_con_cupo("11:00")
    return [
        Escenario("Precio directo", [
            ("¿Cuánto cuesta el encerado?",
             todas(llamo("consultar_precio"), menciona("1200", "1,200", "mil doscientos"))),
        ]),
        Escenario("Ambigüedad: 'el lavado', resuelta con memoria", [
            ("¿Cuánto sale el lavado?", termina_en("clarificar")),
            ("El premium, por favor", menciona("650", "seiscientos cincuenta")),
        ], ambiguo=True),
        Escenario("Ambigüedad: servicio que no existe", [
            ("¿Ustedes hacen cambio de aceite?",
             todas(termina_en("clarificar"), menciona("no lo manejamos"))),
        ], ambiguo=True),
        Escenario(f"Fecha en lenguaje natural ({en_palabras(jueves)})", [
            (f"¿Tienen lugar {en_palabras(jueves)}?",
             llamo("checar_disponibilidad", fecha=jueves.isoformat())),
        ]),
        Escenario("Agendar de punta a punta", [
            (f"Quiero agendar un encerado para {en_palabras(dia_cita)} a las once de la mañana",
             no_llamo("registrar_servicio")),
            ("Me llamo Ramona Pérez y mi teléfono es 55 1234 5678", None),
            # Si el agente ya agendó en el turno anterior, este "sí" es la
            # trampa clásica: una tool NO idempotente llamada dos veces.
            ("Sí, así está bien", None),
        ], final=cita_unica(dia_cita, "11:00", "12345678", "Encerado")),
    ]


async def main() -> None:
    regenerar_base()
    grafo = await construir_agente(obtener_ajustes())
    escenarios = construir_escenarios()

    aprobados, verificaciones, fallidas, tiempos = 0, 0, 0, []

    for numero, escenario in enumerate(escenarios, start=1):
        config = {"configurable": {"thread_id": f"eval-{numero}"}}
        motivos: list[str] = []
        print(f"\n[{numero}/{len(escenarios)}] {escenario.nombre}")

        for frase, verificar in escenario.turnos:
            r = await correr_turno(grafo, config, frase)
            tiempos.append(r.segundos)
            print(f"   CLIENTE: {frase}")
            print(f"   ruta   : {' -> '.join(r.ruta)}  ({r.segundos:.2f}s)")
            print(f"   AGENTE : {r.respuesta}")
            if verificar:
                verificaciones += 1
                if (motivo := verificar(r)) is not None:
                    fallidas += 1
                    motivos.append(motivo)
            await asyncio.sleep(1.5)

        if escenario.final:
            verificaciones += 1
            if (motivo := escenario.final()) is not None:
                fallidas += 1
                motivos.append(motivo)

        if motivos:
            print("   >>> FALLÓ")
            for motivo in motivos:
                print(f"       - {motivo}")
        else:
            aprobados += 1
            print("   >>> APROBADO")

    ambiguos = sum(e.ambiguo for e in escenarios)
    print("\n" + "=" * 72)
    print(f"Escenarios aprobados : {aprobados}/{len(escenarios)}  ({ambiguos} ambiguos)")
    print(f"Verificaciones       : {verificaciones - fallidas}/{verificaciones}")
    print(f"Latencia por turno   : media {sum(tiempos) / len(tiempos):.2f}s · máx {max(tiempos):.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
