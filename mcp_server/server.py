"""Servidor MCP que publica las herramientas del negocio sobre Streamable HTTP.

Este módulo es la capa de PROTOCOLO. La lógica vive en tools.py y no sabe
que MCP existe. Aquí solo se registra, se anota y se sirve.

    uv run mcp_server/server.py
"""

import os

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from mcp_server.tools import (
    checar_disponibilidad,
    consultar_precio,
    listar_servicios,
    registrar_servicio,
)

# Instrucciones a nivel de servidor: el modelo las lee al conectarse, antes
# de ver ninguna herramienta. Es el sitio para las reglas transversales.
INSTRUCCIONES = """Herramientas del taller de car detailing.

Reglas de uso:
- Las fechas van en formato AAAA-MM-DD y las horas en HH:MM de 24 horas. Si
  el cliente habla en relativo ("mañana", "el sábado"), conviértelo a fecha
  absoluta antes de llamar cualquier herramienta.
- Nunca inventes precios, horarios ni folios. Todos vienen de estas tools.
- Si consultar_precio devuelve encontrado=False con sugerencias, pregúntale
  al cliente cuál de esas opciones quiere. No elijas por él.
- Si el cliente pregunta qué servicios hay en general, usa listar_servicios.
- Confirma los cinco datos con el cliente antes de llamar registrar_servicio:
  esa herramienta crea una cita real en la agenda del taller.
"""

SOLO_LECTURA = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

ESCRITURA = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)


def construir_servidor() -> MCPServer:
    """Crea el servidor y registra las tres herramientas.

    El registro se hace llamando al decorador explícitamente en vez de
    ponerlo encima de cada función: así tools.py sigue sin importar MCP.
    """
    servidor = MCPServer(
        name="car-detailing",
        version="0.1.0",
        instructions=INSTRUCCIONES,
    )

    servidor.tool(annotations=SOLO_LECTURA)(consultar_precio)
    servidor.tool(annotations=SOLO_LECTURA)(listar_servicios)
    servidor.tool(annotations=SOLO_LECTURA)(checar_disponibilidad)
    servidor.tool(annotations=ESCRITURA)(registrar_servicio)

    return servidor


if __name__ == "__main__":
    construir_servidor().run(
        "streamable-http",
        # Por defecto solo loopback. En el contenedor de Fase 4 se pasará
        # MCP_HOST=0.0.0.0 explícitamente, como decisión consciente.
        host=os.getenv("MCP_HOST", "127.0.0.1"),
        port=int(os.getenv("MCP_PORT", "8000")),
        streamable_http_path="/mcp",
    )
