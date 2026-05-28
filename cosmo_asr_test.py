import os
import subprocess
from openai import OpenAI

AUDIO_FILE = "/home/pi/cosmo_robotics/recording.wav"

def record_audio(seconds=5):
    print(f"Recording {seconds} seconds...")
    cmd = [
        "arecord",
        "-D", "hw:2,0",
        "-f", "S16_LE",
        "-r", "48000",
        "-c", "2",
        "-d", str(seconds),
        AUDIO_FILE,
    ]
    subprocess.run(cmd, check=True)
    print("Recording saved:", AUDIO_FILE)

def transcribe():
    client = OpenAI()
    with open(AUDIO_FILE, "rb") as audio:
        text = client.audio.transcriptions.create(
            model="gpt-4o-transcribe",
            file=audio,
            language="fr",
        )
    return text.text

if __name__ == "__main__":
    record_audio(5)
    result = transcribe()
    print("You said:")
    print(result)
