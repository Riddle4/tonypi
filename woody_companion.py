#!/usr/bin/env python3
"""Woody companion app for TonyPi.

Run on the robot from /home/pi/cosmo_robotics after deployment.
"""

import argparse
import array
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
import wave

from woody_actions import DANCE_ROUTINES, DANCE_SCRIPT, SAFE_ACTIONS, action_prompt_catalog

sys.path.append("/home/pi/large_models")
sys.path.append("/home/pi/TonyPi")
sys.path.append("/home/pi/TonyPi/tonypi2025")

try:
    from config import llm_api_key, llm_base_url
except Exception:
    llm_api_key = os.environ.get("OPENAI_API_KEY")
    llm_base_url = os.environ.get("OPENAI_BASE_URL")

try:
    import hiwonder.ActionGroupControl as AGC
except Exception:
    AGC = None


APP_DIR = os.environ.get("WOODY_APP_DIR", "/home/pi/cosmo_robotics")
WAKE_AUDIO_FILE = os.path.join(APP_DIR, "woody_wake.wav")
TURN_AUDIO_FILE = os.path.join(APP_DIR, "woody_turn.wav")
REPLY_AUDIO_FILE = os.path.join(APP_DIR, "woody_reply.mp3")

DEFAULT_AUDIO_DEVICE = os.environ.get("WOODY_AUDIO_DEVICE", "hw:2,0")
DEFAULT_AUDIO_RATE = int(os.environ.get("WOODY_AUDIO_RATE", "48000"))
DEFAULT_AUDIO_CHANNELS = int(os.environ.get("WOODY_AUDIO_CHANNELS", "2"))
DEFAULT_VOICE_THRESHOLD = int(os.environ.get("WOODY_VOICE_THRESHOLD", "500"))
WAKE_PHRASE = "salut woody"
DEFAULT_WAKE_ALIASES = (
    "salut woody",
    "salut woodie",
    "salut woudi",
    "salut woogie",
    "salut mon ami",
)
STOP_PHRASES = {"stop", "arrete", "arrete toi", "arrete tout", "immobile"}
SLEEP_PHRASES = {"au revoir", "bonne nuit", "retourne dormir"}
EXIT_PHRASES = STOP_PHRASES | SLEEP_PHRASES

LLM_MODEL = os.environ.get("WOODY_LLM_MODEL", "gpt-4o-mini")
TRANSCRIBE_MODEL = os.environ.get("WOODY_TRANSCRIBE_MODEL", "gpt-4o-transcribe")
TTS_MODEL = os.environ.get("WOODY_TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.environ.get("WOODY_TTS_VOICE", "alloy")

client = None
active_dance_process = None

TRANSCRIPTION_PROMPT = """
Transcris en francais une commande adressee a Woody, un petit robot compagnon.
Les phrases possibles incluent: salut Woody, avance d'un pas, recule, tourne a
gauche, tourne a droite, peux-tu me saluer, danse, danse la deuxieme danse,
comment vas-tu, raconte-moi quelque chose, au revoir.
Ignore les bruits de fond et ne traduis pas.
"""

NUMBER_WORDS = {
    "premier": 1,
    "premiere": 1,
    "un": 1,
    "une": 1,
    "deux": 2,
    "deuxieme": 2,
    "second": 2,
    "seconde": 2,
    "trois": 3,
    "troisieme": 3,
    "quatre": 4,
    "quatrieme": 4,
    "cinq": 5,
    "cinquieme": 5,
}


SYSTEM_PROMPT = f"""
Tu es Woody, un compagnon robot TonyPi chaleureux, curieux et francophone.

Objectif:
- Dialoguer naturellement en francais.
- Detecter les commandes physiques demandees par l'utilisateur.
- Ne jamais inventer de mouvement hors catalogue.
- Repondre avec une phrase courte et naturelle.

Catalogue de commandes autorisees:
{action_prompt_catalog()}

Format de sortie obligatoire: JSON strict, sans markdown.
Schema:
{{
  "reply": "reponse courte en francais",
  "actions": [
    {{"name": "forward_step", "repeat": 1}}
  ],
  "dance_index": null,
  "sleep": false
}}

Regles:
- Si l'utilisateur veut discuter, laisse "actions" vide et "dance_index" a null.
- Si l'utilisateur demande de danser, choisis dance_index entre 1 et 4.
- Si l'utilisateur demande une danse precise 1, 2, 3 ou 4, respecte ce numero.
- Si l'utilisateur dit stop ou arrete, mets "stop_motion": true.
- Si l'utilisateur dit dormir, bonne nuit, ou au revoir, mets "sleep": true.
- Pour avancer/reculer/tourner plusieurs fois, repete l'action mais limite avec max_repeat.
- Apres une sequence de mouvement, ajoute "stand" si utile.
- Refuse poliment les demandes dangereuses ou impossibles.
"""


def normalize(text):
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def contains_wake_phrase(text):
    normalized = normalize(text)
    aliases = os.environ.get("WOODY_WAKE_ALIASES")
    phrases = aliases.split(",") if aliases else DEFAULT_WAKE_ALIASES
    return any(normalize(phrase) in normalized for phrase in phrases)


def extract_repeat(normalized, default=1, maximum=5):
    for word, value in NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", normalized):
            return max(1, min(value, maximum))

    match = re.search(r"\b([1-5])\b", normalized)
    if match:
        return max(1, min(int(match.group(1)), maximum))

    return default


def fast_plan(user_text):
    """Return a deterministic plan for obvious robot commands."""
    normalized = normalize(user_text)

    if normalized in SLEEP_PHRASES:
        return {"reply": "D'accord, je retourne en veille.", "actions": [], "sleep": True}

    if normalized in STOP_PHRASES or any(phrase in normalized for phrase in STOP_PHRASES):
        return {
            "reply": "J'arrete tous les mouvements.",
            "actions": [],
            "dance_index": None,
            "stop_motion": True,
            "sleep": False,
            "fast": True,
        }

    if "danse" in normalized or "dancer" in normalized:
        dance_index = extract_repeat(normalized, default=1, maximum=4)
        return {
            "reply": "Je lance la danse.",
            "actions": [],
            "dance_index": dance_index,
            "sleep": False,
            "fast": True,
        }

    checks = [
        (("avance", "avancer", "devant"), "forward_step", "J'avance."),
        (("recule", "recul", "arriere", "derriere"), "back_step", "Je recule."),
        (("tourne a gauche", "gauche"), "turn_left", "Je tourne a gauche."),
        (("tourne a droite", "droite"), "turn_right", "Je tourne a droite."),
        (("salue", "saluer", "bonjour", "coucou"), "wave", "Salut !"),
        (("incline", "courbette"), "bow", "Avec plaisir."),
        (("squat", "accroup"), "squat", "Je fais un squat."),
        (("abdo", "abdos"), "sit_ups", "C'est parti pour les abdos."),
        (("marche sur place", "sur place"), "stepping", "Je marche sur place."),
        (("tortille", "twist"), "twist", "Je me tortille."),
        (("celebre", "celebration", "bravo"), "celebrate", "Je celebre."),
        (("wing chun",), "wing_chun", "Mode wing chun."),
        (("coup de pied gauche", "pied gauche"), "left_kick", "Coup de pied gauche."),
        (("coup de pied droit", "pied droit"), "right_kick", "Coup de pied droit."),
        (("tire gauche", "tir gauche"), "left_shot", "Tir du pied gauche."),
        (("tire droit", "tir droit"), "right_shot", "Tir du pied droit."),
        (("debout", "releve", "relever"), "stand", "Je me remets debout."),
    ]

    for triggers, action_name, reply in checks:
        if any(trigger in normalized for trigger in triggers):
            repeat = extract_repeat(
                normalized,
                default=1,
                maximum=SAFE_ACTIONS[action_name]["max_repeat"],
            )
            actions = [{"name": action_name, "repeat": repeat}]
            if SAFE_ACTIONS[action_name].get("movement") and action_name != "stand":
                actions.append({"name": "stand", "repeat": 1})
            return {
                "reply": reply,
                "actions": actions,
                "dance_index": None,
                "sleep": False,
                "fast": True,
            }

    return None


def get_client():
    global client
    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=llm_api_key, base_url=llm_base_url)
    return client


def record_audio(path, seconds, device=DEFAULT_AUDIO_DEVICE, rate=DEFAULT_AUDIO_RATE):
    duration = max(1, int(round(seconds)))
    cmd = [
        "arecord",
        "-D",
        device,
        "-f",
        "S16_LE",
        "-r",
        str(rate),
        "-c",
        "2",
        "-d",
        str(duration),
        path,
    ]
    subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)


def write_wav(path, audio_bytes, rate=DEFAULT_AUDIO_RATE, channels=DEFAULT_AUDIO_CHANNELS):
    with wave.open(path, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(audio_bytes)


def rms_pcm16(audio_bytes):
    if not audio_bytes:
        return 0
    samples = array.array("h")
    samples.frombytes(audio_bytes)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return 0
    square_sum = sum(sample * sample for sample in samples)
    return int(math.sqrt(square_sum / len(samples)))


def record_until_silence(
    path,
    max_seconds,
    device=DEFAULT_AUDIO_DEVICE,
    rate=DEFAULT_AUDIO_RATE,
    channels=DEFAULT_AUDIO_CHANNELS,
    threshold=DEFAULT_VOICE_THRESHOLD,
    silence_seconds=0.8,
    start_timeout=6.0,
    chunk_ms=100,
):
    """Record until speech is followed by a short silence."""
    chunk_frames = max(1, int(rate * chunk_ms / 1000))
    chunk_bytes = chunk_frames * channels * 2
    cmd = [
        "arecord",
        "-D",
        device,
        "-f",
        "S16_LE",
        "-r",
        str(rate),
        "-c",
        str(channels),
        "-t",
        "raw",
        "-q",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    chunks = []
    started = False
    start_time = time.monotonic()
    speech_start = None
    last_voice = None

    try:
        while True:
            if proc.stdout is None:
                break

            chunk = proc.stdout.read(chunk_bytes)
            if not chunk:
                break

            now = time.monotonic()
            chunks.append(chunk)
            rms = rms_pcm16(chunk)

            if rms >= threshold:
                if not started:
                    started = True
                    speech_start = now
                    print("[woody] voix detectee")
                last_voice = now

            elapsed = now - start_time
            if started and last_voice is not None:
                enough_voice = speech_start is None or now - speech_start >= 0.35
                if enough_voice and now - last_voice >= silence_seconds:
                    break

            if not started and elapsed >= start_timeout:
                break

            if elapsed >= max_seconds:
                break
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()

    audio_bytes = b"".join(chunks)
    write_wav(path, audio_bytes, rate=rate, channels=channels)
    return started, len(audio_bytes) / float(rate * channels * 2)


def transcribe_audio(path):
    with open(path, "rb") as audio:
        try:
            transcript = get_client().audio.transcriptions.create(
                model=TRANSCRIBE_MODEL,
                file=audio,
                language="fr",
                prompt=TRANSCRIPTION_PROMPT,
            )
        except TypeError:
            audio.seek(0)
            transcript = get_client().audio.transcriptions.create(
                model=TRANSCRIBE_MODEL,
                file=audio,
                language="fr",
            )
    return transcript.text.strip()


def speak(text, enabled=True):
    if not enabled or not text:
        return

    response = get_client().audio.speech.create(
        model=TTS_MODEL,
        voice=TTS_VOICE,
        input=text,
    )
    response.write_to_file(REPLY_AUDIO_FILE)
    subprocess.run(["mpg123", "-q", REPLY_AUDIO_FILE], check=False)


def speak_async(text, enabled=True):
    if not enabled or not text:
        return None
    thread = threading.Thread(target=speak, args=(text, enabled), daemon=True)
    thread.start()
    return thread


def stop_all_motion(dry_run=False):
    global active_dance_process
    print("[woody] stop all motion")

    if dry_run:
        return

    proc = active_dance_process
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=1)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    active_dance_process = None

    if AGC is not None:
        for method_name in ("stopActionGroup", "stopAction"):
            method = getattr(AGC, method_name, None)
            if method is not None:
                try:
                    method()
                except Exception as exc:
                    print(f"[woody] {method_name} failed: {exc}")


def clamp_repeat(action_name, repeat):
    try:
        repeat = int(repeat)
    except Exception:
        repeat = 1

    max_repeat = SAFE_ACTIONS[action_name]["max_repeat"]
    return max(1, min(repeat, max_repeat))


def run_action(action_name, repeat=1, dry_run=False):
    if action_name not in SAFE_ACTIONS:
        print(f"[woody] refused unknown action: {action_name}")
        return

    action_group = SAFE_ACTIONS[action_name]["action_group"]
    repeat = clamp_repeat(action_name, repeat)

    for index in range(repeat):
        print(f"[woody] action {action_name} -> {action_group} ({index + 1}/{repeat})")
        if dry_run:
            continue
        if AGC is None:
            raise RuntimeError("hiwonder.ActionGroupControl is not available")
        AGC.runActionGroup(action_group)
        time.sleep(0.2)


def run_dance(dance_index, dry_run=False):
    global active_dance_process
    try:
        dance_index = int(dance_index)
    except Exception:
        dance_index = 1

    if dance_index not in DANCE_ROUTINES:
        dance_index = 1

    routine = DANCE_ROUTINES[dance_index]
    print(
        "[woody] dance "
        f"{dance_index} -> {routine['action_group']} + {routine['audio_file']}"
    )

    if dry_run:
        return

    stop_all_motion(dry_run=False)
    active_dance_process = subprocess.Popen(["python3", DANCE_SCRIPT, str(dance_index)])
    print("[woody] dance started in background; say stop to interrupt it")


def plan_turn(user_text, history):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history[-8:])
    messages.append({"role": "user", "content": user_text})

    kwargs = {
        "model": LLM_MODEL,
        "temperature": 0.4,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    try:
        response = get_client().chat.completions.create(**kwargs)
    except Exception as exc:
        message = str(exc).lower()
        if "response_format" not in message and "json_object" not in message:
            raise
        kwargs.pop("response_format", None)
        response = get_client().chat.completions.create(**kwargs)

    content = response.choices[0].message.content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        embedded = re.search(r"\{.*\}", content, re.DOTALL)
        if embedded:
            try:
                return json.loads(embedded.group(0))
            except json.JSONDecodeError:
                pass
        print(f"[woody] invalid JSON from model: {content}")
        return {
            "reply": content or "Je t'ai entendu, mais j'ai mal compris la commande.",
            "actions": [],
            "dance_index": None,
            "sleep": False,
        }


def execute_plan(plan, dry_run=False):
    if plan.get("stop_motion"):
        stop_all_motion(dry_run=dry_run)
        return

    dance_index = plan.get("dance_index")
    if dance_index:
        run_dance(dance_index, dry_run=dry_run)

    for action in plan.get("actions", []):
        name = action.get("name")
        repeat = action.get("repeat", 1)
        run_action(name, repeat, dry_run=dry_run)


def companion_turn(user_text, history, speak_enabled=True, dry_run=False):
    plan = fast_plan(user_text) or plan_turn(user_text, history)

    reply = plan.get("reply") or "D'accord."
    print(f"Woody: {reply}")

    has_physical_action = bool(
        plan.get("stop_motion") or plan.get("dance_index") or plan.get("actions")
    )
    if has_physical_action:
        voice_thread = speak_async(reply, enabled=speak_enabled)
        execute_plan(plan, dry_run=dry_run)
        if voice_thread:
            voice_thread.join()
    else:
        speak(reply, enabled=speak_enabled)

    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": reply})
    return bool(plan.get("sleep"))


def text_loop(args):
    history = []
    print("Woody text mode. Tape 'q' pour quitter.")
    while True:
        text = input("Vous > ").strip()
        if text.lower() in {"q", "quit", "exit"}:
            break
        companion_turn(text, history, speak_enabled=args.speak, dry_run=args.dry_run)


def voice_session(args):
    history = []
    speak("Je suis la. Que veux-tu faire ?", enabled=args.speak)
    while True:
        print("[woody] parle maintenant...")
        started, duration = record_until_silence(
            TURN_AUDIO_FILE,
            args.turn_seconds,
            threshold=args.voice_threshold,
            silence_seconds=args.silence_seconds,
            start_timeout=args.start_timeout,
        )
        print(f"[woody] audio capture: {duration:.1f}s")
        if not started:
            print("[woody] aucune voix detectee")
            speak("Je n'ai pas entendu ta voix.", enabled=args.speak)
            continue

        text = transcribe_audio(TURN_AUDIO_FILE)
        print(f"Vous: {text}")

        if not text:
            speak("Je n'ai pas bien entendu.", enabled=args.speak)
            continue

        should_sleep = companion_turn(
            text,
            history,
            speak_enabled=args.speak,
            dry_run=args.dry_run,
        )
        if should_sleep:
            break


def software_wake_loop(args):
    print('Woody wake mode. Dis "Salut Woody" pour demarrer.')
    print("Si la detection rate trop souvent, lance: python3 woody_companion.py --voice --speak")
    while True:
        try:
            record_audio(WAKE_AUDIO_FILE, args.wake_seconds)
            text = transcribe_audio(WAKE_AUDIO_FILE)
            print(f"[woody] wake check: {text}")
            if contains_wake_phrase(text):
                speak("Salut, je suis Woody.", enabled=args.speak)
                voice_session(args)
                print('[woody] back to wake mode. Dis "Salut Woody".')
        except KeyboardInterrupt:
            print("\n[woody] bye")
            break
        except Exception as exc:
            print(f"[woody] wake loop error: {exc}")
            time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="Woody companion app for TonyPi")
    parser.add_argument("--text", action="store_true", help="use typed input")
    parser.add_argument("--voice", action="store_true", help="start voice session immediately")
    parser.add_argument("--wake", action="store_true", help="wait for the software wake phrase")
    parser.add_argument("--speak", action="store_true", help="speak replies with TTS")
    parser.add_argument("--dry-run", action="store_true", help="do not run robot actions")
    parser.add_argument("--wake-seconds", type=float, default=4.0)
    parser.add_argument("--turn-seconds", type=float, default=10.0)
    parser.add_argument("--silence-seconds", type=float, default=0.8)
    parser.add_argument("--start-timeout", type=float, default=6.0)
    parser.add_argument("--voice-threshold", type=int, default=DEFAULT_VOICE_THRESHOLD)
    args = parser.parse_args()

    os.makedirs(APP_DIR, exist_ok=True)

    if args.text:
        text_loop(args)
    elif args.wake:
        software_wake_loop(args)
    else:
        voice_session(args)


if __name__ == "__main__":
    main()
