"""Un turno completo con tool calling, escrito a mano y sin grafo.

Son literalmente los 5 pasos de la teoría:
  1. mandar mensajes + esquemas de las tools
  2. el modelo PROPONE tool_calls (no ejecuta nada)
  3. NOSOTROS ejecutamos cada una vía MCP
  4. devolvemos cada resultado como ToolMessage
  5. el modelo redacta la respuesta final con los datos reales

Requiere el servidor MCP corriendo en el puerto 8000.

    uv run sandbox/12_un_turno.py
"""

import asyncio
import time
from datetime import date

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from agent.mcp_puente import descubrir_tools, ejecutar_tool
from core.settings import obtener_ajustes

SISTEMA = (
    "Eres la recepcionista telefónica de un taller de car detailing. "
    f"Hoy es {date.today().isoformat()}. Responde en una o dos frases cortas, "
    "porque se leerán en voz alta. Usa las herramientas para cualquier precio "
    "o disponibilidad; nunca inventes datos."
)


async def un_turno(llm, url: str, frase: str) -> None:
    print(f"\n{'=' * 70}\nCLIENTE: {frase}")
    mensajes = [SystemMessage(SISTEMA), HumanMessage(frase)]

    # Pasos 1 y 2
    inicio = time.perf_counter()
    propuesta = await llm.ainvoke(mensajes)
    t_llm1 = time.perf_counter() - inicio

    if not propuesta.tool_calls:
        print(f"  [sin tools] AGENTE: {propuesta.content}")
        print(f"  tiempos: LLM {t_llm1:.2f}s")
        return

    mensajes.append(propuesta)

    # Pasos 3 y 4
    t_mcp = 0.0
    for llamada in propuesta.tool_calls:
        print(f"  el LLM propone: {llamada['name']}({llamada['args']})")
        inicio = time.perf_counter()
        resultado = await ejecutar_tool(url, llamada["name"], llamada["args"])
        t_mcp += time.perf_counter() - inicio
        print(f"  MCP devuelve  : {resultado.como_texto()[:160]}")
        mensajes.append(
            ToolMessage(
                content=resultado.como_texto(),
                tool_call_id=llamada.get("id") or llamada["name"],
                status="success" if resultado.ok else "error",
            )
        )

    # Paso 5
    inicio = time.perf_counter()
    final = await llm.ainvoke(mensajes)
    t_llm2 = time.perf_counter() - inicio

    print(f"  AGENTE: {final.content}")
    print(f"  tiempos: LLM {t_llm1:.2f}s + MCP {t_mcp * 1000:.0f}ms + LLM {t_llm2:.2f}s"
          f" = {t_llm1 + t_mcp + t_llm2:.2f}s")


async def main() -> None:
    ajustes = obtener_ajustes()
    key, modelo, base = ajustes.exigir_llm()

    tools = await descubrir_tools(ajustes.mcp_server_url)
    nombres = [t["function"]["name"] for t in tools]
    print(f"Descubiertas en {ajustes.mcp_server_url}: {nombres}")
    print(f"Modelo: {modelo}")

    llm = ChatOpenAI(
        model=modelo, api_key=key, base_url=base, temperature=0, timeout=60
    ).bind_tools(tools)

    for frase in [
        "¿Cuánto cuesta el encerado?",
        "¿Tienen lugar el 15 de septiembre?",
        "¿Cuánto sale el lavado?",
    ]:
        await un_turno(llm, ajustes.mcp_server_url, frase)
        await asyncio.sleep(1.5)


if __name__ == "__main__":
    asyncio.run(main())
