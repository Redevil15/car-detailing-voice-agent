"""Ida y vuelta de voz con el proveedor configurado en .env: texto -> audio -> texto.

Guarda el audio en sandbox/voz_prueba.wav para escucharlo con:
    afplay sandbox/voz_prueba.wav

    uv run sandbox/15_voz_local.py
"""

import asyncio
import time
from pathlib import Path

from core.settings import obtener_ajustes
from voice.audio import Audio
from voice.fabrica import crear_proveedor_voz

FRASES = [
    "El encerado cuesta mil doscientos pesos y dura dos horas.",
    "Tenemos lavado básico y lavado premium. ¿Cuál le interesa?",
    "Para agendar necesito su nombre y su número de teléfono.",
]


async def main() -> None:
    ajustes = obtener_ajustes()
    print(f"VOICE_PROVIDER={ajustes.voice_provider}")

    inicio = time.perf_counter()
    voz = crear_proveedor_voz(ajustes)
    print(f"Proveedor {type(voz).__name__} listo en {time.perf_counter() - inicio:.2f}s\n")

    audios: list[Audio] = []
    for frase in FRASES:
        inicio = time.perf_counter()
        audio = await voz.synthesize(frase)
        t_tts = time.perf_counter() - inicio

        inicio = time.perf_counter()
        escuchado = await voz.transcribe(audio)
        t_stt = time.perf_counter() - inicio

        audios.append(audio)
        print(f"  original : {frase}")
        print(f"  escuchado: {escuchado}")
        print(f"  TTS {t_tts:.2f}s -> {audio.duracion:.2f}s de audio | STT {t_stt:.2f}s\n")

    frecuencia = audios[0].sample_rate
    pausa = b"\x00\x00" * frecuencia  # un segundo de silencio entre frases
    unido = Audio(pausa.join(a.pcm16 for a in audios), frecuencia)

    destino = Path(__file__).parent / "voz_prueba.wav"
    destino.write_bytes(unido.a_wav())
    print(f"Audio guardado ({unido.duracion:.1f}s). Escúchalo con:  afplay sandbox/voz_prueba.wav")


if __name__ == "__main__":
    asyncio.run(main())
