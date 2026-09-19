#!/bin/sh
# Arranque idempotente: siembra la base solo si se pide Y no existe.
#
# La siembra se activa por variable de entorno y no por defecto, porque la
# misma imagen sirve a varios servicios y solo uno es dueño de los datos.
set -e

RUTA_BD="${RUTA_BD:-/app/mcp_server/db/detailing.db}"

if [ "${SEMBRAR_BD:-false}" = "true" ] && [ ! -f "$RUTA_BD" ]; then
    echo "[arranque] no hay base en $RUTA_BD: sembrando datos sintéticos"
    python mcp_server/db/seed.py
elif [ "${SEMBRAR_BD:-false}" = "true" ]; then
    echo "[arranque] base existente en $RUTA_BD: no se toca"
fi

# exec: el proceso real sustituye al script y recibe las señales de Docker.
# Sin exec, un "docker stop" mataría el shell y dejaría al hijo huérfano.
exec "$@"
