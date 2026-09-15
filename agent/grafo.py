"""Grafo del agente de voz.

    START -+- registro pendiente y el cliente aceptó -> ejecutar_registro -> END
           +- en otro caso -> agente -+- sin tool_calls -------------------------> END
                                      +- el LLM no respondió --------------------> manejar_error -> END
                                      +- tool_calls -> herramientas -+- datos / error de tool -> agente
                                                                     +- ambigüedad -----------> clarificar -> END
                                                                     +- registrar_servicio ---> confirmar -> END
                                                                     +- caída o 3 errores ----> manejar_error -> END

Dos decisiones salen del LLM y se vuelven rutas deterministas:
  - CLARIFICAR: ante ambigüedad, un modelo tiende a elegir la opción más probable
    en vez de preguntar, y cotizar el servicio equivocado no es aceptable.
  - CONFIRMAR: registrar_servicio es la única tool con efectos y no idempotente.
    El grafo la deja pendiente, lee los datos al cliente y solo la ejecuta tras
    un "sí". Pedírselo al modelo en el prompt lo dejó en bucle (qwen3.5:2b).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from agent.mcp_puente import descubrir_tools, ejecutar_tool
from core.settings import Ajustes

MAX_ERRORES_DE_TOOL = 2


class EstadoAgente(TypedDict):
    # Historial de la llamada: se ACUMULA entre turnos gracias al checkpointer.
    messages: Annotated[list[AnyMessage], add_messages]
    # Registro que el LLM propuso y espera el "sí" del cliente. Es el ÚNICO campo,
    # además del historial, que cruza turnos: por eso entrada_de_turno no lo toca.
    registro_pendiente: dict[str, Any] | None
    # Campos de UN SOLO turno. El checkpointer persiste todo el estado, así que
    # se reinician en cada entrada (ver entrada_de_turno); si no, la ambigüedad
    # del turno anterior contaminaría el siguiente.
    sugerencias: list[str]
    motivo_aclaracion: str | None  # 'ambiguo' o 'sin_coincidencia': lo declara la tool
    avisos_llm: list[str]  # errores del modelo principal cuando respondió el respaldo
    errores_de_tool: int
    fallo_grave: str | None


def entrada_de_turno(texto: str) -> dict[str, Any]:
    """Lo que entra al grafo cada vez que el cliente habla.

    No incluye registro_pendiente a propósito: debe sobrevivir hasta el turno
    en que el cliente confirma.
    """
    return {
        "messages": [HumanMessage(texto)],
        "sugerencias": [],
        "motivo_aclaracion": None,
        "avisos_llm": [],
        "errores_de_tool": 0,
        "fallo_grave": None,
    }


def _prompt_sistema() -> str:
    # La fecha se calcula en cada llamada, no al importar: un servidor que
    # arrancó ayer no debe creer que hoy sigue siendo ayer.
    return (
        "Eres la recepcionista telefónica de un taller de car detailing. "
        f"Hoy es {date.today().isoformat()}. "
        "Muchos clientes son personas mayores: trátalos siempre de usted, nunca de tú. "
        "Tus respuestas se leerán en voz alta: una o dos frases cortas, sin listas "
        "ni formato. Si hay muchos horarios libres, menciona solo dos o tres. "
        "Di los precios en pesos y con palabras que suenen bien habladas: nunca "
        "uses abreviaturas como MXN ni símbolos, porque un sintetizador de voz "
        "las lee letra por letra. "
        "Usa las herramientas para cualquier precio o disponibilidad y nunca "
        "inventes datos. Si preguntan qué servicios hay, menciona dos o tres por "
        "su nombre y precio, y ofrezca contar más. "
        "Para agendar necesitas nombre, teléfono, servicio, fecha y hora. Revisa "
        "toda la conversación y nunca vuelvas a pedir un dato que el cliente ya "
        "dio: pide solo lo que falte. Cuando tengas los cinco, llama a "
        "registrar_servicio sin pedir confirmación: el sistema se la pide al cliente."
    )


def _enumerar(opciones: list[str]) -> str:
    if len(opciones) == 1:
        return opciones[0]
    return ", ".join(opciones[:-1]) + " y " + opciones[-1]


# ------------------------------------------------- confirmación de registros

CAMPOS_REGISTRO = ("cliente", "telefono", "servicio", "fecha", "hora")
_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre")
_HORAS = ("doce", "una", "dos", "tres", "cuatro", "cinco", "seis",
          "siete", "ocho", "nueve", "diez", "once", "doce")
_AFIRMACIONES = {"si", "correcto", "exacto", "claro", "perfecto", "adelante", "ok",
                 "okay", "vale", "sale", "confirmo", "acuerdo", "bien", "asi"}
_RECHAZOS = {"no", "pero", "mejor", "cambie", "cambiar", "cambia", "otra", "otro",
             "espere", "corrija", "mal", "equivocado"}
_PENSAMIENTO = re.compile(r"<think>.*?</think>", re.S | re.I)


def fecha_hablada(iso: str) -> str:
    """'2026-09-15' -> 'el martes 15 de septiembre'. Si no es ISO, la deja igual."""
    try:
        dia = date.fromisoformat(str(iso))
    except ValueError:
        return str(iso)
    return f"el {_DIAS[dia.weekday()]} {dia.day} de {_MESES[dia.month - 1]}"


def hora_hablada(hhmm: str) -> str:
    """'13:00' -> 'la una de la tarde'. Un TTS lee '13:00' de formas raras."""
    try:
        horas, minutos = (int(parte) for parte in str(hhmm).split(":"))
    except ValueError:
        return str(hhmm)
    if not (0 <= horas < 24 and 0 <= minutos < 60):
        return str(hhmm)
    if horas == 0 or horas >= 20:
        periodo = "de la noche"
    elif horas < 12:
        periodo = "de la mañana"
    elif horas == 12:
        periodo = "del mediodía"
    else:
        periodo = "de la tarde"
    doce = horas % 12 or 12
    articulo = "la" if doce == 1 else "las"
    extra = f" y {minutos}" if minutos else ""
    return f"{articulo} {_HORAS[doce]}{extra} {periodo}"


def telefono_hablado(telefono: str) -> str:
    """'55 1234 5678' -> '55, 12, 34, 56, 78': en pares, como se dicta en México."""
    digitos = re.sub(r"\D", "", str(telefono))
    if len(digitos) == 10:
        return ", ".join(digitos[i:i + 2] for i in range(0, 10, 2))
    return " ".join(digitos) or str(telefono)


def es_afirmacion(texto: str) -> bool:
    """¿El cliente aceptó sin corregir nada?

    Ante la duda, NO: es preferible volver a preguntar que agendar algo que el
    cliente no aceptó. Una pregunta nunca cuenta como aceptación.
    """
    if "?" in texto:
        return False
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn"
    )
    palabras = set(re.findall(r"[a-z]+", sin_acentos))
    return bool(palabras & _AFIRMACIONES) and not palabras & _RECHAZOS


def limpiar_pensamiento(texto: str) -> str:
    """Quita el razonamiento que algunos modelos meten en el texto (<think>...).

    lfm2.5:8b ignora reasoning_effort y lo escribe en la respuesta, a veces en
    inglés. Nunca debe llegar al TTS.
    """
    limpio = _PENSAMIENTO.sub("", texto)
    cierre = limpio.lower().rfind("</think>")
    if cierre != -1:  # cierre sin apertura: se descarta todo lo anterior
        limpio = limpio[cierre + len("</think>"):]
    apertura = limpio.lower().find("<think>")
    if apertura != -1:  # apertura sin cierre: se descarta desde ahí
        limpio = limpio[:apertura]
    return limpio.strip()


# ---------------------------------------------------------------- enrutadores
# Funciones puras a nivel de módulo: se testean sin LLM, sin red y sin grafo.

def ruta_tras_agente(estado: EstadoAgente) -> Literal["herramientas", "manejar_error", "fin"]:
    if estado.get("fallo_grave"):
        return "manejar_error"
    ultimo = estado["messages"][-1]
    return "herramientas" if getattr(ultimo, "tool_calls", None) else "fin"


def ruta_inicio(estado: EstadoAgente) -> Literal["ejecutar_registro", "agente"]:
    """Si hay un registro esperando y el cliente acaba de aceptar, se agenda sin LLM."""
    if estado.get("registro_pendiente") and es_afirmacion(str(estado["messages"][-1].content)):
        return "ejecutar_registro"
    return "agente"


def ruta_tras_herramientas(
    estado: EstadoAgente,
) -> Literal["agente", "clarificar", "confirmar", "manejar_error"]:
    if estado.get("fallo_grave") or estado["errores_de_tool"] > MAX_ERRORES_DE_TOOL:
        return "manejar_error"
    if estado["sugerencias"]:
        return "clarificar"  # un servicio ambiguo se aclara antes de confirmar nada
    if estado.get("registro_pendiente"):
        return "confirmar"
    return "agente"


def ruta_tras_registro(estado: EstadoAgente) -> Literal["manejar_error", "fin"]:
    return "manejar_error" if estado.get("fallo_grave") else "fin"


# ------------------------------------------------------ nodos deterministas

def clarificar(estado: EstadoAgente) -> dict[str, Any]:
    opciones = estado["sugerencias"]
    # El motivo lo DECLARA la tool. Antes se deducía de la longitud de la lista,
    # y "¿qué servicios tienen?" acababa en "ese servicio no lo manejamos".
    if estado.get("motivo_aclaracion") == "sin_coincidencia":
        # Leer el catálogo completo por teléfono sería eterno: se ofrecen tres.
        texto = f"Ese servicio no lo manejamos. Tenemos, por ejemplo, {_enumerar(opciones[:3])}. ¿Le interesa alguno?"
    else:
        texto = f"Tenemos {_enumerar(opciones)}. ¿Cuál le interesa?"
    return {"messages": [AIMessage(texto)], "registro_pendiente": None}


def manejar_error(estado: EstadoAgente) -> dict[str, Any]:
    texto = (
        "Disculpe, en este momento tengo un problema técnico para consultar la "
        "agenda. ¿Podría llamarnos de nuevo en unos minutos?"
    )
    return {"messages": [AIMessage(texto)]}


def confirmar(estado: EstadoAgente) -> dict[str, Any]:
    """Lee los datos al cliente con texto determinista: el LLM no redacta esto."""
    datos = estado["registro_pendiente"]
    texto = (
        f"Para confirmar: {datos['servicio']} {fecha_hablada(datos['fecha'])} a "
        f"{hora_hablada(datos['hora'])}, a nombre de {datos['cliente']}, con teléfono "
        f"{telefono_hablado(datos['telefono'])}. ¿Es correcto?"
    )
    return {"messages": [AIMessage(texto)]}


async def invocar_con_respaldo(
    candidatos: list[tuple[str, Any]], mensajes: list
) -> tuple[AIMessage | None, list[str]]:
    """Prueba cada modelo en orden. Devuelve (respuesta, errores de los que fallaron).

    Sustituye a with_fallbacks, que relanza solo el PRIMER error y descarta los
    demás: con los dos modelos fallando, la mitad del diagnóstico se perdía.
    Vive a nivel de módulo para poder probarla con modelos falsos, sin red.
    """
    errores: list[str] = []
    for nombre, llm in candidatos:
        try:
            return await llm.ainvoke(mensajes), errores
        except Exception as error:
            errores.append(f"{nombre}: {type(error).__name__}: {str(error)[:300]}")
    return None, errores


# ---------------------------------------------------------------- ensamblado

async def construir_agente(ajustes: Ajustes, checkpointer=None):
    """Descubre las tools del servidor MCP y compila el grafo.

    Es async porque el descubrimiento habla con el servidor por red.
    """
    key, modelo, base = ajustes.exigir_llm()
    url = ajustes.mcp_server_url
    tools = await descubrir_tools(url)

    # reasoning_effort solo se envía si está configurado. Con 'none', qwen3.5:2b
    # bajó de 1.68 s a 0.65 s por turno sin perder aciertos. Otros proveedores
    # podrían rechazar el parámetro: vacío significa "no enviarlo".
    extra = {"reasoning_effort": ajustes.llm_reasoning_effort} if ajustes.llm_reasoning_effort else {}

    def _llm(nombre: str):
        return ChatOpenAI(
            model=nombre, api_key=key, base_url=base,
            temperature=0, timeout=30, max_retries=0, **extra,
        ).bind_tools(tools)

    # Principal y respaldo, en orden: ver invocar_con_respaldo.
    candidatos = [(modelo, _llm(modelo))]
    if ajustes.llm_model_respaldo:
        candidatos.append((ajustes.llm_model_respaldo, _llm(ajustes.llm_model_respaldo)))

    async def agente(estado: EstadoAgente) -> dict[str, Any]:
        respuesta, errores = await invocar_con_respaldo(
            candidatos, [SystemMessage(_prompt_sistema()), *estado["messages"]]
        )
        if respuesta is None:
            return {
                "fallo_grave": "ningún modelo respondió -> " + " | ".join(errores),
                "registro_pendiente": None,
            }
        # Algunos modelos (lfm2.5:8b) ignoran reasoning_effort y meten su
        # razonamiento en el texto. Nunca debe llegar al TTS.
        if isinstance(respuesta.content, str) and respuesta.content:
            limpio = limpiar_pensamiento(respuesta.content)
            if not limpio and not respuesta.tool_calls:
                limpio = "Disculpe, ¿me lo puede repetir?"
            if limpio != respuesta.content:
                respuesta = respuesta.model_copy(update={"content": limpio})
        # Un turno puede pasar dos veces por aquí (ciclo ReAct), así que se
        # acumula a mano: un reducer de suma impediría reiniciar la lista por turno.
        # Todo paso por el LLM descarta el registro pendiente: si el cliente no
        # aceptó, lo que dijo (una corrección, otra pregunta) lo interpreta el modelo.
        return {
            "messages": [respuesta],
            "avisos_llm": estado.get("avisos_llm", []) + errores,
            "registro_pendiente": None,
        }

    async def herramientas(estado: EstadoAgente) -> dict[str, Any]:
        ultimo = estado["messages"][-1]
        mensajes: list[ToolMessage] = []
        sugerencias: list[str] = []
        motivo_aclaracion: str | None = None
        errores = estado["errores_de_tool"]
        fallo = None
        pendiente: dict[str, Any] | None = None

        for llamada in ultimo.tool_calls:
            if llamada["name"] == "registrar_servicio":
                # NO se ejecuta aquí: queda pendiente hasta que el cliente acepte.
                faltan = [c for c in CAMPOS_REGISTRO if not str(llamada["args"].get(c) or "").strip()]
                estatus = "error"
                if faltan:
                    errores += 1
                    contenido = f"ERROR: faltan datos para agendar: {', '.join(faltan)}. Pídeselos al cliente."
                else:
                    # Se valida el servicio ANTES de confirmar: así el cliente escucha el
                    # nombre oficial, y un nombre mal escrito ("enchado", lo que propuso
                    # lfm2.5:8b) no llega a un "¿es correcto?" que después fallaría.
                    precio = await ejecutar_tool(url, "consultar_precio", {"servicio": llamada["args"]["servicio"]})
                    if precio.transporte:
                        fallo = precio.error
                        contenido = f"ERROR: {precio.error}"
                    elif not precio.ok:
                        errores += 1
                        contenido = f"ERROR: {precio.error}"
                    elif precio.datos.get("encontrado"):
                        pendiente = {**llamada["args"], "servicio": precio.datos["servicio"]}
                        contenido = "PENDIENTE: el sistema le pedirá confirmación al cliente antes de agendar."
                        estatus = "success"
                    else:
                        # Ambiguo o inexistente: se aclara con el cliente, no se confirma.
                        sugerencias = precio.datos.get("sugerencias", [])
                        motivo_aclaracion = precio.datos.get("motivo")
                        contenido = "ERROR: servicio no identificado; el sistema le pedirá al cliente que elija."
                mensajes.append(ToolMessage(
                    content=contenido,
                    tool_call_id=llamada.get("id") or llamada["name"],
                    status=estatus,
                ))
                continue
            resultado = await ejecutar_tool(url, llamada["name"], llamada["args"])
            # Cada tool_call DEBE recibir su ToolMessage, incluso si después se
            # desvía a clarificar o a error: un historial con llamadas sin
            # respuesta es rechazado por el proveedor en el turno siguiente.
            mensajes.append(ToolMessage(
                content=resultado.como_texto(),
                tool_call_id=llamada.get("id") or llamada["name"],
                status="success" if resultado.ok else "error",
            ))
            if resultado.transporte:
                fallo = resultado.error
            elif not resultado.ok:
                errores += 1
            elif llamada["name"] == "consultar_precio" and not resultado.datos.get("encontrado"):
                sugerencias = resultado.datos.get("sugerencias", [])
                motivo_aclaracion = resultado.datos.get("motivo")

        return {
            "messages": mensajes,
            "sugerencias": sugerencias,
            "motivo_aclaracion": motivo_aclaracion,
            "registro_pendiente": pendiente,
            "errores_de_tool": errores,
            "fallo_grave": fallo,
        }

    async def ejecutar_registro(estado: EstadoAgente) -> dict[str, Any]:
        datos = estado["registro_pendiente"]
        resultado = await ejecutar_tool(url, "registrar_servicio", datos)
        if resultado.transporte:
            return {"fallo_grave": resultado.error, "registro_pendiente": None}
        if resultado.ok and resultado.datos.get("exito"):
            texto = (
                f"Listo, su cita quedó agendada: {datos['servicio']} {fecha_hablada(datos['fecha'])} "
                f"a {hora_hablada(datos['hora'])}. Su folio es el {resultado.datos['cita_id']}."
            )
        elif resultado.ok:
            texto = f"No pude agendar la cita. {resultado.datos.get('mensaje', '')} ¿Le busco otra opción?"
        else:
            texto = "No pude agendar la cita con esos datos. ¿Me los repite, por favor?"
        return {"messages": [AIMessage(texto)], "registro_pendiente": None}

    grafo = StateGraph(EstadoAgente)
    grafo.add_node("agente", agente)
    grafo.add_node("herramientas", herramientas)
    grafo.add_node("clarificar", clarificar)
    grafo.add_node("manejar_error", manejar_error)
    grafo.add_node("confirmar", confirmar)
    grafo.add_node("ejecutar_registro", ejecutar_registro)

    grafo.add_conditional_edges(
        START, ruta_inicio,
        {"ejecutar_registro": "ejecutar_registro", "agente": "agente"},
    )
    grafo.add_conditional_edges(
        "agente", ruta_tras_agente,
        {"herramientas": "herramientas", "manejar_error": "manejar_error", "fin": END},
    )
    grafo.add_conditional_edges(
        "herramientas", ruta_tras_herramientas,
        {"agente": "agente", "clarificar": "clarificar", "confirmar": "confirmar",
         "manejar_error": "manejar_error"},
    )
    grafo.add_conditional_edges(
        "ejecutar_registro", ruta_tras_registro,
        {"manejar_error": "manejar_error", "fin": END},
    )
    grafo.add_edge("clarificar", END)
    grafo.add_edge("confirmar", END)
    grafo.add_edge("manejar_error", END)

    return grafo.compile(checkpointer=checkpointer or InMemorySaver())
