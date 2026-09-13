"""Conversaciones de varios turnos contra el grafo real.

Cada conversación es una llamada telefónica distinta (thread_id propio).
Se imprime la RUTA que tomó el grafo en cada turno, no solo la respuesta.

Requiere el servidor MCP corriendo en el puerto 8000.

    uv run sandbox/13_conversacion.py
"""

import asyncio
import time
from pathlib import Path

from agent.grafo import construir_agente, entrada_de_turno
from core.settings import obtener_ajustes

CONVERSACIONES = [
    ("Precio directo", ["¿Cuánto cuesta el encerado?"]),
    ("Ambigüedad resuelta con memoria", ["¿Cuánto sale el lavado?", "El premium, por favor"]),
    ("Servicio que no existe", ["¿Hacen cambio de aceite?"]),
]


async def main() -> None:
    grafo = await construir_agente(obtener_ajustes())

    for numero, (titulo, turnos) in enumerate(CONVERSACIONES, start=1):
        config = {"configurable": {"thread_id": f"llamada-{numero}"}}
        print(f"\n{'=' * 72}\n{titulo}")

        for frase in turnos:
            inicio = time.perf_counter()
            ruta: list[str] = []
            async for paso in grafo.astream(entrada_de_turno(frase), config, stream_mode="updates"):
                ruta.extend(paso.keys())

            estado = await grafo.aget_state(config)
            respuesta = estado.values["messages"][-1].content
            print(f"\n  CLIENTE: {frase}")
            print(f"  ruta   : {' -> '.join(ruta)}")
            print(f"  AGENTE : {respuesta}")
            print(f"  ({time.perf_counter() - inicio:.2f}s, {len(estado.values['messages'])} mensajes en memoria)")
            await asyncio.sleep(1.5)

    Path("docs/agente.mmd").write_text(grafo.get_graph().draw_mermaid(), encoding="utf-8")
    print("\nDiagrama del grafo guardado en docs/agente.mmd")


if __name__ == "__main__":
    asyncio.run(main())
