"""Prueba la rama manejar_error apagando el servidor MCP a mitad de la llamada.

El grafo se construye con el servidor ARRIBA (el descubrimiento de tools lo
necesita). Luego lo apagas tú, y se envía un turno que requiere una tool.

    uv run sandbox/14_fallo_servidor.py
"""

import asyncio

from agent.grafo import construir_agente, entrada_de_turno
from core.settings import obtener_ajustes


async def turno(grafo, hilo: str, frase: str) -> None:
    config = {"configurable": {"thread_id": hilo}}
    ruta: list[str] = []
    async for paso in grafo.astream(entrada_de_turno(frase), config, stream_mode="updates"):
        ruta.extend(paso.keys())
    estado = await grafo.aget_state(config)
    print(f"  ruta   : {' -> '.join(ruta)}")
    print(f"  AGENTE : {estado.values['messages'][-1].content}")
    herramientas = [m for m in estado.values["messages"] if m.type == "tool"]
    if herramientas:
        print(f"  la tool devolvió: {herramientas[-1].content[:110]}")


async def main() -> None:
    grafo = await construir_agente(obtener_ajustes())
    print("Grafo construido con el servidor MCP arriba.\n")

    await asyncio.to_thread(input, ">>> DETÉN el servidor MCP (Ctrl-C en su terminal) y presiona Enter aquí... ")
    print("\n--- Con el servidor caído ---")
    await turno(grafo, "llamada-caida", "¿Cuánto cuesta el encerado?")

    await asyncio.to_thread(input, "\n>>> VUELVE a levantar el servidor y presiona Enter aquí... ")
    print("\n--- Con el servidor recuperado ---")
    await turno(grafo, "llamada-recuperada", "¿Cuánto cuesta el encerado?")


if __name__ == "__main__":
    asyncio.run(main())
