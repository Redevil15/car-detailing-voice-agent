import operator
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END


class Estado(TypedDict):
    # sin reducer: se sobreescribe
    turno_actual: str
    # con reducer: la lista devuelta se CONCATENA a la existente
    historial: Annotated[list[str], operator.add]


def cliente_habla(estado: Estado) -> dict:
    return {"turno_actual": "cliente", "historial": ["¿cuánto cuesta el pulido?"]}


def agente_responde(estado: Estado) -> dict:
    return {"turno_actual": "agente", "historial": ["El pulido cuesta 1200 pesos."]}


builder = StateGraph(Estado)
builder.add_node("cliente", cliente_habla)
builder.add_node("agente", agente_responde)
builder.add_edge(START, "cliente")
builder.add_edge("cliente", "agente")
builder.add_edge("agente", END)
grafo = builder.compile()

for paso in grafo.stream({"turno_actual": "", "historial": []}):
    print(paso)
