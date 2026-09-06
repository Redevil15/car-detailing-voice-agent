"""Hello world de LangGraph — Fase 0.

Grafo de 2 nodos que modela el esqueleto del agente real:

    START -> interpretar -> responder -> END

Deliberadamente SIN LLM y SIN MCP. En Fase 0 validamos la mecánica del
grafo; en Fase 2 el cuerpo de `interpretar` pasa a ser una llamada al LLM
y el de `responder` pasa a llamar tools vía MCP. El contrato de cada nodo
(qué recibe y qué devuelve) no cambia — solo su implementación.
"""

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph


class EstadoConversacion(TypedDict):
    """Todo lo que fluye por el sistema durante una llamada."""

    transcripcion: str  # lo que dijo el cliente (vendrá del STT en Fase 3)
    intencion: str  # lo que detecta el nodo `interpretar`
    respuesta: str  # lo que dirá el agente (irá al TTS en Fase 3)
    historial: Annotated[list[str], operator.add]  # acumula, no sobreescribe


# Las 3 intenciones son exactamente las 3 tools del negocio (Fase 1).
PALABRAS_CLAVE: dict[str, tuple[str, ...]] = {
    "consultar_precio": ("precio", "cuesta", "cuánto", "cuanto", "tarifa"),
    "checar_disponibilidad": ("disponible", "disponibilidad", "hueco", "espacio"),
    "registrar_servicio": ("agendar", "apartar", "reservar", "quiero mi cita"),
}

RESPUESTAS: dict[str, str] = {
    "consultar_precio": "Con gusto le consulto el precio de ese servicio.",
    "checar_disponibilidad": "Déjeme revisar qué fechas tenemos disponibles.",
    "registrar_servicio": "Perfecto, procedo a agendarle el servicio.",
    "desconocida": "Disculpe, no le entendí bien. ¿Me lo puede repetir?",
}


def interpretar(estado: EstadoConversacion) -> dict:
    """Clasifica la intención del cliente. En Fase 2 esto será un LLM."""
    texto = estado["transcripcion"].lower()
    intencion = "desconocida"
    for nombre, palabras in PALABRAS_CLAVE.items():
        if any(palabra in texto for palabra in palabras):
            intencion = nombre
            break
    return {
        "intencion": intencion,
        "historial": [f"cliente: {estado['transcripcion']}"],
    }


def responder(estado: EstadoConversacion) -> dict:
    """Genera la respuesta. En Fase 2 esto llamará tools vía MCP."""
    respuesta = RESPUESTAS[estado["intencion"]]
    return {
        "respuesta": respuesta,
        "historial": [f"agente: {respuesta}"],
    }


def construir_grafo():
    """Devuelve el grafo compilado. Función, no variable de módulo: así se
    puede instanciar en tests sin efectos secundarios al importar."""
    builder = StateGraph(EstadoConversacion)
    builder.add_node("interpretar", interpretar)
    builder.add_node("responder", responder)
    builder.add_edge(START, "interpretar")
    builder.add_edge("interpretar", "responder")
    builder.add_edge("responder", END)
    return builder.compile()


def _estado_inicial(transcripcion: str) -> EstadoConversacion:
    return {
        "transcripcion": transcripcion,
        "intencion": "",
        "respuesta": "",
        "historial": [],
    }


if __name__ == "__main__":
    grafo = construir_grafo()

    frases = [
        "¿Cuánto cuesta el pulido completo?",
        "¿Tienen espacio el sábado?",
        "Quiero apartar una cita para el viernes",
        "Oiga, ¿ustedes venden llantas?",
    ]

    for frase in frases:
        resultado = grafo.invoke(_estado_inicial(frase))
        print(f"\n  cliente   : {frase}")
        print(f"  intención : {resultado['intencion']}")
        print(f"  agente    : {resultado['respuesta']}")
