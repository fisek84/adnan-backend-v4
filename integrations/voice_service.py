import base64
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import UploadFile
import openai
import os


class VoiceService:

    def __init__(self):
        # Load OpenAI API key
        openai.api_key = os.getenv("OPENAI_API_KEY")

        # No explicit client object needed; using openai.audio.transcriptions.create
        pass

    async def save_temp_audio(self, file: UploadFile) -> Path:
        suffix = Path(file.filename).suffix or ".wav"
        temp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        data = await file.read()
        temp.write(data)
        temp.flush()
        return Path(temp.name)

    async def transcribe(self, file: UploadFile) -> str:
        audio_path = await self.save_temp_audio(file)

        try:
            with open(audio_path, "rb") as f:
                result = openai.audio.transcriptions.create(
                    model="whisper-1",
                    file=f
                )
            return result.text.strip()
        finally:
            audio_path.unlink(missing_ok=True)

    def transcribe_base64(self, audio_b64: str, ext: str = ".wav") -> str:
        raw = base64.b64decode(audio_b64)
        temp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        temp.write(raw)
        temp.flush()
        path = Path(temp.name)

        try:
            with open(path, "rb") as f:
                result = openai.audio.transcriptions.create(
                    model="whisper-1",
                    file=f
                )
            return result.text.strip()
        finally:
            path.unlink(missing_ok=True)
