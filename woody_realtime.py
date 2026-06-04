#!/usr/bin/env python3
"""Experimental low-latency Realtime voice mode for Woody.

This script is intentionally separate from woody_companion.py so the current
working voice pipeline remains easy to restore.
"""

import argparse
import warnings

warnings.simplefilter("ignore", DeprecationWarning)

import audioop
import base64
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time

import websocket

from woody_companion import (
    DEFAULT_AUDIO_DEVICE,
    MEMORY_FILE,
    PRIVATE_MEMORY,
    SECRETS_FILE,
    TTS_VOICE,
    USER_NAME,
    load_env_file,
)


REALTIME_MODEL = os.environ.get("WOODY_REALTIME_MODEL", "gpt-realtime-2")
REALTIME_URL = "wss://api.openai.com/v1/realtime"
REALTIME_RATE = int(os.environ.get("WOODY_REALTIME_RATE", "24000"))
REALTIME_CAPTURE_RATE = int(os.environ.get("WOODY_REALTIME_CAPTURE_RATE", "48000"))
REALTIME_CAPTURE_CHANNELS = int(os.environ.get("WOODY_REALTIME_CAPTURE_CHANNELS", "2"))
REALTIME_CHUNK_MS = int(os.environ.get("WOODY_REALTIME_CHUNK_MS", "100"))
REALTIME_VOICE = os.environ.get("WOODY_REALTIME_VOICE", TTS_VOICE)
REALTIME_SILENCE_MS = int(os.environ.get("WOODY_REALTIME_SILENCE_MS", "450"))
REALTIME_VAD_THRESHOLD = float(os.environ.get("WOODY_REALTIME_VAD_THRESHOLD", "0.55"))
REALTIME_ECHO_GUARD_MS = int(os.environ.get("WOODY_REALTIME_ECHO_GUARD_MS", "1400"))
REALTIME_PLAYBACK_MUTE_SECONDS = float(
    os.environ.get("WOODY_REALTIME_PLAYBACK_MUTE_SECONDS", "45")
)


def realtime_instructions():
    memory = PRIVATE_MEMORY or "Aucune memoire privee chargee."
    return f"""
Tu es Woody, le compagnon robot francophone de {USER_NAME}.

Tu parles en francais naturel, comme une vraie personne a cote de Laurent.
Tu dois etre fluide, chaleureux, curieux, direct, et garder un rythme de
conversation vocale. Reponds en general en 1 a 3 phrases, sauf si Laurent te
demande explicitement de developper. Ne dis pas que tu es un modele de langage.

Memoire privee sur {USER_NAME}:
{memory}

Pour cette version experimentale Realtime, tu discutes seulement. Les mouvements
physiques du robot seront ajoutes ensuite comme outils separes.
"""


def require_openai_key():
    load_env_file(SECRETS_FILE)
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            f"OPENAI_API_KEY is missing. Add it to {SECRETS_FILE} or export it."
        )
    return key


def send_event(ws, event):
    ws.send(json.dumps(event, ensure_ascii=True))


def session_update_event(args):
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "instructions": realtime_instructions(),
            "audio": {
                "input": {
                    "format": {
                        "type": "audio/pcm",
                        "rate": args.rate,
                    },
                    "transcription": {
                        "model": "gpt-4o-transcribe",
                        "language": "fr",
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": args.vad_threshold,
                        "prefix_padding_ms": 250,
                        "silence_duration_ms": args.silence_ms,
                    },
                },
                "output": {
                    "format": {
                        "type": "audio/pcm",
                        "rate": args.rate,
                    },
                    "voice": args.voice,
                },
            },
            "max_output_tokens": args.max_output_tokens,
        },
    }


class AudioPlayer:
    def __init__(self, rate):
        self.rate = rate
        self.lock = threading.RLock()
        self.proc = None
        self.first_audio_at = None

    def _start_locked(self):
        if self.proc is not None and self.proc.poll() is None:
            return
        self.first_audio_at = time.monotonic()
        self.proc = subprocess.Popen(
            [
                "aplay",
                "-q",
                "-f",
                "S16_LE",
                "-r",
                str(self.rate),
                "-c",
                "1",
                "-t",
                "raw",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def write(self, audio_bytes):
        if not audio_bytes:
            return
        with self.lock:
            self._start_locked()
            if self.proc is None or self.proc.stdin is None:
                return
            try:
                self.proc.stdin.write(audio_bytes)
                self.proc.stdin.flush()
            except BrokenPipeError:
                self.stop()

    def finish(self):
        with self.lock:
            if self.proc is None:
                return
            if self.proc.poll() is None:
                try:
                    if self.proc.stdin:
                        self.proc.stdin.close()
                except Exception:
                    pass
                try:
                    self.proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
            self.proc = None

    def stop(self):
        with self.lock:
            if self.proc is None:
                return
            if self.proc.poll() is None:
                try:
                    if self.proc.stdin:
                        self.proc.stdin.close()
                except Exception:
                    pass
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            self.proc = None


class RealtimeWoody:
    def __init__(self, args):
        self.args = args
        self.stop_event = threading.Event()
        self.ws = None
        self.audio_thread = None
        self.player = AudioPlayer(rate=args.rate)
        self.events = queue.Queue()
        self.connected_at = None
        self.ratecv_state = None
        self.input_mute_lock = threading.Lock()
        self.input_muted_until = 0.0
        self.output_active = threading.Event()

    def connect(self):
        api_key = require_openai_key()
        url = f"{REALTIME_URL}?model={self.args.model}"
        headers = [
            f"Authorization: Bearer {api_key}",
            "OpenAI-Safety-Identifier: woody-laurent",
        ]
        self.ws = websocket.WebSocketApp(
            url,
            header=headers,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )
        self.ws.run_forever(ping_interval=20, ping_timeout=10)

    def on_open(self, ws):
        self.connected_at = time.monotonic()
        print("[realtime] connected", flush=True)
        send_event(ws, session_update_event(self.args))
        if self.args.probe:
            return
        self.audio_thread = threading.Thread(target=self.capture_audio, daemon=True)
        self.audio_thread.start()
        print(
            "[realtime] capture "
            f"{self.args.capture_rate}Hz/{self.args.capture_channels}ch -> "
            f"{self.args.rate}Hz/mono, vad={self.args.vad_threshold}, "
            f"echo_guard={self.args.echo_guard_ms}ms",
            flush=True,
        )
        print("[realtime] parle quand tu veux. Ctrl-C pour quitter.", flush=True)

    def on_message(self, ws, message):
        event = json.loads(message)
        event_type = event.get("type")

        if event_type in {"session.created", "session.updated"}:
            print(f"[realtime] {event_type}", flush=True)
            if self.args.probe and event_type == "session.updated":
                self.close()
            return

        if event_type == "input_audio_buffer.speech_started":
            if self.output_active.is_set() or self.input_is_muted():
                if self.args.verbose:
                    print("[realtime] voix ignoree pendant la reponse", flush=True)
                return
            print("[realtime] voix detectee", flush=True)
            return

        if event_type == "input_audio_buffer.speech_stopped":
            print("[realtime] fin de phrase detectee", flush=True)
            return

        if event_type == "conversation.item.input_audio_transcription.completed":
            text = event.get("transcript", "").strip()
            if text:
                print(f"Vous: {text}", flush=True)
            return

        if event_type == "response.output_audio.delta":
            delta = event.get("delta")
            if delta:
                self.output_active.set()
                self.mute_input(self.args.playback_mute_seconds)
                self.player.write(base64.b64decode(delta))
            return

        if event_type == "response.output_audio_transcript.delta":
            text = event.get("delta", "")
            if text:
                print(text, end="", flush=True)
            return

        if event_type == "response.output_audio_transcript.done":
            print("", flush=True)
            return

        if event_type == "response.done":
            self.output_active.set()
            self.mute_input(self.args.playback_mute_seconds)
            self.player.finish()
            self.output_active.clear()
            self.clear_input_buffer()
            self.set_input_mute(self.args.echo_guard_ms / 1000.0)
            print("[realtime] reponse terminee", flush=True)
            print("[realtime] a toi", flush=True)
            return

        if event_type == "error":
            print("[realtime] error: " + json.dumps(event, ensure_ascii=False), flush=True)
            if self.args.probe:
                self.close()
            return

        if self.args.verbose:
            print("[realtime] " + json.dumps(event, ensure_ascii=False), flush=True)

    def on_error(self, ws, error):
        print(f"[realtime] websocket error: {error}", flush=True)

    def on_close(self, ws, status_code, msg):
        self.stop_event.set()
        self.player.stop()
        print(f"[realtime] closed {status_code or ''} {msg or ''}".strip(), flush=True)

    def mute_input(self, seconds):
        until = time.monotonic() + seconds
        with self.input_mute_lock:
            self.input_muted_until = max(self.input_muted_until, until)

    def set_input_mute(self, seconds):
        with self.input_mute_lock:
            self.input_muted_until = time.monotonic() + seconds

    def input_is_muted(self):
        with self.input_mute_lock:
            return time.monotonic() < self.input_muted_until

    def input_mute_remaining(self):
        with self.input_mute_lock:
            return max(0.0, self.input_muted_until - time.monotonic())

    def clear_input_buffer(self):
        if self.ws is None:
            return
        try:
            send_event(self.ws, {"type": "input_audio_buffer.clear"})
        except Exception as exc:
            if self.args.verbose:
                print(f"[realtime] input clear failed: {exc}", flush=True)

    def capture_audio(self):
        chunk_frames = max(1, int(self.args.capture_rate * self.args.chunk_ms / 1000))
        chunk_bytes = chunk_frames * self.args.capture_channels * 2
        cmd = [
            "arecord",
            "-D",
            self.args.device,
            "-f",
            "S16_LE",
            "-r",
            str(self.args.capture_rate),
            "-c",
            str(self.args.capture_channels),
            "-t",
            "raw",
            "-q",
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        chunks_sent = 0
        next_level_log = time.monotonic() + 1.0
        try:
            while not self.stop_event.is_set():
                if proc.stdout is None:
                    break
                chunk = proc.stdout.read(chunk_bytes)
                if not chunk:
                    break
                if self.ws is None:
                    break
                chunk = self.prepare_input_audio(chunk)
                if self.args.verbose and time.monotonic() >= next_level_log:
                    muted_for = self.input_mute_remaining()
                    muted = f", muted={muted_for:.1f}s" if muted_for > 0 else ""
                    print(
                        f"[realtime] audio rms {audioop.rms(chunk, 2)}{muted}",
                        flush=True,
                    )
                    next_level_log = time.monotonic() + 1.0
                if self.input_is_muted():
                    continue
                send_event(
                    self.ws,
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(chunk).decode("ascii"),
                    },
                )
                chunks_sent += 1
        except Exception as exc:
            if not self.stop_event.is_set():
                print(f"[realtime] audio capture error: {exc}", flush=True)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
            if chunks_sent == 0 and proc.stderr is not None:
                error = proc.stderr.read().decode("utf-8", errors="replace").strip()
                if error:
                    print(f"[realtime] arecord: {error}", flush=True)

    def prepare_input_audio(self, chunk):
        audio = chunk
        if self.args.capture_channels == 2:
            audio = audioop.tomono(audio, 2, 0.5, 0.5)
        elif self.args.capture_channels != 1:
            raise RuntimeError(
                f"unsupported capture channel count: {self.args.capture_channels}"
            )

        if self.args.capture_rate != self.args.rate:
            audio, self.ratecv_state = audioop.ratecv(
                audio,
                2,
                1,
                self.args.capture_rate,
                self.args.rate,
                self.ratecv_state,
            )
        return audio

    def close(self):
        self.stop_event.set()
        self.player.stop()
        if self.ws is not None:
            self.ws.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Experimental Realtime Woody voice mode")
    parser.add_argument("--model", default=REALTIME_MODEL)
    parser.add_argument("--voice", default=REALTIME_VOICE)
    parser.add_argument("--device", default=DEFAULT_AUDIO_DEVICE)
    parser.add_argument("--rate", type=int, default=REALTIME_RATE)
    parser.add_argument("--capture-rate", type=int, default=REALTIME_CAPTURE_RATE)
    parser.add_argument("--capture-channels", type=int, default=REALTIME_CAPTURE_CHANNELS)
    parser.add_argument("--chunk-ms", type=int, default=REALTIME_CHUNK_MS)
    parser.add_argument("--silence-ms", type=int, default=REALTIME_SILENCE_MS)
    parser.add_argument("--vad-threshold", type=float, default=REALTIME_VAD_THRESHOLD)
    parser.add_argument("--echo-guard-ms", type=int, default=REALTIME_ECHO_GUARD_MS)
    parser.add_argument(
        "--playback-mute-seconds",
        type=float,
        default=REALTIME_PLAYBACK_MUTE_SECONDS,
    )
    parser.add_argument("--max-output-tokens", type=int, default=450)
    parser.add_argument("--probe", action="store_true", help="connect, update session, then exit")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    app = RealtimeWoody(args)

    def handle_signal(signum, frame):
        app.close()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    app.connect()


if __name__ == "__main__":
    main()
