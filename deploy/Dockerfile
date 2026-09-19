# syntax=docker/dockerfile:1.7
# Imagen ÚNICA para los dos procesos del sistema (servidor MCP y agente).
# Qué proceso corre lo decide el comando, no la imagen.

ARG PYTHON_VERSION=3.12

# --------------------------------------------------------------- construcción
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

# Solo el manifiesto y el lock: esta capa se reaprovecha mientras no cambien
# las dependencias, aunque cambie todo el código.
COPY pyproject.toml uv.lock ./

# El grupo voz-local pesa 164 MB (onnxruntime, piper, av). La imagen de AWS no
# lo necesita: allí no hay GPU y la voz será de nube.
ARG VOZ_LOCAL=false

# --locked falla si uv.lock no coincide con pyproject.toml: es la garantía de
# que la imagen instala exactamente lo mismo que tu máquina.
# La caché de uv vive en un cache mount: acelera builds y NO queda en la imagen.
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$VOZ_LOCAL" = "true" ]; then \
        uv sync --locked --no-install-project --no-default-groups --group voz-local; \
    else \
        uv sync --locked --no-install-project --no-default-groups; \
    fi

# Ahora el código, y la instalación del propio proyecto.
# hatchling valida los metadatos al instalar el proyecto, y pyproject.toml
# declara readme = "README.md": sin este archivo, el build falla.
COPY README.md ./
COPY agent/ ./agent/
COPY core/ ./core/
COPY mcp_server/ ./mcp_server/
COPY voice/ ./voice/
COPY observability/ ./observability/
COPY evals/ ./evals/

RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$VOZ_LOCAL" = "true" ]; then \
        uv sync --locked --no-default-groups --group voz-local; \
    else \
        uv sync --locked --no-default-groups; \
    fi

# ----------------------------------------------------------------- ejecución
# Mismo Debian que la etapa anterior: misma libc, los mismos wheels son válidos.
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

# Usuario sin privilegios: si alguien escapa del proceso, no es root.
RUN groupadd --system taller && useradd --system --gid taller --home-dir /app taller

WORKDIR /app
COPY --from=builder --chown=taller:taller /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    WHISPER_MODEL_DIR=/app/models/whisper-small \
    PIPER_VOICE=/app/models/piper/es_MX-claude-high.onnx \
    MCP_PORT=8000 \
    MCP_HOST=0.0.0.0

USER taller
EXPOSE 8000

# Sin curl en la imagen slim: la sonda se hace con el Python que ya está.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os,socket; socket.create_connection(('127.0.0.1', int(os.environ['MCP_PORT'])), 2).close()"

# Proceso por defecto: el servidor MCP. El agente se lanza con otro comando.
CMD ["python", "mcp_server/server.py"]
