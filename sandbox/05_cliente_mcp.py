"""Prueba end-to-end del servidor MCP hablando Streamable HTTP de verdad.

Requiere el servidor corriendo:  uv run mcp_server/server.py

Este script es, en miniatura, lo que hará el agente de Fase 2.
"""

import asyncio
from datetime import date, timedelta

from mcp.client import Client

URL = "http://127.0.0.1:8000/mcp"


async def main() -> None:
    async with Client(URL) as cliente:
        resultado = await cliente.list_tools()

        print(f"El servidor publica {len(resultado.tools)} herramientas:\n")
        for herramienta in resultado.tools:
            primera_linea = herramienta.description.strip().splitlines()[0]
            parametros = list(herramienta.input_schema["properties"])
            solo_lectura = herramienta.annotations.read_only_hint
            print(f"  {herramienta.name}")
            print(f"     {primera_linea}")
            print(f"     parámetros : {parametros}")
            print(f"     solo lectura: {solo_lectura}\n")

        print("--- Llamadas reales por HTTP ---\n")

        r = await cliente.call_tool("consultar_precio", {"servicio": "ceramico"})
        print("consultar_precio('ceramico'):")
        print("  ", r.structured_content, "\n")

        manana = (date.today() + timedelta(days=1)).isoformat()
        r = await cliente.call_tool("checar_disponibilidad", {"fecha": manana})
        print(f"checar_disponibilidad('{manana}'):")
        print("  ", r.structured_content, "\n")

        r = await cliente.call_tool("consultar_precio", {"servicio": "lavado"})
        print("consultar_precio('lavado') — caso ambiguo:")
        print("  ", r.structured_content)


asyncio.run(main())
