"""Capa HTTP del sistema: salud, preparacion y pagina de estado.

Por que un servicio aparte y no dos rutas mas dentro del servidor MCP:

  1. Seguridad. Las tools de MCP CREAN CITAS y no autentican a nadie. Ese
     proceso no puede salir a internet. Esta API si va a salir (tunel de
     Cloudflare) y por eso no reexpone ninguna tool: solo informa.
  2. Operacion. Un orquestador necesita HTTP corriente para responder dos
     preguntas distintas: si el contenedor VIVE y si esta LISTO.

Este modulo habla con MCP por el protocolo, igual que el agente. No importa
mcp_server ni abre la base de datos: la frontera del ADR-004 sigue en pie.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from agent.mcp_puente import descubrir_tools
from core.settings import Ajustes, obtener_ajustes

# monotonic y no time(): no retrocede si se ajusta el reloj del host.
ARRANQUE = time.monotonic()

# La sonda a MCP se cachea: un balanceador puede preguntar cada pocos segundos
# y no hace falta abrir una sesion MCP nueva en cada visita.
TTL_SONDA = 5.0
_ultima_sonda: tuple[float, "Sonda"] | None = None


class Sonda(BaseModel):
    """Resultado de preguntarle al servidor MCP si esta ahi."""

    ok: bool
    tools: int
    detalle: str


class Salud(BaseModel):
    estado: str
    version: str


class Estado(BaseModel):
    """Todo lo que la pagina de estado necesita, en una sola llamada."""

    entorno: str
    version: str
    commit: str
    segundos_en_pie: float
    proveedor_voz: str
    modelo_llm: str
    llm_configurado: bool
    mcp_url: str
    mcp_ok: bool
    mcp_tools: int
    mcp_detalle: str


async def sondear_mcp(ajustes: Ajustes) -> Sonda:
    global _ultima_sonda
    ahora = time.monotonic()
    if _ultima_sonda is not None and ahora - _ultima_sonda[0] < TTL_SONDA:
        return _ultima_sonda[1]

    try:
        tools = await descubrir_tools(ajustes.mcp_server_url)
        sonda = Sonda(ok=True, tools=len(tools), detalle="tools descubiertas")
    except Exception as error:
        # Una sonda que lanza excepcion tumba la pagina de estado justo cuando
        # mas falta hace. Un fallo de MCP es un DATO, no un error de esta API.
        sonda = Sonda(ok=False, tools=0, detalle=str(error))

    _ultima_sonda = (ahora, sonda)
    return sonda


app = FastAPI(
    title="Taller de detallado - API de voz",
    description="Salud, preparacion y estado del agente telefonico.",
    version=obtener_ajustes().version_app,
)


@app.get("/salud", response_model=Salud, summary="Liveness: el proceso vive?")
async def salud() -> Salud:
    """NO consulta nada externo, a proposito.

    Si esta ruta dependiera de MCP, un arranque lento de MCP haria que el
    orquestador matara esta API, que volveria a fallar por lo mismo: un bucle
    de reinicios causado por la propia sonda. Liveness solo debe fallar cuando
    reiniciar arregla el problema.
    """
    return Salud(estado="vivo", version=obtener_ajustes().version_app)


@app.get("/listo", response_model=Sonda, summary="Readiness: puede atender?")
async def listo(respuesta: Response) -> Sonda:
    """Aqui SI se mira la dependencia. Un 503 saca la instancia del balanceador
    sin reiniciarla: cuando MCP vuelva, esta ruta da 200 otra vez sola."""
    sonda = await sondear_mcp(obtener_ajustes())
    if not sonda.ok:
        respuesta.status_code = 503
    return sonda


@app.get("/estado", response_model=Estado, summary="Estado completo en JSON")
async def estado() -> Estado:
    ajustes = obtener_ajustes()
    sonda = await sondear_mcp(ajustes)
    return Estado(
        entorno=ajustes.deploy_env,
        version=ajustes.version_app,
        commit=ajustes.commit_git,
        segundos_en_pie=round(time.monotonic() - ARRANQUE, 1),
        proveedor_voz=ajustes.voice_provider,
        modelo_llm=ajustes.llm_model or "(sin configurar)",
        # Se informa si HAY credencial, nunca la credencial. Y no se llama al
        # modelo: una pagina de estado no debe gastar tokens ni tardar 3 s.
        llm_configurado=bool(ajustes.llm_api_key and ajustes.llm_model),
        mcp_url=ajustes.mcp_server_url,
        mcp_ok=sonda.ok,
        mcp_tools=sonda.tools,
        mcp_detalle=sonda.detalle,
    )


@app.get("/", response_class=HTMLResponse, summary="Pagina de estado")
async def pagina() -> str:
    """Sin CSS ni fuentes externas: el homelab debe poder servirla sin internet
    y sin que el navegador del visitante filtre la visita a un CDN."""
    e = await estado()
    color = "#1a7f37" if e.mcp_ok else "#b42318"
    etiqueta = "operativo" if e.mcp_ok else "degradado"
    filas = "".join(
        f"<tr><th>{clave}</th><td>{valor}</td></tr>"
        for clave, valor in (
            ("entorno", e.entorno),
            ("version", e.version),
            ("commit", e.commit),
            ("en pie", f"{e.segundos_en_pie} s"),
            ("voz", e.proveedor_voz),
            ("modelo", e.modelo_llm),
            ("LLM configurado", "si" if e.llm_configurado else "no"),
            ("MCP", f"{e.mcp_url} - {e.mcp_tools} tools"),
            ("detalle MCP", e.mcp_detalle),
        )
    )
    return f"""<!doctype html>
<html lang="es"><meta charset="utf-8">
<title>Estado - taller de detallado</title>
<style>
 body {{ font: 15px/1.5 system-ui, sans-serif; margin: 3rem auto; max-width: 42rem; color: #1b1b1b; padding: 0 1rem; }}
 h1 {{ font-size: 1.2rem; margin-bottom: .25rem; }}
 .badge {{ background: {color}; color: #fff; padding: .15rem .6rem; border-radius: 999px; font-size: .75rem; }}
 table {{ border-collapse: collapse; margin-top: 1.5rem; width: 100%; }}
 th, td {{ text-align: left; padding: .5rem .75rem; border-bottom: 1px solid #e3e3e3; }}
 th {{ width: 11rem; font-weight: 600; color: #555; }}
 td {{ font-family: ui-monospace, monospace; word-break: break-all; }}
 p {{ color: #666; font-size: .85rem; }}
</style>
<h1>Agente telefonico - taller de detallado <span class="badge">{etiqueta}</span></h1>
<p>Sirviendo desde el entorno <strong>{e.entorno}</strong>.</p>
<table>{filas}</table>
<p>JSON en <a href="/estado">/estado</a> - sondas en <a href="/salud">/salud</a> y <a href="/listo">/listo</a> - OpenAPI en <a href="/docs">/docs</a></p>
</html>"""
