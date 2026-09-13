"""Contrato de audio compartido por todos los proveedores de voz.

Regla de diseño: la frecuencia de muestreo VIAJA CON el audio. En esta cadena
conviven al menos cuatro: micrófono (48 kHz), Whisper (16 kHz), Piper
(22.05 kHz) y, en el futuro, la línea telefónica (8 kHz). Un audio sin su
frecuencia se reproduce acelerado o grave sin lanzar ningún error.
"""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass


@dataclass(frozen=True)
class Audio:
    """Audio PCM de 16 bits, mono, little-endian, con su frecuencia."""

    pcm16: bytes
    sample_rate: int

    def __post_init__(self) -> None:
        # Validar al construir: un audio corrupto debe fallar aquí, con nombre,
        # y no tres capas más abajo como ruido en la bocina.
        if self.sample_rate <= 0:
            raise ValueError(f"sample_rate inválido: {self.sample_rate}")
        if len(self.pcm16) % 2:
            raise ValueError("PCM de 16 bits debe tener un número par de bytes")

    @property
    def duracion(self) -> float:
        return len(self.pcm16) / 2 / self.sample_rate

    def a_wav(self) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(self.pcm16)
        return buffer.getvalue()

    @classmethod
    def desde_wav(cls, datos: bytes) -> Audio:
        with wave.open(io.BytesIO(datos), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise ValueError(
                    f"se esperaba WAV mono de 16 bits; llegó {wav.getnchannels()} canal(es) "
                    f"de {8 * wav.getsampwidth()} bits"
                )
            return cls(wav.readframes(wav.getnframes()), wav.getframerate())
