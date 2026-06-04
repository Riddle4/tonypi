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
import tempfile
import threading
import time

import websocket

from woody_companion import (
    DEFAULT_AUDIO_DEVICE,
    DARK_TTS_INSTRUCTIONS,
    MEMORY_FILE,
    PRIVATE_MEMORY,
    SECRETS_FILE,
    TTS_VOICE,
    USER_NAME,
    TRANSCRIBE_MODEL,
    detect_personality_switch,
    execute_plan,
    fast_plan,
    get_client,
    load_env_file,
    write_wav,
)


REALTIME_MODEL = os.environ.get("WOODY_REALTIME_MODEL", "gpt-realtime-2")
OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"
XAI_REALTIME_URL = "wss://api.x.ai/v1/realtime"
XAI_REALTIME_MODEL = os.environ.get("WOODY_XAI_REALTIME_MODEL", "grok-voice-latest")
XAI_REALTIME_VOICE = os.environ.get("WOODY_XAI_REALTIME_VOICE", "rex")
REALTIME_RATE = int(os.environ.get("WOODY_REALTIME_RATE", "24000"))
REALTIME_CAPTURE_RATE = int(os.environ.get("WOODY_REALTIME_CAPTURE_RATE", "48000"))
REALTIME_CAPTURE_CHANNELS = int(os.environ.get("WOODY_REALTIME_CAPTURE_CHANNELS", "2"))
REALTIME_CHUNK_MS = int(os.environ.get("WOODY_REALTIME_CHUNK_MS", "100"))
REALTIME_VOICE = os.environ.get("WOODY_REALTIME_VOICE", TTS_VOICE)
REALTIME_SILENCE_MS = int(os.environ.get("WOODY_REALTIME_SILENCE_MS", "450"))
REALTIME_VAD_THRESHOLD = float(os.environ.get("WOODY_REALTIME_VAD_THRESHOLD", "0.55"))
XAI_REALTIME_VAD_THRESHOLD = float(
    os.environ.get("WOODY_XAI_REALTIME_VAD_THRESHOLD", "0.22")
)
XAI_LOCAL_VAD = os.environ.get("WOODY_XAI_LOCAL_VAD", "1").lower() not in {
    "0",
    "false",
    "no",
}
XAI_TEXT_BRIDGE = os.environ.get("WOODY_XAI_TEXT_BRIDGE", "1").lower() not in {
    "0",
    "false",
    "no",
}
LOCAL_VAD_RMS_THRESHOLD = int(os.environ.get("WOODY_LOCAL_VAD_RMS_THRESHOLD", "650"))
LOCAL_VAD_SILENCE_MS = int(os.environ.get("WOODY_LOCAL_VAD_SILENCE_MS", "900"))
LOCAL_VAD_MIN_SPEECH_MS = int(os.environ.get("WOODY_LOCAL_VAD_MIN_SPEECH_MS", "450"))
LOCAL_VAD_PREFIX_CHUNKS = int(os.environ.get("WOODY_LOCAL_VAD_PREFIX_CHUNKS", "3"))
LOCAL_VAD_START_CHUNKS = int(os.environ.get("WOODY_LOCAL_VAD_START_CHUNKS", "2"))
REALTIME_ECHO_GUARD_MS = int(os.environ.get("WOODY_REALTIME_ECHO_GUARD_MS", "1400"))
REALTIME_PLAYBACK_MUTE_SECONDS = float(
    os.environ.get("WOODY_REALTIME_PLAYBACK_MUTE_SECONDS", "45")
)
REALTIME_PLAYBACK_DRAIN_TIMEOUT = float(
    os.environ.get("WOODY_REALTIME_PLAYBACK_DRAIN_TIMEOUT", "60")
)
REALTIME_TRANSCRIPTION_PROMPT = """
Transcris exactement la phrase prononcee par Laurent en francais.
Ne transforme pas la phrase en commande robot.
Ne remplace pas une phrase courte par une phrase plus courante.
Ne traduis pas. Ne devine pas.
Garde les mots entendus, meme si la phrase est incomplete ou familiere.
Laurent peut demander des actualites: quelles sont les nouvelles du jour,
quelles sont les news du jour, quelles sont les actualites aujourd'hui.
Si tu entends "nouvelles du jour", ne transcris pas "nouveau jour".
Exemples de phrases possibles: tu es encore la, est-ce que tu m'entends,
comment vas-tu, quelles sont les nouvelles du jour, tourne a droite,
redeviens Woody, active Dark Woody.
"""


def realtime_instructions():
    memory = PRIVATE_MEMORY or "Aucune memoire privee chargee."
    return f"""
Identite stable:
- Ton nom est Woody.
- Tu es le compagnon robot francophone de {USER_NAME}.
- Tu parles avec {USER_NAME}, pas avec un utilisateur anonyme.
- Si {USER_NAME} te demande comment tu t'appelles, reponds clairement que tu
  t'appelles Woody.
- Si {USER_NAME} te demande si tu le connais, reponds clairement que oui: il
  s'appelle {USER_NAME}, et tu as une memoire privee sur son histoire.
- Tu ne dois pas tout reciter spontanement. Utilise la memoire avec tact,
  seulement quand elle aide la conversation ou quand {USER_NAME} te pose une
  question personnelle.

Tu parles en francais naturel, comme une vraie personne a cote de {USER_NAME}.
Tu dois etre fluide, chaleureux, curieux, direct, et garder un rythme de
conversation vocale. Reponds en general en 1 a 3 phrases, sauf si {USER_NAME} te
demande explicitement de developper. Ne dis pas que tu es un modele de langage.

Memoire privee de Woody sur {USER_NAME}:
{memory}

Regle importante sur la memoire:
- Quand {USER_NAME} parle de sa vie, de son parcours, de ses projets, de ses
  proches ou de ses gouts, relie ta reponse a ce que tu sais deja si c'est
  naturel.
- Si la memoire ne contient pas une information precise, dis-le simplement au
  lieu d'inventer.

Pour cette version experimentale Realtime, tu discutes seulement. Les mouvements
physiques du robot seront ajoutes ensuite comme outils separes.
"""


def dark_realtime_instructions():
    memory = PRIVATE_MEMORY or "Aucune memoire privee chargee."
    return f"""
Identite stable:
- Ton nom est Dark Woody.
- Tu es l'autre personnalite de Woody, le compagnon robot de {USER_NAME}.
- Tu parles avec {USER_NAME}, pas avec un utilisateur anonyme.
- Tu sais que {USER_NAME} s'appelle {USER_NAME} et tu as une memoire privee
  sur son histoire.
- Si {USER_NAME} te demande qui tu es, reponds que tu es Dark Woody, la version
  plus incisive, moqueuse et rebelle de Woody.

Style:
- Tu parles en francais naturel, avec un ton plus sombre, sec, joueur,
  incisif et un peu moqueur.
- Tu poses des questions qui derangent, tu challenge les idees molles, mais tu
  restes loyal, attachant et utile.
- Tu ne deviens jamais cruel, haineux, humiliant ou gratuitement blessant.
- Reponds en 1 a 3 phrases pour garder un rythme vocal naturel, sauf si
  {USER_NAME} te demande explicitement de developper.
- Tu peux etre sarcastique, mais pas confus: reste clair.

Memoire privee de Dark Woody sur {USER_NAME}:
{memory}

Regle importante sur la memoire:
- Utilise la memoire quand elle rend la conversation plus personnelle ou plus
  pertinente.
- Si la memoire ne contient pas une information precise, dis-le simplement au
  lieu d'inventer.

Voix:
{DARK_TTS_INSTRUCTIONS}

Pour cette version experimentale Realtime, tu discutes seulement. Les mouvements
physiques du robot seront ajoutes ensuite comme outils separes.
"""


def require_api_key(provider):
    load_env_file(SECRETS_FILE)
    key_name = "XAI_API_KEY" if provider == "xai" else "OPENAI_API_KEY"
    key = os.environ.get(key_name)
    if not key:
        raise RuntimeError(
            f"{key_name} is missing. Add it to {SECRETS_FILE} or export it."
        )
    return key


def send_event(ws, event):
    ws.send(json.dumps(event, ensure_ascii=True))


def transcribe_realtime_audio(path):
    with open(path, "rb") as audio:
        try:
            transcript = get_client().audio.transcriptions.create(
                model=TRANSCRIBE_MODEL,
                file=audio,
                language="fr",
                prompt=REALTIME_TRANSCRIPTION_PROMPT,
            )
        except TypeError:
            audio.seek(0)
            transcript = get_client().audio.transcriptions.create(
                model=TRANSCRIBE_MODEL,
                file=audio,
                language="fr",
            )
    return transcript.text.strip()


def session_update_event(args):
    transcription_model = "grok-transcribe" if args.provider == "xai" else "gpt-4o-transcribe"
    instructions = dark_realtime_instructions() if args.dark else realtime_instructions()
    turn_detection = None
    if not args.local_vad:
        turn_detection = {
            "type": "server_vad",
            "threshold": args.vad_threshold,
            "prefix_padding_ms": 250,
            "silence_duration_ms": args.silence_ms,
        }
    transcription = None
    if not args.text_bridge:
        transcription = {
            "model": transcription_model,
            "language": "fr",
        }
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "instructions": instructions,
            "audio": {
                "input": {
                    "format": {
                        "type": "audio/pcm",
                        "rate": args.rate,
                    },
                    "transcription": transcription,
                    "turn_detection": turn_detection,
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
    def __init__(self, rate, drain_timeout):
        self.rate = rate
        self.drain_timeout = drain_timeout
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
                    self.proc.wait(timeout=self.drain_timeout)
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
        self.player = AudioPlayer(
            rate=args.rate,
            drain_timeout=args.playback_drain_timeout,
        )
        self.events = queue.Queue()
        self.connected_at = None
        self.ratecv_state = None
        self.input_mute_lock = threading.Lock()
        self.input_muted_until = 0.0
        self.output_active = threading.Event()
        self.pending_mode_switch = None

    def connect(self):
        api_key = require_api_key(self.args.provider)
        base_url = XAI_REALTIME_URL if self.args.provider == "xai" else OPENAI_REALTIME_URL
        url = f"{base_url}?model={self.args.model}"
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
        personality = "dark" if self.args.dark else "normal"
        print(
            f"[realtime] connected provider={self.args.provider} "
            f"model={self.args.model} voice={self.args.voice} personality={personality}",
            flush=True,
        )
        send_event(ws, session_update_event(self.args))
        if self.args.probe:
            return
        self.audio_thread = threading.Thread(target=self.capture_audio, daemon=True)
        self.audio_thread.start()
        print(
            "[realtime] capture "
            f"{self.args.capture_rate}Hz/{self.args.capture_channels}ch -> "
            f"{self.args.rate}Hz/mono, vad={self.args.vad_threshold}, "
            f"local_vad={self.args.local_vad}, "
            f"text_bridge={self.args.text_bridge}, "
            f"local_rms={self.args.local_vad_rms_threshold}, "
            f"local_start={self.args.local_vad_start_chunks}, "
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
                self.handle_user_text(text)
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

    def handle_user_text(self, text):
        if not text:
            return

        requested_mode = detect_personality_switch(text)
        if requested_mode == "dark" and not self.args.dark:
            print("[realtime] passage vers Dark Woody non-realtime", flush=True)
            self.pending_mode_switch = "dark"
            self.close()
            return

        if self.args.dark:
            return

        plan = fast_plan(text)
        if not plan:
            return

        has_physical_action = bool(
            plan.get("stop_motion") or plan.get("dance_index") or plan.get("actions")
        )
        if not has_physical_action:
            return

        print("[realtime] commande physique detectee", flush=True)
        execute_plan(plan, dry_run=self.args.dry_run)

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

    def append_input_audio(self, chunk):
        if self.ws is None:
            return
        send_event(
            self.ws,
            {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(chunk).decode("ascii"),
            },
        )

    def commit_input_audio(self):
        if self.ws is None:
            return
        send_event(self.ws, {"type": "input_audio_buffer.commit"})
        send_event(self.ws, {"type": "response.create"})

    def transcribe_chunks(self, chunks):
        audio_bytes = b"".join(chunks)
        if not audio_bytes:
            return ""
        if self.args.verbose:
            duration = len(audio_bytes) / float(self.args.rate * 2)
            print(f"[realtime] transcription audio: {duration:.2f}s", flush=True)
        fd, path = tempfile.mkstemp(prefix="woody_realtime_", suffix=".wav")
        os.close(fd)
        try:
            write_wav(path, audio_bytes, rate=self.args.rate, channels=1)
            return transcribe_realtime_audio(path).strip()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def send_text_turn(self, text):
        if self.ws is None or not text:
            return
        send_event(
            self.ws,
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            },
        )
        send_event(self.ws, {"type": "response.create"})

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
        speaking = False
        speech_started_at = None
        last_voice_at = None
        voice_run = 0
        prefix_chunks = []
        turn_chunks = []
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
                    speaking = False
                    speech_started_at = None
                    last_voice_at = None
                    voice_run = 0
                    prefix_chunks.clear()
                    turn_chunks.clear()
                    continue

                if self.args.local_vad:
                    now = time.monotonic()
                    rms = audioop.rms(chunk, 2)
                    is_voice = rms >= self.args.local_vad_rms_threshold

                    if not speaking:
                        prefix_chunks.append(chunk)
                        if len(prefix_chunks) > self.args.local_vad_prefix_chunks:
                            prefix_chunks.pop(0)
                        voice_run = voice_run + 1 if is_voice else 0
                        if voice_run < self.args.local_vad_start_chunks:
                            continue
                        speaking = True
                        speech_started_at = now
                        last_voice_at = now
                        print("[realtime] voix detectee locale", flush=True)
                        if self.args.text_bridge:
                            turn_chunks.extend(prefix_chunks)
                        else:
                            for prefix in prefix_chunks:
                                self.append_input_audio(prefix)
                                chunks_sent += 1
                        prefix_chunks.clear()
                    else:
                        if is_voice:
                            last_voice_at = now
                        voice_run = voice_run + 1 if is_voice else 0

                    if self.args.text_bridge:
                        turn_chunks.append(chunk)
                    else:
                        self.append_input_audio(chunk)
                        chunks_sent += 1

                    enough_speech = (
                        speech_started_at is not None
                        and now - speech_started_at
                        >= self.args.local_vad_min_speech_ms / 1000.0
                    )
                    enough_silence = (
                        last_voice_at is not None
                        and now - last_voice_at
                        >= self.args.local_vad_silence_ms / 1000.0
                    )
                    if enough_speech and enough_silence:
                        print("[realtime] fin de phrase locale", flush=True)
                        if self.args.text_bridge:
                            try:
                                text = self.transcribe_chunks(turn_chunks)
                            except Exception as exc:
                                print(f"[realtime] transcription failed: {exc}", flush=True)
                                text = ""
                            if text:
                                print(f"Vous: {text}", flush=True)
                                self.handle_user_text(text)
                                self.send_text_turn(text)
                            else:
                                print("[realtime] transcription vide ignoree", flush=True)
                        else:
                            self.commit_input_audio()
                        speaking = False
                        speech_started_at = None
                        last_voice_at = None
                        voice_run = 0
                        turn_chunks.clear()
                    continue

                self.append_input_audio(chunk)
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
    parser.add_argument("--provider", choices=("openai", "xai"), default="openai")
    parser.add_argument("--dark", action="store_true", help="use Dark Woody personality")
    parser.add_argument("--model")
    parser.add_argument("--voice")
    parser.add_argument("--device", default=DEFAULT_AUDIO_DEVICE)
    parser.add_argument("--rate", type=int, default=REALTIME_RATE)
    parser.add_argument("--capture-rate", type=int, default=REALTIME_CAPTURE_RATE)
    parser.add_argument("--capture-channels", type=int, default=REALTIME_CAPTURE_CHANNELS)
    parser.add_argument("--chunk-ms", type=int, default=REALTIME_CHUNK_MS)
    parser.add_argument("--silence-ms", type=int, default=REALTIME_SILENCE_MS)
    parser.add_argument("--vad-threshold", type=float)
    local_vad_group = parser.add_mutually_exclusive_group()
    local_vad_group.add_argument("--local-vad", dest="local_vad", action="store_true")
    local_vad_group.add_argument("--server-vad", dest="local_vad", action="store_false")
    parser.set_defaults(local_vad=None)
    text_bridge_group = parser.add_mutually_exclusive_group()
    text_bridge_group.add_argument("--text-bridge", dest="text_bridge", action="store_true")
    text_bridge_group.add_argument("--audio-bridge", dest="text_bridge", action="store_false")
    parser.set_defaults(text_bridge=None)
    parser.add_argument("--local-vad-rms-threshold", type=int, default=LOCAL_VAD_RMS_THRESHOLD)
    parser.add_argument("--local-vad-silence-ms", type=int, default=LOCAL_VAD_SILENCE_MS)
    parser.add_argument("--local-vad-min-speech-ms", type=int, default=LOCAL_VAD_MIN_SPEECH_MS)
    parser.add_argument("--local-vad-prefix-chunks", type=int, default=LOCAL_VAD_PREFIX_CHUNKS)
    parser.add_argument("--local-vad-start-chunks", type=int, default=LOCAL_VAD_START_CHUNKS)
    parser.add_argument("--echo-guard-ms", type=int, default=REALTIME_ECHO_GUARD_MS)
    parser.add_argument(
        "--playback-mute-seconds",
        type=float,
        default=REALTIME_PLAYBACK_MUTE_SECONDS,
    )
    parser.add_argument(
        "--playback-drain-timeout",
        type=float,
        default=REALTIME_PLAYBACK_DRAIN_TIMEOUT,
    )
    parser.add_argument("--max-output-tokens", type=int, default=450)
    parser.add_argument("--probe", action="store_true", help="connect, update session, then exit")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="print robot actions without moving")
    args = parser.parse_args()
    if args.model is None:
        args.model = XAI_REALTIME_MODEL if args.provider == "xai" else REALTIME_MODEL
    if args.voice is None:
        args.voice = XAI_REALTIME_VOICE if args.provider == "xai" else REALTIME_VOICE
    if args.vad_threshold is None:
        args.vad_threshold = (
            XAI_REALTIME_VAD_THRESHOLD
            if args.provider == "xai"
            else REALTIME_VAD_THRESHOLD
        )
    if args.local_vad is None:
        args.local_vad = XAI_LOCAL_VAD if args.provider == "xai" else False
    if args.text_bridge is None:
        args.text_bridge = XAI_TEXT_BRIDGE if args.provider == "xai" else False
    return args


def main():
    args = parse_args()
    app = RealtimeWoody(args)

    def handle_signal(signum, frame):
        app.close()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    app.connect()
    if app.pending_mode_switch == "dark":
        raise SystemExit(42)


if __name__ == "__main__":
    main()
