#!/usr/bin/env python3
"""Woody companion app for TonyPi.

Run on the robot from /home/pi/cosmo_robotics after deployment.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import unicodedata

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


APP_DIR = "/home/pi/cosmo_robotics"
WAKE_AUDIO_FILE = os.path.join(APP_DIR, "woody_wake.wav")
TURN_AUDIO_FILE = os.path.join(APP_DIR, "woody_turn.wav")
REPLY_AUDIO_FILE = os.path.join(APP_DIR, "woody_reply.mp3")

WAKE_PHRASE = "salut woody"
EXIT_PHRASES = {"stop", "arrete", "au revoir", "bonne nuit", "retourne dormir"}

LLM_MODEL = os.environ.get("WOODY_LLM_MODEL", "gpt-4o-mini")
TRANSCRIBE_MODEL = os.environ.get("WOODY_TRANSCRIBE_MODEL", "gpt-4o-transcribe")
TTS_MODEL = os.environ.get("WOODY_TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.environ.get("WOODY_TTS_VOICE", "alloy")

client = None


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
- Si l'utilisateur dit d'arreter, dormir, ou au revoir, mets "sleep": true.
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
    return WAKE_PHRASE in normalized or "salut woodie" in normalized


def get_client():
    global client
    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=llm_api_key, base_url=llm_base_url)
    return client


def record_audio(path, seconds):
    duration = max(1, int(round(seconds)))
    cmd = [
        "arecord",
        "-D",
        "hw:2,0",
        "-f",
        "S16_LE",
        "-r",
        "48000",
        "-c",
        "2",
        "-d",
        str(duration),
        path,
    ]
    subprocess.run(cmd, check=True)


def transcribe_audio(path):
    with open(path, "rb") as audio:
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

    subprocess.run(["python3", DANCE_SCRIPT, str(dance_index)], check=False)


def plan_turn(user_text, history):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history[-8:])
    messages.append({"role": "user", "content": user_text})

    response = get_client().chat.completions.create(
        model=LLM_MODEL,
        temperature=0.4,
        messages=messages,
    )
    content = response.choices[0].message.content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        print(f"[woody] invalid JSON from model: {content}")
        return {
            "reply": "Je t'ai entendu, mais j'ai mal compris la commande.",
            "actions": [],
            "dance_index": None,
            "sleep": False,
        }


def execute_plan(plan, dry_run=False):
    dance_index = plan.get("dance_index")
    if dance_index:
        run_dance(dance_index, dry_run=dry_run)

    for action in plan.get("actions", []):
        name = action.get("name")
        repeat = action.get("repeat", 1)
        run_action(name, repeat, dry_run=dry_run)


def companion_turn(user_text, history, speak_enabled=True, dry_run=False):
    normalized = normalize(user_text)
    if normalized in EXIT_PHRASES:
        plan = {"reply": "D'accord, je retourne en veille.", "actions": [], "sleep": True}
    else:
        plan = plan_turn(user_text, history)

    reply = plan.get("reply") or "D'accord."
    print(f"Woody: {reply}")
    speak(reply, enabled=speak_enabled)
    execute_plan(plan, dry_run=dry_run)

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
        print("[woody] listening for a command...")
        record_audio(TURN_AUDIO_FILE, args.turn_seconds)
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
    parser.add_argument("--speak", action="store_true", help="speak replies with TTS")
    parser.add_argument("--dry-run", action="store_true", help="do not run robot actions")
    parser.add_argument("--wake-seconds", type=float, default=2.5)
    parser.add_argument("--turn-seconds", type=float, default=5.0)
    args = parser.parse_args()

    os.makedirs(APP_DIR, exist_ok=True)

    if args.text:
        text_loop(args)
    else:
        software_wake_loop(args)


if __name__ == "__main__":
    main()
