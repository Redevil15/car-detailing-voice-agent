"""Primera conversación de voz completa: micrófono -> Whisper -> agente -> Piper -> bocina.

Push-to-talk: Enter para empezar a hablar y Enter para terminar. Mientras suena
la bocina el micrófono está cerrado, así el agente no se escucha a sí mismo.

Requiere el servidor MCP corriendo en el puerto 8000.

    uv run sandbox/16_conversacion_voz.py
"""

import asyncio
import time
import uuid

import numpy as np
import sounddevice as sd

from agent.grafo import construir_agente, entrada_de_turno
from core.settings import obtener_ajustes
from voice.audio import Audio
from voice.fabrica import crear_proveedor_voz

FRECUENCIA_MIC = 16000  # la que espera Whisper; CoreAudio remuestrea desde 48 kHz
DURACION_MINIMA = 0.4   # segundos: menos que esto es un Enter doble, no una frase
UMBRAL_SILENCIO = 200   # pico en int16 (máximo 32767): por debajo no se captó nada


class Grabadora:
    """Acumula lo que entrega el micrófono hasta que se presiona Enter."""

    def __init__(self, sample_rate: int = FRECUENCIA_MIC) -> None:
        self.sample_rate = sample_rate
        self._bloques: list[bytes] = []
        self.incidencias = 0

    def _callback(self, indata, frames, tiempo, status) -> None:
        # Corre en el hilo de PortAudio, no en el nuestro: debe hacer lo mínimo.
        if status:
            self.incidencias += 1  # por ejemplo, un desbordamiento de buffer
        # tobytes() COPIA. PortAudio reutiliza el mismo buffer en cada llamada;
        # guardar la referencia deja todos los bloques iguales al último.
        # Medido: la transcripción pasó de la frase completa a ''.
        self._bloques.append(indata.tobytes())

    def grabar_hasta_enter(self) -> Audio:
        self._bloques = []
        self.incidencias = 0
        with sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype="int16", callback=self._callback
        ):
            input("   [grabando] presiona Enter para terminar ")
        return Audio(b"".join(self._bloques), self.sample_rate)


def reproducir(audio: Audio) -> None:
    sd.play(np.frombuffer(audio.pcm16, dtype=np.int16), audio.sample_rate, blocking=True)


def pico(audio: Audio) -> int:
    if not audio.pcm16:
        return 0
    muestras = np.frombuffer(audio.pcm16, dtype=np.int16)
    # A int32 antes de abs(): en int16, abs(-32768) desborda y sigue siendo negativo.
    return int(np.abs(muestras.astype(np.int32)).max())


async def main() -> None:
    ajustes = obtener_ajustes()
    print("Cargando voz y agente...")
    voz = crear_proveedor_voz(ajustes)
    agente = await construir_agente(ajustes)
    grabadora = Grabadora()

    # Un thread_id por ejecución: cada vez que corres el script es una llamada nueva.
    config = {"configurable": {"thread_id": f"llamada-{uuid.uuid4().hex[:8]}"}}

    saludo = "Buenas tardes, le atiende el taller de detallado automotriz. ¿En qué le puedo ayudar?"
    print(f"\nAGENTE: {saludo}")
    await asyncio.to_thread(reproducir, await voz.synthesize(saludo))

    while True:
        orden = await asyncio.to_thread(input, "\nEnter para hablar (o escribe 'salir'): ")
        if orden.strip().lower() in {"salir", "q", "exit"}:
            break

        audio = await asyncio.to_thread(grabadora.grabar_hasta_enter)
        if audio.duracion < DURACION_MINIMA:
            print("   (grabación demasiado corta, intenta de nuevo)")
            continue
        if pico(audio) < UMBRAL_SILENCIO:
            print("   (no se captó sonido: revisa el permiso de micrófono de tu terminal)")
            continue

        inicio = time.perf_counter()
        texto = await voz.transcribe(audio)
        t_stt = time.perf_counter() - inicio
        if not texto:
            print("   (se grabó sonido, pero no se reconoció voz)")
            continue
        print(f"CLIENTE: {texto}")

        inicio = time.perf_counter()
        ruta: list[str] = []
        async for paso in agente.astream(entrada_de_turno(texto), config, stream_mode="updates"):
            ruta.extend(paso.keys())
        estado = await agente.aget_state(config)
        respuesta = str(estado.values["messages"][-1].content)
        t_agente = time.perf_counter() - inicio

        inicio = time.perf_counter()
        audio_respuesta = await voz.synthesize(respuesta)
        t_tts = time.perf_counter() - inicio

        print(f"AGENTE: {respuesta}")
        print(
            f"   ruta: {' -> '.join(ruta)}\n"
            f"   STT {t_stt:.2f}s + agente {t_agente:.2f}s + TTS {t_tts:.2f}s"
            f" = {t_stt + t_agente + t_tts:.2f}s de silencio antes de responder"
        )
        if estado.values.get("fallo_grave"):
            print(f"   FALLO: {estado.values['fallo_grave']}")
        for aviso in estado.values.get("avisos_llm") or []:
            print(f"   aviso LLM: {aviso}")
        if grabadora.incidencias:
            print(f"   aviso: {grabadora.incidencias} incidencias de buffer en el micrófono")

        await asyncio.to_thread(reproducir, audio_respuesta)

    print("Llamada terminada.")


if __name__ == "__main__":
    asyncio.run(main())
