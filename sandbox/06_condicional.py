"""El enrutador decide a qué nodo ir. Todavía sin LLM."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class Estado(TypedDict):
    transcripcion: str
    intencion: str
    respuesta: str


def clasificar(estado: Estado) -> dict:
    texto = estado["transcripcion"].lower()
    if "cuesta" in texto or "precio" in texto:
        return {"intencion": "precio"}
    if "disponible" in texto or "espacio" in texto:
        return {"intencion": "disponibilidad"}
    return {"intencion": "desconocida"}


def enrutar(estado: Estado) -> str:
    """Función PURA: estado -> nombre de ruta.

    No modifica nada y no es un nodo. Se puede testear sola, sin grafo.
    """
    return estado["intencion"]


def responder_precio(estado: Estado) -> dict:
    return {"respuesta": "Con gusto le consulto el precio."}


def responder_disponibilidad(estado: Estado) -> dict:
    return {"respuesta": "Déjeme revisar la agenda."}


def clarificar(estado: Estado) -> dict:
    return {"respuesta": "Disculpe, ¿me lo puede repetir?"}


builder = StateGraph(Estado)
builder.add_node("clasificar", clasificar)
builder.add_node("nodo_precio", responder_precio)
builder.add_node("nodo_disponibilidad", responder_disponibilidad)
builder.add_node("nodo_clarificar", clarificar)

builder.add_edge(START, "clasificar")

# El tercer argumento mapea NOMBRE DE RUTA -> NOMBRE DE NODO. Son cosas
# distintas a propósito: el enrutador habla el lenguaje del dominio
# ("precio"), no el de la topología ("nodo_precio").
builder.add_conditional_edges(
    "clasificar",
    enrutar,
    {
        "precio": "nodo_precio",
        "disponibilidad": "nodo_disponibilidad",
        "desconocida": "nodo_clarificar",
    },
)

for nodo in ("nodo_precio", "nodo_disponibilidad", "nodo_clarificar"):
    builder.add_edge(nodo, END)

grafo = builder.compile()

for frase in [
    "¿Cuánto cuesta el encerado?",
    "¿Tienen espacio el jueves?",
    "Oiga, ¿ustedes lavan motos?",
]:
    resultado = grafo.invoke({"transcripcion": frase, "intencion": "", "respuesta": ""})
    print(f"{frase!r}\n   -> ruta={resultado['intencion']:<15} {resultado['respuesta']}\n")

print("El enrutador se testea sin grafo:")
print("  ", enrutar({"transcripcion": "", "intencion": "precio", "respuesta": ""}))

print("\nTopología resultante:\n")
print(grafo.get_graph().draw_mermaid())
