"""Interfaz VoiceProvider: el patrón Strategy detrás del Switch B.

El agente solo conoce esta interfaz. Qué hay detrás (Whisper y Piper en local,
o un servicio en la nube) lo decide voice/fabrica.py leyendo VOICE_PROVIDER.

ABC y no typing.Protocol: con ABC, instanciar un proveedor al que le falte un
método falla en el acto con TypeError. Un Protocol solo lo detectaría un
verificador de tipos estático, que este proyecto todavía no ejecuta.
"""

from abc import ABC, abstractmethod

from voice.audio import Audio


class VoiceProvider(ABC):
    nombre: str = "abstracto"

    @abstractmethod
    async def transcribe(self, audio: Audio) -> str:
        """Audio del cliente -> texto. Cadena vacía si no hubo voz."""

    @abstractmethod
    async def synthesize(self, texto: str) -> Audio:
        """Texto del agente -> audio listo para reproducir."""
