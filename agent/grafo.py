"""Grafo del agente de voz — Fase 2.

    START -> agente --+-- sin tool_calls ---------------------------> END
                      +-- el LLM no respondió -----------------------> manejar_error -> END
                      +-- tool_calls -> herramientas --+-- datos / error de tool -> agente
                                                       +-- ambigüedad -----------> clarificar -> END
                                                       +-- caída o 3 errores ----> manejar_error -> END

La clarificación es una RUTA DETERMINISTA, no una decisión del LLM: ante
ambigüedad un modelo tiende a elegir la opción más probable en vez de
preguntar, y cotizarle al cliente el servicio equivocado no es aceptable.
"""

from __future__ import annotations

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
    # Campos de UN SOLO turno. El checkpointer persiste todo el estado, así que
    # se reinician en cada entrada (ver entrada_de_turno); si no, la ambigüedad
    # del turno anterior contaminaría el siguiente.
    sugerencias: list[str]
    errores_de_tool: int
    fallo_grave: str | None


def entrada_de_turno(texto: str) -> dict[str, Any]:
    """Lo que entra al grafo cada vez que el cliente habla."""
    return {
        "messages": [HumanMessage(texto)],
        "sugerencias": [],
        "errores_de_tool": 0,
        "fallo_grave": None,
    }


def _prompt_sistema() -> str:
    # La fecha se calcula en cada llamada, no al importar: un servidor que
    # arrancó ayer no debe creer que hoy sigue siendo ayer.
    return (
        "Eres la recepcionista telefónica de un taller de car detailing. "
        f"Hoy es {date.today().isoformat()}. "
        "Tus respuestas se leerán en voz alta: una o dos frases cortas, sin listas "
        "ni formato. Si hay muchos horarios libres, menciona solo dos o tres. "
        "Di los precios en pesos y con palabras que suenen bien habladas: nunca "
        "uses abreviaturas como MXN ni símbolos, porque un sintetizador de voz "
        "las lee letra por letra. "
        "Usa las herramientas para cualquier precio o disponibilidad y nunca "
        "inventes datos. Para agendar necesitas nombre, teléfono, servicio, fecha "
        "y hora: pide lo que falte antes de llamar a registrar_servicio."
    )


def _enumerar(opciones: list[str]) -> str:
    if len(opciones) == 1:
        return opciones[0]
    return ", ".join(opciones[:-1]) + " y " + opciones[-1]


# ---------------------------------------------------------------- enrutadores
# Funciones puras a nivel de módulo: se testean sin LLM, sin red y sin grafo.

def ruta_tras_agente(estado: EstadoAgente) -> Literal["herramientas", "manejar_error", "fin"]:
    if estado.get("fallo_grave"):
        return "manejar_error"
    ultimo = estado["messages"][-1]
    return "herramientas" if getattr(ultimo, "tool_calls", None) else "fin"


def ruta_tras_herramientas(estado: EstadoAgente) -> Literal["agente", "clarificar", "manejar_error"]:
    if estado.get("fallo_grave") or estado["errores_de_tool"] > MAX_ERRORES_DE_TOOL:
        return "manejar_error"
    if estado["sugerencias"]:
        return "clarificar"
    return "agente"


# ------------------------------------------------------ nodos deterministas

def clarificar(estado: EstadoAgente) -> dict[str, Any]:
    opciones = estado["sugerencias"]
    if len(opciones) <= 3:
        texto = f"Tenemos {_enumerar(opciones)}. ¿Cuál le interesa?"
    else:
        # Muchos candidatos significa que no hubo coincidencia: leer el catálogo
        # completo por teléfono sería eterno, así que se ofrecen tres.
        texto = f"Ese servicio no lo manejamos. Tenemos, por ejemplo, {_enumerar(opciones[:3])}. ¿Le interesa alguno?"
    return {"messages": [AIMessage(texto)]}


def manejar_error(estado: EstadoAgente) -> dict[str, Any]:
    texto = (
        "Disculpe, en este momento tengo un problema técnico para consultar la "
        "agenda. ¿Podría llamarnos de nuevo en unos minutos?"
    )
    return {"messages": [AIMessage(texto)]}


# ---------------------------------------------------------------- ensamblado

async def construir_agente(ajustes: Ajustes, checkpointer=None):
    """Descubre las tools del servidor MCP y compila el grafo.

    Es async porque el descubrimiento habla con el servidor por red.
    """
    key, modelo, base = ajustes.exigir_llm()
    url = ajustes.mcp_server_url
    tools = await descubrir_tools(url)

    def _llm(nombre: str):
        return ChatOpenAI(
            model=nombre, api_key=key, base_url=base,
            temperature=0, timeout=30, max_retries=0,
        ).bind_tools(tools)

    llm = _llm(modelo)
    if ajustes.llm_model_respaldo:
        # Si el principal falla (429 del pool gratuito, timeout), se reintenta
        # la MISMA petición con el respaldo, sin código de reintento a mano.
        llm = llm.with_fallbacks([_llm(ajustes.llm_model_respaldo)])

    async def agente(estado: EstadoAgente) -> dict[str, Any]:
        try:
            respuesta = await llm.ainvoke([SystemMessage(_prompt_sistema()), *estado["messages"]])
        except Exception as error:
            return {"fallo_grave": f"LLM no disponible: {type(error).__name__}"}
        return {"messages": [respuesta]}

    async def herramientas(estado: EstadoAgente) -> dict[str, Any]:
        ultimo = estado["messages"][-1]
        mensajes: list[ToolMessage] = []
        sugerencias: list[str] = []
        errores = estado["errores_de_tool"]
        fallo = None

        for llamada in ultimo.tool_calls:
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

        return {
            "messages": mensajes,
            "sugerencias": sugerencias,
            "errores_de_tool": errores,
            "fallo_grave": fallo,
        }

    grafo = StateGraph(EstadoAgente)
    grafo.add_node("agente", agente)
    grafo.add_node("herramientas", herramientas)
    grafo.add_node("clarificar", clarificar)
    grafo.add_node("manejar_error", manejar_error)

    grafo.add_edge(START, "agente")
    grafo.add_conditional_edges(
        "agente", ruta_tras_agente,
        {"herramientas": "herramientas", "manejar_error": "manejar_error", "fin": END},
    )
    grafo.add_conditional_edges(
        "herramientas", ruta_tras_herramientas,
        {"agente": "agente", "clarificar": "clarificar", "manejar_error": "manejar_error"},
    )
    grafo.add_edge("clarificar", END)
    grafo.add_edge("manejar_error", END)

    return grafo.compile(checkpointer=checkpointer or InMemorySaver())
