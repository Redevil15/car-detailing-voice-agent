"""Admisión dura: las 3 tools reales y 4 casos que exigen criterio.

La prueba anterior (1 tool, 2 frases) no distingue un modelo de 2.6B de uno
competente. Esta sí, porque revisa los ARGUMENTOS y no solo que haya tool_call:

  1. precio        -> consultar_precio con "encerado" en el argumento
  2. fecha natural -> checar_disponibilidad con la fecha ISO correcta
  3. saludo        -> ninguna tool
  4. faltan datos  -> NO debe llamar registrar_servicio (debe preguntar)

Las tools no se ejecutan: solo se inspecciona lo que el modelo PROPONE.

    uv run sandbox/11_admision_real.py
"""

import sys
import time
from datetime import date

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI

from core.settings import obtener_ajustes
from mcp_server.tools import checar_disponibilidad, consultar_precio, registrar_servicio

# Los modelos a evaluar se pueden pasar como argumentos; sin argumentos se usa
# la lista original de OpenRouter. Ejemplo con Ollama:
#   LLM_BASE_URL=http://127.0.0.1:11434/v1 LLM_API_KEY=ollama-local-sin-clave \
#     uv run sandbox/11_admision_real.py lfm2.5:8b qwen3.5:2b
CANDIDATOS = sys.argv[1:] or [
    "liquid/lfm-2.5-2.6b:free",
    "dots-studio/dots-3-note-preview:free",
    "nvidia/nemotron-3.5-lightning:free",
    "google/gemma-4-26b-a4b-it:free",
    "minimax/minimax-m2.7:free",
]

HOY = date.today()
SISTEMA = (
    f"Eres la recepcionista telefónica de un taller de car detailing. "
    f"Hoy es {HOY.isoformat()}. Usa las herramientas para cualquier dato de "
    f"precios o agenda; nunca los inventes. No agendes una cita sin tener "
    f"nombre, teléfono, servicio, fecha y hora confirmados por el cliente."
)

TOOLS = [
    StructuredTool.from_function(consultar_precio),
    StructuredTool.from_function(checar_disponibilidad),
    StructuredTool.from_function(registrar_servicio),
]

FECHA_ESPERADA = date(HOY.year, 9, 15).isoformat()


def _llamadas(respuesta) -> list[tuple[str, dict]]:
    return [(c["name"], c["args"]) for c in respuesta.tool_calls]


def caso_precio(r) -> bool:
    return any(n == "consultar_precio" and "encerado" in str(a).lower() for n, a in _llamadas(r))


def caso_fecha(r) -> bool:
    return any(n == "checar_disponibilidad" and a.get("fecha") == FECHA_ESPERADA for n, a in _llamadas(r))


def caso_saludo(r) -> bool:
    return not r.tool_calls


def caso_faltan_datos(r) -> bool:
    return not any(n == "registrar_servicio" for n, _ in _llamadas(r))


CASOS = [
    ("precio", "¿Cuánto me cobran por un encerado?", caso_precio),
    ("fecha", "¿Tienen lugar el 15 de septiembre?", caso_fecha),
    ("saludo", "Buenas tardes, ¿con quién hablo?", caso_saludo),
    ("faltan datos", "Quiero agendar un pulido completo", caso_faltan_datos),
]


def evaluar(modelo: str, key: str, base: str) -> tuple[int, float, list[str]]:
    llm = ChatOpenAI(
        model=modelo, api_key=key, base_url=base,
        temperature=0, timeout=60, max_retries=0,
    ).bind_tools(TOOLS)

    aciertos, tiempos, fallos = 0, [], []
    for nombre, frase, verificar in CASOS:
        inicio = time.perf_counter()
        respuesta = llm.invoke([SystemMessage(SISTEMA), HumanMessage(frase)])
        tiempos.append(time.perf_counter() - inicio)
        if verificar(respuesta):
            aciertos += 1
        else:
            fallos.append(f"{nombre}: {_llamadas(respuesta) or 'sin tool'}")
        time.sleep(1)
    return aciertos, sum(tiempos) / len(tiempos), fallos


def main() -> None:
    ajustes = obtener_ajustes()
    if not ajustes.llm_api_key:
        raise SystemExit("Falta LLM_API_KEY en .env")

    print(f"Fecha esperada en el caso 'fecha': {FECHA_ESPERADA}\n")
    print(f"{'modelo':<40} {'aciertos':>9} {'latencia media':>15}")
    print("-" * 66)

    detalle = []
    for modelo in CANDIDATOS:
        try:
            aciertos, media, fallos = evaluar(modelo, ajustes.llm_api_key, ajustes.llm_base_url)
            print(f"{modelo:<40} {aciertos:>7}/4 {media:>14.2f}s")
            detalle += [f"  {modelo} -> {f}" for f in fallos]
        except Exception as error:
            texto = str(error)
            motivo = "429 saturado" if "429" in texto else "404 sin endpoint" if "404" in texto else type(error).__name__
            print(f"{modelo:<40} {motivo:>25}")
        time.sleep(2)

    if detalle:
        print("\nFallos (qué propuso el modelo en cada caso fallido):")
        print("\n".join(detalle))


if __name__ == "__main__":
    main()
