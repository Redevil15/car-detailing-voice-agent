"""Única fuente de configuración del sistema.

Regla del proyecto: ningún otro módulo llama a os.getenv. Todos importan
`obtener_ajustes()` y leen atributos. Esa regla es lo que permite cambiar
de proveedor de LLM o de voz editando .env, sin tocar código, y que un test
construya otros ajustes sin manipular el entorno del proceso.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent

Entorno = Literal["local", "aws"]
ProveedorVoz = Literal["cloud", "local"]


@dataclass(frozen=True)
class Ajustes:
    """Inmutable a propósito: la configuración se lee al arrancar, no muta."""

    deploy_env: Entorno
    voice_provider: ProveedorVoz
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_model_respaldo: str  # opcional: entra si el principal falla
    groq_api_key: str  # sin uso por ahora: Groq quedó fuera (ADR-010)
    whisper_modelo_dir: Path  # carpeta con el model.bin de faster-whisper
    piper_voz: Path  # archivo .onnx de la voz de Piper
    mcp_server_url: str
    langfuse_host: str

    def exigir_llm(self) -> tuple[str, str, str]:
        """Devuelve (api_key, modelo, base_url) o falla con un mensaje útil.

        La exigencia es perezosa: importar este módulo no debe reventar solo
        porque falte una credencial que quizá este proceso no use. El servidor
        MCP, por ejemplo, no necesita ningún LLM.
        """
        if not self.llm_api_key:
            raise RuntimeError("Falta LLM_API_KEY en .env.")
        if not self.llm_model:
            raise RuntimeError(
                "Falta LLM_MODEL en .env. Lista los modelos de tu proveedor "
                "con: uv run sandbox/09_llm.py"
            )
        # Un marcador sin sustituir produce errores del proveedor que culpan a
        # otra cosa (un 401 'missing header', un 404). Mejor detectarlo aquí.
        for nombre, valor in (("LLM_API_KEY", self.llm_api_key), ("LLM_MODEL", self.llm_model)):
            if "PEGA_AQUI" in valor or "EL_QUE_ELIJAS" in valor:
                raise RuntimeError(f"{nombre} tiene un marcador sin sustituir en .env.")
        return self.llm_api_key, self.llm_model, self.llm_base_url


def _leer(nombre: str, defecto: str = "") -> str:
    return os.getenv(nombre, defecto).strip()


def _ruta(nombre: str, defecto: str) -> Path:
    """Ruta leída del entorno. Si es relativa, se resuelve contra la raíz del
    repo y no contra el directorio desde el que se lance el proceso."""
    ruta = Path(_leer(nombre, defecto)).expanduser()
    return ruta if ruta.is_absolute() else RAIZ / ruta


@lru_cache(maxsize=1)
def obtener_ajustes() -> Ajustes:
    """Lee la configuración una sola vez por proceso.

    load_dotenv apunta a la raíz del repo de forma explícita, no al directorio
    actual: si dependiera del cwd, el mismo código se comportaría distinto
    según desde dónde lo lances. En producción (ECS, Docker) no habrá .env;
    load_dotenv no encuentra nada y os.getenv lee el entorno del contenedor.
    """
    load_dotenv(RAIZ / ".env")

    deploy = _leer("DEPLOY_ENV", "local")
    voz = _leer("VOICE_PROVIDER", "cloud")

    # Fallar al arrancar con un mensaje claro es mucho mejor que fallar tres
    # capas más abajo con un error incomprensible.
    if deploy not in ("local", "aws"):
        raise ValueError(f"DEPLOY_ENV inválido: {deploy!r}. Usa 'local' o 'aws'.")
    if voz not in ("cloud", "local"):
        raise ValueError(f"VOICE_PROVIDER inválido: {voz!r}. Usa 'cloud' o 'local'.")

    return Ajustes(
        deploy_env=deploy,
        voice_provider=voz,
        llm_base_url=_leer("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
        llm_api_key=_leer("LLM_API_KEY"),
        llm_model=_leer("LLM_MODEL"),
        llm_model_respaldo=_leer("LLM_MODEL_RESPALDO"),
        groq_api_key=_leer("GROQ_API_KEY"),
        whisper_modelo_dir=_ruta("WHISPER_MODEL_DIR", "models/whisper-small"),
        piper_voz=_ruta("PIPER_VOICE", "models/piper/es_MX-claude-high.onnx"),
        mcp_server_url=_leer("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp"),
        langfuse_host=_leer("LANGFUSE_HOST", "https://cloud.langfuse.com"),
    )
