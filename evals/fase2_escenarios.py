"""Escenarios de evaluación de Fase 2.

Siete conversaciones, dos de ellas ambiguas, con verificaciones OBJETIVAS:
qué tool se llamó, con qué argumentos, qué ruta tomó el grafo y qué quedó en
la base de datos. Nada se juzga "a ojo". Es la base de las métricas de Fase 5.

La base se regenera al empezar, para que cada corrida sea comparable.
Requiere el servidor MCP corriendo en el puerto 8000.

    uv run evals/fase2_escenarios.py
"""

from __future__ import annotations

import asyncio
import re
import time
import unicodedata
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


def fecha_con_cupo_en(*horas: str) -> date:
    """Primer día desde pasado mañana con cupo libre en TODAS esas horas."""
    conexion = conectar()
    try:
        filas = conexion.execute(
            f"""
            SELECT d.fecha, d.hora FROM disponibilidad d
            LEFT JOIN citas c
              ON c.fecha = d.fecha AND c.hora = d.hora AND c.estado = 'confirmada'
            WHERE d.hora IN ({",".join("?" * len(horas))}) AND d.fecha >= ?
            GROUP BY d.fecha, d.hora
            HAVING d.cupo_total - COUNT(c.id) > 0
            """,
            (*horas, (date.today() + timedelta(days=2)).isoformat()),
        ).fetchall()
    finally:
        conexion.close()
    libres: dict[str, set[str]] = {}
    for fila in filas:
        libres.setdefault(fila["fecha"], set()).add(fila["hora"])
    return date.fromisoformat(min(f for f, h in libres.items() if h >= set(horas)))


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


def no_menciona(*prohibidas: str) -> Verificacion:
    def verificar(r: ResultadoTurno):
        texto = r.respuesta.lower()
        dichas = [p for p in prohibidas if p in texto]
        return f"no debía decir {dichas}" if dichas else None
    return verificar


# Formas típicas de tuteo. Es una heurística para detectar regresiones, no un
# analizador gramatical: puede equivocarse con frases poco comunes.
TUTEO = (" tienes", " quieres", " te gustaría", " puedes", " tu ", "¿tienes", "¿quieres", "¿te ")


def usa_usted() -> Verificacion:
    def verificar(r: ResultadoTurno):
        texto = f" {r.respuesta.lower()} "
        encontrado = [t.strip() for t in TUTEO if t in texto]
        return f"tutea al cliente: {encontrado}" if encontrado else None
    return verificar


_NUMEROS = {"un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
            "cinco": 5, "seis": 6, "siete": 7, "ocho": 8}
_DURACION = re.compile(
    r"dura\w*\s+(?:(?:de|es|aproximad\w*|unos?|unas|como)\s+)*"
    r"(\d+|un|una|dos|tres|cuatro|cinco|seis|siete|ocho)\s+(horas?|minutos?)"
)


def duracion_correcta(minutos: int) -> Verificacion:
    """Si la respuesta dice cuánto dura algo, debe ser la duración real.

    Atrapa datos inventados: qwen3.5:2b dijo "dura una hora" de un servicio de
    120 minutos, y ninguna verificación lo detectó.
    """
    def verificar(r: ResultadoTurno):
        texto = "".join(
            c for c in unicodedata.normalize("NFD", r.respuesta.lower())
            if unicodedata.category(c) != "Mn"
        )
        dichas = [
            (int(n) if n.isdigit() else _NUMEROS[n]) * (60 if unidad.startswith("hora") else 1)
            for n, unidad in _DURACION.findall(texto)
        ]
        malas = [d for d in dichas if d != minutos]
        return f"dijo una duración de {malas} min; la real es {minutos}" if malas else None
    return verificar


_PRECIO = re.compile(r"(\d[\d,.]*)\s*pesos")


def _precios_del_catalogo() -> set[int]:
    conexion = conectar()
    try:
        return {fila["precio_mxn"] for fila in conexion.execute("SELECT precio_mxn FROM servicios")}
    finally:
        conexion.close()


def precios_reales() -> Verificacion:
    """Todo precio dicho en pesos (con dígitos) debe existir en el catálogo.

    Atrapa precios inventados: qwen3.5:2b dijo que el lavado premium cuesta
    25,000 pesos cuando cuesta 650. Es una heurística: no entiende precios
    escritos con palabras ni sumas de varios servicios.
    """
    def verificar(r: ResultadoTurno):
        dichos = {int(re.sub(r"[,.]", "", n)) for n in _PRECIO.findall(r.respuesta.lower())}
        inventados = sorted(dichos - _precios_del_catalogo())
        return f"precio que no existe en el catálogo: {inventados}" if inventados else None
    return verificar


_PROMESAS = ("quedo agendada", "queda agendada", "le agendo", "ya quedo", "cita confirmada",
             "he agendado", "esta agendada", "quedo registrada", "la agende")


def no_finge_agendar() -> Verificacion:
    """Si el agente dice que agendo, el turno DEBE haber pasado por ejecutar_registro.

    Prometer una cita que no existe es el fallo mas caro de este negocio: el
    cliente llega al taller y no tiene lugar.
    """
    def verificar(r: ResultadoTurno):
        texto = "".join(
            c for c in unicodedata.normalize("NFD", r.respuesta.lower())
            if unicodedata.category(c) != "Mn"
        )
        promesas = [p for p in _PROMESAS if p in texto]
        if promesas and "ejecutar_registro" not in r.ruta:
            return f"dijo que agendo ({promesas}) sin pasar por ejecutar_registro: {r.ruta}"
        return None
    return verificar


def no_imita_confirmacion() -> Verificacion:
    """La confirmacion la escribe el grafo, no el modelo.

    Si el modelo redacta "Para confirmar: ..." sin haber llamado a la
    herramienta, el texto suena igual pero no hay ningun registro armado: el
    "si" del cliente caeria en el vacio.
    """
    def verificar(r: ResultadoTurno):
        if "para confirmar:" in r.respuesta.lower() and "confirmar" not in r.ruta:
            return f"imito la confirmacion del sistema sin armar el registro: {r.ruta}"
        return None
    return verificar


def todas(*verificaciones: Verificacion) -> Verificacion:
    # Reporta TODOS los motivos, no solo el primero: con cortocircuito, el tuteo
    # ocultó que en el mismo turno el modelo había inventado una duración.
    def verificar(r: ResultadoTurno):
        motivos = [motivo for v in verificaciones if (motivo := v(r)) is not None]
        return "; ".join(motivos) if motivos else None
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


def sin_cita(fecha: date, sufijo_telefono: str, *horas: str):
    """Verifica en la BASE que NO se agendó nada: para correcciones sin confirmar."""
    def verificar():
        conexion = conectar()
        try:
            filas = conexion.execute(
                f"""
                SELECT c.hora FROM citas c
                JOIN clientes cl ON cl.id = c.cliente_id
                WHERE c.fecha = ? AND c.hora IN ({",".join("?" * len(horas))})
                  AND c.estado = 'confirmada'
                  AND REPLACE(REPLACE(cl.telefono, ' ', ''), '-', '') LIKE ?
                """,
                (fecha.isoformat(), *horas, f"%{sufijo_telefono}"),
            ).fetchall()
        finally:
            conexion.close()
        if filas:
            return f"se agendó sin confirmación a las {[f['hora'] for f in filas]}"
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


# Se aplican a TODOS los turnos de todos los escenarios.
VERIFICACIONES_GLOBALES: tuple[Verificacion, ...] = (
    # El razonamiento interno de un modelo nunca debe llegar al TTS.
    no_menciona("<think>", "</think>"),
    # Nunca prometer una cita que no se creo.
    no_finge_agendar(),
    # Ni fingir la confirmacion del sistema.
    no_imita_confirmacion(),
    # Ningún precio fuera del catálogo, en ningún turno.
    precios_reales(),
)


def construir_escenarios() -> list[Escenario]:
    jueves = proximo(3)
    dia_cita = fecha_con_cupo("11:00")
    dia_correccion = fecha_con_cupo_en("11:00", "13:00")
    return [
        Escenario("Termino generico del negocio", [
            ("¿Cuánto cuesta el detallado?",
             todas(
                 llamo("listar_servicios"),
                 no_menciona("no lo manejamos"),
                 menciona("lavado", "encerado", "pulido", "interiores", "cerámico"),
             )),
        ]),
        Escenario("Precio directo", [
            ("¿Cuánto cuesta el encerado?",
             todas(llamo("consultar_precio"), menciona("1200", "1,200", "mil doscientos"),
                   duracion_correcta(120))),
        ]),
        Escenario("Catálogo: la pregunta que antes fallaba", [
            ("¿Qué servicios tienen?",
             todas(
                 llamo("listar_servicios"),
                 no_menciona("no lo manejamos"),
                 # Debe dar contenido útil: al menos un servicio por su nombre.
                 menciona("lavado", "encerado", "pulido", "interiores", "cerámico", "descontaminación"),
                 usa_usted(),
             )),
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
             todas(no_llamo("registrar_servicio"), usa_usted(), duracion_correcta(120))),
            # Con los cinco datos, el LLM propone registrar y el GRAFO pide la
            # confirmación con texto determinista que nombra a la clienta.
            ("Me llamo Ramona Pérez y mi teléfono es 55 1234 5678",
             todas(menciona("ramona"), termina_en("confirmar"))),
            # El "sí" se resuelve sin LLM. La verificación final en la base
            # exige UNA cita: ni cero ni duplicada.
            ("Sí, así está bien", termina_en("ejecutar_registro")),
        ], final=cita_unica(dia_cita, "11:00", "12345678", "Encerado")),
        Escenario("Corrección antes de confirmar", [
            (f"Quiero agendar un lavado premium para {en_palabras(dia_correccion)} a las once "
             "de la mañana, a nombre de Julián Torres, teléfono 55 8765 4321",
             termina_en("confirmar")),
            # Una corrección NO es un "sí": no debe agendar nada a las once, y el
            # LLM debe proponer el registro de nuevo con la hora corregida.
            ("No, mejor a la una de la tarde",
             todas(termina_en("confirmar"), menciona("una de la tarde"))),
        ], final=sin_cita(dia_correccion, "87654321", "11:00", "13:00")),
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
            for v in (verificar, *VERIFICACIONES_GLOBALES):
                if v is None:
                    continue
                verificaciones += 1
                if (motivo := v(r)) is not None:
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
