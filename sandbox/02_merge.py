from typing import TypedDict
from langgraph.graph import StateGraph, START, END


class Estado(TypedDict):
    cliente: str
    intencion: str


def detectar_intencion(estado: Estado) -> dict:
    # Solo devuelvo 'intencion'. No menciono 'cliente' para nada.
    return {"intencion": "consultar_precio"}


builder = StateGraph(Estado)
builder.add_node("detectar", detectar_intencion)
builder.add_edge(START, "detectar")
builder.add_edge("detectar", END)
grafo = builder.compile()

print(grafo.invoke({"cliente": "Ramona", "intencion": "desconocida"}))
