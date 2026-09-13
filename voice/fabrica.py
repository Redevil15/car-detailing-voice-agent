"""Único lugar del proyecto que conoce las implementaciones de VoiceProvider.

Todo el Switch B vive en esta función. Ningún otro módulo pregunta si la voz
es local o en la nube.
"""

from core.settings import Ajustes
from voice.provider import VoiceProvider


def crear_proveedor_voz(ajustes: Ajustes) -> VoiceProvider:
    if ajustes.voice_provider == "local":
        from voice.local_provider import LocalVoiceProvider

        return LocalVoiceProvider(ajustes.whisper_modelo_dir, ajustes.piper_voz)

    raise NotImplementedError(
        f"VOICE_PROVIDER={ajustes.voice_provider!r} todavía no tiene implementación. "
        "Por ahora solo existe 'local'."
    )
