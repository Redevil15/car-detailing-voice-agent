"""Un ciclo en el grafo, y el límite que impide que sea infinito."""

from typing import TypedDict

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph


class Estado(TypedDict):
    intentos: int
    limite: int


def trabajar(estado: Estado) -> dict:
    print(f"    ejecutando, intento {estado['intentos'] + 1}")
    return {"intentos": estado["intentos"] + 1}


def seguir_o_terminar(estado: Estado) -> str:
    return "seguir" if estado["intentos"] < estado["limite"] else "terminar"


builder = StateGraph(Estado)
builder.add_node("trabajar", trabajar)
builder.add_edge(START, "trabajar")

# La ruta "seguir" apunta al PROPIO nodo: eso es un ciclo.
builder.add_conditional_edges(
    "trabajar",
    seguir_o_terminar,
    {"seguir": "trabajar", "terminar": END},
)

grafo = builder.compile()

print("Caso 1 — ciclo con condición de salida (3 vueltas):")
print("  resultado:", grafo.invoke({"intentos": 0, "limite": 3}), "\n")

print("Caso 2 — ciclo sin salida, contenido por recursion_limit=5:")
try:
    grafo.invoke({"intentos": 0, "limite": 999}, {"recursion_limit": 5})
except GraphRecursionError as error:
    print("  cortado por GraphRecursionError:")
    print("  ", str(error).splitlines()[0])
