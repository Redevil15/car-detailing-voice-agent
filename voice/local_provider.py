"""Proveedor de voz autoalojado: faster-whisper (STT) + Piper (TTS).

Corre en CPU en la Mac. En el homelab, el mismo código recibirá otro
dispositivo; el agente no cambia.
"""

import asyncio
import io
from pathlib import Path

from voice.audio import Audio
from voice.provider import VoiceProvider

DESCARGA_WHISPER = (
    "uv run python -c \"from faster_whisper import download_model; "
    "download_model('small', output_dir='models/whisper-small')\""
)
DESCARGA_PIPER = "uv run python -m piper.download_voices es_MX-claude-high --download-dir models/piper"


# Sesga a Whisper con el vocabulario del taller: sin esto confundía palabras
# del dominio ("mejor" se transcribió como "M-Mentos").
VOCABULARIO = (
    "Taller de car detailing. Servicios: lavado básico, lavado premium, encerado, "
    "pulido completo, limpieza de interiores, descontaminación de pintura, "
    "tratamiento cerámico. El cliente pregunta precios, revisa disponibilidad "
    "y agenda una cita."
)


class LocalVoiceProvider(VoiceProvider):
    nombre = "local"

    def __init__(self, whisper_dir: Path, piper_voz: Path, dispositivo: str = "cpu") -> None:
        # Imports DENTRO del constructor, no arriba del archivo: la imagen de
        # AWS no instala el grupo voz-local, y debe poder importar voice/ sin
        # que estas dos librerías existan.
        from faster_whisper import WhisperModel
        from piper import PiperVoice

        if not (whisper_dir / "model.bin").exists():
            raise FileNotFoundError(f"No hay modelo Whisper en {whisper_dir}. Descárgalo con:\n  {DESCARGA_WHISPER}")
        if not piper_voz.exists():
            raise FileNotFoundError(f"No hay voz de Piper en {piper_voz}. Descárgala con:\n  {DESCARGA_PIPER}")

        # Se cargan UNA vez, al crear el proveedor, y no en cada turno.
        self._stt = WhisperModel(str(whisper_dir), device=dispositivo, compute_type="int8")
        self._tts = PiperVoice.load(piper_voz)

    # Whisper y Piper son síncronos y ocupan CPU. Llamados directo desde código
    # async congelan el event loop (medido: 0 de 19 latidos durante una
    # transcripción). to_thread los saca del loop (18 de 18 latidos).

    async def transcribe(self, audio: Audio) -> str:
        return await asyncio.to_thread(self._transcribir, audio)

    async def synthesize(self, texto: str) -> Audio:
        return await asyncio.to_thread(self._sintetizar, texto)

    def _transcribir(self, audio: Audio) -> str:
        segmentos, _ = self._stt.transcribe(
            io.BytesIO(audio.a_wav()),  # Whisper remuestrea el WAV a 16 kHz por dentro
            initial_prompt=VOCABULARIO,  # vocabulario del negocio
            language="es",              # fijarlo evita perder tiempo detectando idioma
            beam_size=1,                # decodificación greedy: con small ya fue exacta
            vad_filter=True,            # recorta silencios y evita texto inventado
        )
        # Los segmentos son un generador perezoso: la transcripción ocurre aquí.
        return " ".join(s.text.strip() for s in segmentos).strip()

    def _sintetizar(self, texto: str) -> Audio:
        if not texto.strip():
            raise ValueError("No se puede sintetizar un texto vacío")
        # Piper entrega un trozo por frase. Por ahora se unen; en Fase 5 se
        # usarán para empezar a hablar antes de terminar de sintetizar.
        trozos = list(self._tts.synthesize(texto))
        return Audio(b"".join(t.audio_int16_bytes for t in trozos), trozos[0].sample_rate)
