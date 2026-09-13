"""Lista los modelos del proveedor configurado y verifica tool calling.

Antes de construir el agente hay que confirmar dos cosas del modelo:
  1. que emite tool_calls cuando hacen falta datos
  2. que NO los emite cuando no hacen falta

Un endpoint "compatible con OpenAI" puede fallar cualquiera de las dos.

    uv run sandbox/09_llm.py
"""

import time

import httpx
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from core.settings import obtener_ajustes

ajustes = obtener_ajustes()
print(f"Proveedor: {ajustes.llm_base_url}")
print(f"Modelo   : {ajustes.llm_model or '(sin definir)'}\n")

respuesta = httpx.get(
    f"{ajustes.llm_base_url.rstrip('/')}/models",
    headers={"Authorization": f"Bearer {ajustes.llm_api_key}"},
    timeout=30,
)
if respuesta.status_code == 200:
    datos = respuesta.json().get("data", [])
    print(f"El proveedor ofrece {len(datos)} modelos.")
else:
    print(f"No se pudo listar: HTTP {respuesta.status_code} — {respuesta.text[:200]}")

if not ajustes.llm_model:
    raise SystemExit("Define LLM_MODEL en .env y repite.")

key, modelo, base = ajustes.exigir_llm()
llm = ChatOpenAI(model=modelo, api_key=key, base_url=base, temperature=0)


@tool
def consultar_precio(servicio: str) -> str:
    """Consulta el precio de un servicio de car detailing."""
    return "esta herramienta no se ejecuta en la prueba"


con_tools = llm.bind_tools([consultar_precio])

print("\n--- Prueba 1: debe pedir la herramienta ---")
inicio = time.perf_counter()
r1 = con_tools.invoke("¿Cuánto cuesta el encerado?")
print(f"  latencia   : {time.perf_counter() - inicio:.2f} s")
print(f"  tool_calls : {r1.tool_calls}")
print(f"  texto      : {str(r1.content)[:120]!r}")

print("\n--- Prueba 2: NO debe pedir herramienta ---")
inicio = time.perf_counter()
r2 = con_tools.invoke("Buenos días, ¿cómo están?")
print(f"  latencia   : {time.perf_counter() - inicio:.2f} s")
print(f"  tool_calls : {r2.tool_calls}")
print(f"  texto      : {str(r2.content)[:120]!r}")

print("\n--- Veredicto ---")
if r1.tool_calls and not r2.tool_calls:
    print("  Modelo apto: distingue cuándo necesita datos y cuándo no.")
elif not r1.tool_calls:
    print("  NO apto: no pidió la herramienta; inventaría precios.")
else:
    print("  Dudoso: pide herramientas hasta para saludar. Cuesta latencia y dinero.")
