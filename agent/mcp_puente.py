"""Puente entre el servidor MCP y el LLM.

langchain-mcp-adapters exige mcp<2, incompatible con el SDK 2.x del proyecto
(ADR-005), así que el puente es propio. Hace dos cosas y nada más:

  1. descubrir: tools/list del servidor  -> esquemas en el formato del LLM
  2. ejecutar:  una tool_call del LLM    -> tools/call en el servidor

Este módulo NO importa mcp_server. El agente solo conoce al servidor por su
URL y por lo que el protocolo le describe (ADR-004).
"""

import json
from dataclasses import dataclass
from typing import Any

from mcp.client import Client


@dataclass(frozen=True)
class ResultadoTool:
    """Resultado normalizado de ejecutar una tool, haya salido bien o mal."""

    nombre: str
    ok: bool
    datos: dict[str, Any] | None
    error: str | None
    transporte: bool = False  # True si falló la red o el servidor, no la tool

    def como_texto(self) -> str:
        """Lo que se le devuelve al LLM dentro del ToolMessage."""
        if self.ok:
            return json.dumps(self.datos, ensure_ascii=False)
        return f"ERROR: {self.error}"


async def descubrir_tools(url: str) -> list[dict[str, Any]]:
    """Pregunta al servidor qué tools ofrece y las traduce al formato OpenAI.

    El input_schema de MCP ya es JSON Schema, así que la traducción es solo
    envolverlo. Con 3 tools no hace falta paginar (next_cursor).
    """
    async with Client(url) as cliente:
        resultado = await cliente.list_tools()

    return [
        {
            "type": "function",
            "function": {
                "name": herramienta.name,
                "description": (herramienta.description or "").strip(),
                "parameters": herramienta.input_schema,
            },
        }
        for herramienta in resultado.tools
    ]


async def ejecutar_tool(url: str, nombre: str, argumentos: dict[str, Any]) -> ResultadoTool:
    """Ejecuta una tool y NUNCA lanza excepción: todo fallo vuelve como dato.

    Hay dos familias de fallo y conviene distinguirlas:
      - de transporte: servidor caído, timeout, red. Llegan como excepción.
      - de la tool:    argumentos inválidos, tool inexistente. Llegan como
                       is_error=True en una respuesta HTTP perfectamente normal.

    Una conexión por llamada: medido en 11-14 ms frente a ~1200 ms del LLM,
    no justifica la complejidad de mantener una sesión viva.
    """
    try:
        async with Client(url) as cliente:
            respuesta = await cliente.call_tool(nombre, argumentos)
    except Exception as error:
        return ResultadoTool(
            nombre, False, None, f"servidor MCP inalcanzable: {error}", transporte=True
        )

    if respuesta.is_error:
        detalle = respuesta.content[0].text if respuesta.content else "error sin detalle"
        return ResultadoTool(nombre, False, None, detalle)

    return ResultadoTool(nombre, True, respuesta.structured_content, None)
