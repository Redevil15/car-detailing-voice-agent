"""Prueba de admisión sobre varios modelos candidatos.

Los modelos :free comparten un pool entre todos los usuarios de OpenRouter y
devuelven 429 cuando está saturado. En vez de reintentar el mismo a ciegas,
probamos varios y elegimos con datos.

Cada modelo debe pasar dos pruebas:
  1. pedir la herramienta cuando hacen falta datos
  2. NO pedirla ante un saludo

Este script es el embrión del arnés de evaluación de Fase 5.

    uv run sandbox/10_admision.py
"""

import time

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from core.settings import obtener_ajustes

CANDIDATOS = [
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
    "minimax/minimax-m2.7:free",
    "nvidia/nemotron-3.5-lightning:free",
    "liquid/lfm-2.5-2.6b:free",
    "dots-studio/dots-3-note-preview:free",
]


@tool
def consultar_precio(servicio: str) -> str:
    """Consulta el precio de un servicio de car detailing."""
    return "esta herramienta no se ejecuta en la prueba"


def probar(modelo: str, key: str, base: str) -> tuple[str, float, float]:
    """Devuelve (veredicto, latencia_con_tool, latencia_sin_tool)."""
    llm = ChatOpenAI(
        model=modelo,
        api_key=key,
        base_url=base,
        temperature=0,
        timeout=45,
        # Sin reintentos internos: queremos medir la latencia real de UNA
        # llamada, no la de tres disfrazadas de una.
        max_retries=0,
    )
    con_tools = llm.bind_tools([consultar_precio])

    inicio = time.perf_counter()
    r1 = con_tools.invoke("¿Cuánto cuesta el encerado?")
    t1 = time.perf_counter() - inicio

    inicio = time.perf_counter()
    r2 = con_tools.invoke("Buenos días, ¿cómo están?")
    t2 = time.perf_counter() - inicio

    if r1.tool_calls and not r2.tool_calls:
        return "APTO", t1, t2
    if not r1.tool_calls:
        return "no pide tool", t1, t2
    return "pide tool de mas", t1, t2


def main() -> None:
    ajustes = obtener_ajustes()
    key, _, base = ajustes.llm_api_key, ajustes.llm_model, ajustes.llm_base_url
    if not key:
        raise SystemExit("Falta LLM_API_KEY en .env")

    print(f"{'modelo':<40} {'veredicto':<18} {'t1':>7} {'t2':>7}")
    print("-" * 76)

    for modelo in CANDIDATOS:
        try:
            veredicto, t1, t2 = probar(modelo, key, base)
            print(f"{modelo:<40} {veredicto:<18} {t1:>6.2f}s {t2:>6.2f}s")
        except Exception as error:
            nombre = type(error).__name__
            detalle = str(error).replace("\n", " ")
            if "429" in detalle:
                motivo = "429 pool saturado"
            elif "404" in detalle:
                motivo = "404 sin endpoint"
            elif "401" in detalle or "403" in detalle:
                motivo = "sin permiso"
            else:
                motivo = nombre
            print(f"{modelo:<40} {motivo:<18} {'-':>7} {'-':>7}")

        # Respirar entre modelos: el tier gratuito también limita por cuenta.
        time.sleep(1.5)


if __name__ == "__main__":
    main()
