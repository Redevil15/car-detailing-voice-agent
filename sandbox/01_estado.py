from typing import TypedDict
from langgraph.graph import StateGraph, START, END


class Estado(TypedDict):
    contador: int


def incrementar(estado: Estado) -> dict:
    print(f"  [nodo] recibí el estado completo: {estado}")
    return {"contador": estado["contador"] + 1}


builder = StateGraph(Estado)
builder.add_node("incrementar", incrementar)
builder.add_edge(START, "incrementar")
builder.add_edge("incrementar", END)
grafo = builder.compile()

resultado = grafo.invoke({"contador": 0})
print(f"resultado final: {resultado}")
