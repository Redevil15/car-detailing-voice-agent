"""Reproduce en texto la conversación de voz que terminó en manejar_error.

Mismas frases que transcribió Whisper y en el mismo hilo, para ver el error
completo que antes se perdía. El nombre y el teléfono son inventados.

Requiere el servidor MCP en el puerto 8000, reiniciado para que publique
listar_servicios.

    uv run sandbox/17_replay_fallo.py
"""

import asyncio

from agent.grafo import construir_agente, entrada_de_turno
from core.settings import obtener_ajustes

TURNOS = [
    "¿Qué servicios tiene?",
    "Quiero un cambio de aceite.",
    "Si vamos con el lavado premium",
    "ok bueno mi nombre es Ramona Pérez mi teléfono es 55 1234 5678 y me gustaría "
    "lavado el lunes en la mañana no sé de 8 de la mañana a una PM",
]


def resumir_historial(mensajes) -> None:
    """Forma del historial, sin contenido: lo que importa para un 400."""
    print("   historial de la llamada:")
    for numero, mensaje in enumerate(mensajes):
        detalle = ""
        llamadas = getattr(mensaje, "tool_calls", None) or []
        if llamadas:
            detalle = f" tool_calls={[c.get('id') for c in llamadas]}"
        if mensaje.type == "tool":
            detalle = f" tool_call_id={mensaje.tool_call_id} status={getattr(mensaje, 'status', None)}"
        print(f"     {numero:>2}. {mensaje.type:<6} {len(str(mensaje.content)):>4} caracteres{detalle}")


async def main() -> None:
    grafo = await construir_agente(obtener_ajustes())
    config = {"configurable": {"thread_id": "replay-fallo"}}

    for frase in TURNOS:
        ruta: list[str] = []
        async for paso in grafo.astream(entrada_de_turno(frase), config, stream_mode="updates"):
            ruta.extend(paso.keys())
        estado = (await grafo.aget_state(config)).values

        print(f"\nCLIENTE: {frase}")
        print(f"   ruta   : {' -> '.join(ruta)}")
        print(f"   AGENTE : {estado['messages'][-1].content}")
        for aviso in estado.get("avisos_llm") or []:
            print(f"   aviso LLM: {aviso}")
        if estado.get("fallo_grave"):
            print(f"   FALLO  : {estado['fallo_grave']}")
            resumir_historial(estado["messages"])
        await asyncio.sleep(1.5)


if __name__ == "__main__":
    asyncio.run(main())
