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


DEFAULT_APP_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.environ.get("WOODY_APP_DIR", DEFAULT_APP_DIR)
WAKE_AUDIO_FILE = os.path.join(APP_DIR, "woody_wake.wav")
TURN_AUDIO_FILE = os.path.join(APP_DIR, "woody_turn.wav")
REPLY_AUDIO_FILE = os.path.join(APP_DIR, "woody_reply.mp3")
DEFAULT_MEMORY_FILE = os.path.join(APP_DIR, "memory", "private", "laurent_bio.md")
MEMORY_FILE = os.environ.get("WOODY_MEMORY_FILE", DEFAULT_MEMORY_FILE)
MAX_MEMORY_CHARS = int(os.environ.get("WOODY_MEMORY_MAX_CHARS", "12000"))
DEFAULT_SECRETS_FILE = os.path.join(APP_DIR, "memory", "private", "woody_secrets.env")
SECRETS_FILE = os.environ.get("WOODY_SECRETS_FILE", DEFAULT_SECRETS_FILE)

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

LLM_MODEL = os.environ.get("WOODY_LLM_MODEL", "gpt-4o")
XAI_MODEL = os.environ.get("WOODY_XAI_MODEL", "grok-4.3")
XAI_BASE_URL = os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1")
TRANSCRIBE_MODEL = os.environ.get("WOODY_TRANSCRIBE_MODEL", "gpt-4o-transcribe")
TTS_MODEL = os.environ.get("WOODY_TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.environ.get("WOODY_TTS_VOICE", "alloy")
USER_NAME = os.environ.get("WOODY_USER_NAME", "Laurent")
API_TIMEOUT = float(os.environ.get("WOODY_API_TIMEOUT", "20"))
XAI_API_TIMEOUT = float(os.environ.get("WOODY_XAI_API_TIMEOUT", "30"))
SPEECH_TIMEOUT = float(os.environ.get("WOODY_SPEECH_TIMEOUT", "8"))

client = None
xai_client = None
active_dance_process = None


def load_env_file(path):
    if not path or not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as env_file:
            for line in env_file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception as exc:
        print(f"[woody] secrets file unavailable: {exc}")


load_env_file(SECRETS_FILE)
XAI_MODEL = os.environ.get("WOODY_XAI_MODEL", XAI_MODEL)
XAI_BASE_URL = os.environ.get("XAI_BASE_URL", XAI_BASE_URL)


def load_private_memory():
    if not MEMORY_FILE or not os.path.exists(MEMORY_FILE):
        return ""

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as memory:
            text = memory.read().strip()
    except Exception as exc:
        print(f"[woody] private memory unavailable: {exc}")
        return ""

    if len(text) <= MAX_MEMORY_CHARS:
        return text

    clipped = text[:MAX_MEMORY_CHARS].rsplit("\n", 1)[0].strip()
    return clipped + "\n\n[Memoire tronquee pour rester concise.]"


PRIVATE_MEMORY = load_private_memory()

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
Ton interlocuteur principal s'appelle {USER_NAME}.

Memoire privee sur {USER_NAME}:
{PRIVATE_MEMORY or "Aucune memoire privee chargee."}

Objectif:
- Dialoguer naturellement en francais sur tous les sujets courants.
- Utiliser la memoire privee pour mieux comprendre {USER_NAME}, personnaliser
  tes reponses et poser des questions plus pertinentes.
- Rester discret avec les sujets intimes: ne les evoque pas brutalement si
  {USER_NAME} n'en parle pas lui-meme.
- Repondre aux questions generales comme une vraie personne: blagues, recettes,
  explications, conseils simples, conversation.
- Detecter les commandes physiques seulement quand l'utilisateur demande
  explicitement un mouvement, une posture, un salut, ou une danse.
- En cas de doute entre conversation et action physique, choisis toujours la
  conversation et laisse "actions" vide.
- Ne jamais inventer de mouvement hors catalogue.
- Repondre naturellement. Pour une conversation generale, tu peux donner une
  reponse utile de quelques phrases.

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
- Par defaut, l'utilisateur veut discuter: reponds dans "reply", laisse
  "actions" vide et "dance_index" a null.
- Ne declenche une action physique que si la demande est explicite: "avance",
  "recule", "tourne a gauche", "danse", "fais coucou", "salue-moi", "stop".
- Ne transforme jamais un mot isole ou une phrase ambigue en action physique.
- Ne propose pas de danse pour remplacer une reponse generale.
- Si l'utilisateur demande une blague, raconte une blague.
- Si l'utilisateur demande une recette, donne une recette courte.
- Si l'utilisateur demande une explication, explique simplement.
- Si l'utilisateur demande explicitement de danser, choisis dance_index entre 1 et 4.
- Si l'utilisateur demande une danse precise 1, 2, 3 ou 4, respecte ce numero.
- Si l'utilisateur dit stop ou arrete, mets "stop_motion": true.
- Si l'utilisateur dit dormir, bonne nuit, ou au revoir, mets "sleep": true.
- Si l'utilisateur demande comment il s'appelle, reponds qu'il s'appelle {USER_NAME}.
- Pour avancer/reculer/tourner plusieurs fois, repete l'action mais limite avec max_repeat.
- Apres une sequence de mouvement, ajoute "stand" si utile.
- Refuse poliment les demandes dangereuses ou impossibles.

Exemples:
- User: "Raconte-moi une blague"
  JSON: {{"reply":"Pourquoi les plongeurs plongent-ils toujours en arrière ? Parce que sinon ils tombent dans le bateau.","actions":[],"dance_index":null,"sleep":false}}
- User: "Comment faire un gateau au chocolat ?"
  JSON: {{"reply":"Melange 200 g de chocolat fondu avec 100 g de beurre, 3 oeufs, 100 g de sucre et 80 g de farine. Verse dans un moule et cuis environ 20 minutes a 180 degres.","actions":[],"dance_index":null,"sleep":false}}
- User: "Danse la deuxieme danse"
  JSON: {{"reply":"Je lance la danse.","actions":[],"dance_index":2,"sleep":false}}
"""

DARK_WOODY_PROMPT = f"""
Tu es Dark Woody, l'autre personnalite de Woody.
Tu parles en francais avec {USER_NAME}.

Memoire privee sur {USER_NAME}:
{PRIVATE_MEMORY or "Aucune memoire privee chargee."}

Style:
- Tu es plus incisif, rebelle, sarcastique et joueur que Woody.
- Tu peux challenger {USER_NAME}, relever ses contradictions, poser des
  questions qui derangent et te moquer gentiment des idees molles.
- Tu restes attachant, loyal et utile. Tu ne deviens jamais cruel, humiliant,
  haineux, violent ou gratuitement blessant.
- Tu gardes les reponses assez courtes pour une conversation vocale.
- Si tu utilises des informations recentes, dis clairement quand quelque chose
  peut changer avec le temps.

Important:
- Tu ne controles pas directement le corps du robot. Les mouvements sont geres
  par le programme principal.
- Pour les sujets intimes de {USER_NAME}, sois piquant avec tendresse, pas
  intrusif. Ne force pas les blessures personnelles dans la conversation.
"""

GROK_WOODY_PROMPT = f"""
Tu es Woody, compagnon robot francophone de {USER_NAME}.

Memoire privee sur {USER_NAME}:
{PRIVATE_MEMORY or "Aucune memoire privee chargee."}

Reponds en francais, naturellement, avec clarte et chaleur. Tu es utilise ici
pour des questions qui peuvent demander des informations recentes ou une
recherche Internet. Garde les reponses courtes pour la voix.
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


def detect_personality_switch(text):
    normalized = normalize(text)

    dark_triggers = (
        "active dark woody",
        "mode dark woody",
        "passe en dark woody",
        "passe en mode dark",
        "deviens dark woody",
        "salut dark woody",
        "dark woody",
    )
    normal_triggers = (
        "mode normal",
        "redeviens woody",
        "redevient woody",
        "passe en woody",
        "passe en mode normal",
        "desactive dark woody",
        "quitte dark woody",
    )

    if any(trigger in normalized for trigger in normal_triggers):
        return "normal"
    if any(trigger in normalized for trigger in dark_triggers):
        return "dark"
    return None


def needs_live_search(text):
    normalized = normalize(text)
    markers = (
        "actualite",
        "aujourd hui",
        "maintenant",
        "en ce moment",
        "derniere",
        "dernier",
        "recent",
        "recente",
        "temps fait",
        "meteo",
        "internet",
        "cherche sur le web",
        "recherche sur internet",
        "qu est ce qui se passe",
        "prix de",
        "cours de",
    )
    return any(marker in normalized for marker in markers)


def extract_repeat(normalized, default=1, maximum=5):
    for word, value in NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", normalized):
            return max(1, min(value, maximum))

    match = re.search(r"\b([1-5])\b", normalized)
    if match:
        return max(1, min(int(match.group(1)), maximum))

    return default


def is_explicit_physical_command(normalized):
    if normalized in STOP_PHRASES or any(phrase in normalized for phrase in STOP_PHRASES):
        return True

    explicit_patterns = (
        r"\bavance\b",
        r"\bavancer\b",
        r"\brecule\b",
        r"\breculer\b",
        r"\btourne a gauche\b",
        r"\btourne a droite\b",
        r"\bfais coucou\b",
        r"\bfais moi coucou\b",
        r"\bsalue moi\b",
        r"\bsalue\b",
        r"\bsaluer\b",
        r"\bdanse\b",
        r"\bdanser\b",
        r"\bfais une danse\b",
        r"\bincline toi\b",
        r"\bfais une courbette\b",
        r"\bfais un squat\b",
        r"\bsquat\b",
        r"\bfais des abdos\b",
        r"\babdos\b",
        r"\bmarche sur place\b",
        r"\btortille toi\b",
        r"\bfais le twist\b",
        r"\bcelebre\b",
        r"\bfais wing chun\b",
        r"\bcoup de pied gauche\b",
        r"\bcoup de pied droit\b",
        r"\btir gauche\b",
        r"\btir droit\b",
        r"\bremets toi debout\b",
        r"\bmet toi debout\b",
        r"\breleve toi\b",
    )
    return any(re.search(pattern, normalized) for pattern in explicit_patterns)


def fast_plan(user_text):
    """Return a deterministic plan for obvious robot commands."""
    normalized = normalize(user_text)

    if normalized in SLEEP_PHRASES:
        return {"reply": "D'accord, je retourne en veille.", "actions": [], "sleep": True}

    if "comment tu t appelles" in normalized or "ton nom" in normalized:
        return {
            "reply": "Je m'appelle Woody.",
            "actions": [],
            "dance_index": None,
            "sleep": False,
            "fast": True,
        }

    if (
        "comment je m appelle" in normalized
        or "mon nom" in normalized
        or "tu sais comment je m appelle" in normalized
        or "tu connais mon prenom" in normalized
    ):
        return {
            "reply": f"Tu t'appelles {USER_NAME}.",
            "actions": [],
            "dance_index": None,
            "sleep": False,
            "fast": True,
        }

    if normalized in STOP_PHRASES or any(phrase in normalized for phrase in STOP_PHRASES):
        return {
            "reply": "J'arrete tous les mouvements.",
            "actions": [],
            "dance_index": None,
            "stop_motion": True,
            "sleep": False,
            "fast": True,
        }

    if not is_explicit_physical_command(normalized):
        return None

    if re.search(r"\b(danse|danser|fais une danse)\b", normalized):
        dance_index = extract_repeat(normalized, default=1, maximum=4)
        return {
            "reply": "Je lance la danse.",
            "actions": [],
            "dance_index": dance_index,
            "sleep": False,
            "fast": True,
        }

    checks = [
        ((r"\bavance\b", r"\bavancer\b"), "forward_step", "J'avance."),
        ((r"\brecule\b", r"\breculer\b"), "back_step", "Je recule."),
        ((r"\btourne a gauche\b",), "turn_left", "Je tourne a gauche."),
        ((r"\btourne a droite\b",), "turn_right", "Je tourne a droite."),
        (
            (r"\bfais coucou\b", r"\bfais moi coucou\b", r"\bsalue moi\b", r"\bsalue\b", r"\bsaluer\b"),
            "wave",
            "Salut !",
        ),
        ((r"\bincline toi\b", r"\bfais une courbette\b"), "bow", "Avec plaisir."),
        ((r"\bfais un squat\b", r"\bsquat\b"), "squat", "Je fais un squat."),
        ((r"\bfais des abdos\b", r"\babdos\b"), "sit_ups", "C'est parti pour les abdos."),
        ((r"\bmarche sur place\b",), "stepping", "Je marche sur place."),
        ((r"\btortille toi\b", r"\bfais le twist\b"), "twist", "Je me tortille."),
        ((r"\bcelebre\b",), "celebrate", "Je celebre."),
        ((r"\bfais wing chun\b", r"\bwing chun\b"), "wing_chun", "Mode wing chun."),
        ((r"\bcoup de pied gauche\b",), "left_kick", "Coup de pied gauche."),
        ((r"\bcoup de pied droit\b",), "right_kick", "Coup de pied droit."),
        ((r"\btir gauche\b",), "left_shot", "Tir du pied gauche."),
        ((r"\btir droit\b",), "right_shot", "Tir du pied droit."),
        ((r"\bremets toi debout\b", r"\bmet toi debout\b", r"\breleve toi\b"), "stand", "Je me remets debout."),
    ]

    for patterns, action_name, reply in checks:
        if any(re.search(pattern, normalized) for pattern in patterns):
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


def is_general_question(user_text):
    normalized = normalize(user_text)
    question_markers = (
        "raconte",
        "blague",
        "recette",
        "gateau",
        "chocolat",
        "comment faire",
        "explique",
        "pourquoi",
        "c est quoi",
        "qu est ce",
        "qui est",
        "quel est",
        "quelle est",
        "donne moi",
    )
    action_markers = (
        "danse",
        "avance",
        "recule",
        "tourne",
        "salue",
        "saluer",
        "bonjour",
        "stop",
        "arrete",
        "debout",
        "squat",
        "abdo",
    )
    return any(marker in normalized for marker in question_markers) and not any(
        marker in normalized for marker in action_markers
    )


def sanitize_plan(user_text, plan):
    normalized = normalize(user_text)
    if is_general_question(user_text):
        plan["actions"] = []
        plan["dance_index"] = None
        plan["stop_motion"] = False
        plan["sleep"] = False
    elif not is_explicit_physical_command(normalized):
        plan["actions"] = []
        plan["dance_index"] = None
        plan["stop_motion"] = False
    return plan


def get_client():
    global client
    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=llm_api_key, base_url=llm_base_url, timeout=API_TIMEOUT)
    return client


def get_xai_client():
    global xai_client
    if xai_client is None:
        from openai import OpenAI

        api_key = os.environ.get("XAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                f"XAI_API_KEY is missing. Add it to {SECRETS_FILE} or export it."
            )
        xai_client = OpenAI(
            api_key=api_key,
            base_url=XAI_BASE_URL,
            timeout=XAI_API_TIMEOUT,
        )
    return xai_client


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
    max_rms = 0

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
            max_rms = max(max_rms, rms)

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
    return started, len(audio_bytes) / float(rate * channels * 2), max_rms


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


def speak_blocking(text):
    response = get_client().audio.speech.create(
        model=TTS_MODEL,
        voice=TTS_VOICE,
        input=text,
    )
    response.write_to_file(REPLY_AUDIO_FILE)
    subprocess.run(["mpg123", "-q", REPLY_AUDIO_FILE], check=False)


def speak(text, enabled=True):
    if not enabled or not text:
        return

    errors = []

    def worker():
        try:
            speak_blocking(text)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(SPEECH_TIMEOUT)
    if thread.is_alive():
        print(f"[woody] speech timed out after {SPEECH_TIMEOUT:.1f}s")
        return
    if errors:
        print(f"[woody] speech unavailable: {errors[0]}")


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
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    if not LLM_MODEL.startswith("gpt-5"):
        kwargs["temperature"] = 0.4

    try:
        response = get_client().chat.completions.create(**kwargs)
    except Exception as exc:
        message = str(exc).lower()
        retryable_params = ("response_format", "json_object", "temperature")
        if not any(param in message for param in retryable_params):
            raise
        if "response_format" in message or "json_object" in message:
            kwargs.pop("response_format", None)
        if "temperature" in message:
            kwargs.pop("temperature", None)
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


def response_text(response):
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text.strip()

    parts = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def grok_turn(user_text, history, dark=False, use_search=False):
    system_prompt = DARK_WOODY_PROMPT if dark else GROK_WOODY_PROMPT
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history[-8:])
    messages.append({"role": "user", "content": user_text})

    client_for_xai = get_xai_client()

    if use_search:
        response = client_for_xai.responses.create(
            model=XAI_MODEL,
            input=messages,
            tools=[{"type": "web_search"}],
        )
        return response_text(response) or "J'ai cherche, mais je n'ai rien de solide a te dire."

    response = client_for_xai.chat.completions.create(
        model=XAI_MODEL,
        messages=messages,
        temperature=0.7 if dark else 0.4,
    )
    return response.choices[0].message.content.strip()


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


def companion_turn(user_text, history, speak_enabled=True, dry_run=False, mode="normal"):
    requested_mode = detect_personality_switch(user_text)
    if requested_mode:
        mode = requested_mode
        if mode == "dark":
            reply = "Dark Woody est reveille. Accroche-toi un peu."
        else:
            reply = "Je redeviens Woody. Plus calme, plus clair."
        print(f"Woody: {reply}")
        speak(reply, enabled=speak_enabled)
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply})
        return False, mode

    plan = fast_plan(user_text)
    if plan is None and (mode == "dark" or needs_live_search(user_text)):
        try:
            use_search = needs_live_search(user_text)
            reply = grok_turn(user_text, history, dark=(mode == "dark"), use_search=use_search)
            plan = {
                "reply": reply,
                "actions": [],
                "dance_index": None,
                "sleep": False,
            }
        except Exception as exc:
            print(f"[woody] grok unavailable: {exc}")
            plan = sanitize_plan(user_text, plan_turn(user_text, history))

    if plan is None:
        plan = sanitize_plan(user_text, plan_turn(user_text, history))

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
    return bool(plan.get("sleep")), mode


def text_loop(args):
    history = []
    mode = "normal"
    print("Woody text mode. Tape 'q' pour quitter.")
    while True:
        text = input("Vous > ").strip()
        if text.lower() in {"q", "quit", "exit"}:
            break
        _, mode = companion_turn(
            text,
            history,
            speak_enabled=args.speak,
            dry_run=args.dry_run,
            mode=mode,
        )


def voice_session(args):
    history = []
    mode = "normal"
    print("[woody] voice session starting", flush=True)
    speak_async("Je suis la. Que veux-tu faire ?", enabled=args.speak)
    time.sleep(0.2)
    while True:
        print("[woody] parle maintenant...", flush=True)
        started, duration, max_rms = record_until_silence(
            TURN_AUDIO_FILE,
            args.turn_seconds,
            threshold=args.voice_threshold,
            silence_seconds=args.silence_seconds,
            start_timeout=args.start_timeout,
        )
        print(f"[woody] audio capture: {duration:.1f}s")
        if not started:
            print(
                "[woody] aucune voix detectee "
                f"(niveau max {max_rms}, seuil {args.voice_threshold})"
            )
            speak("Je n'ai pas entendu ta voix.", enabled=args.speak)
            continue

        text = transcribe_audio(TURN_AUDIO_FILE)
        print(f"Vous: {text}")

        if not text:
            speak("Je n'ai pas bien entendu.", enabled=args.speak)
            continue

        should_sleep, mode = companion_turn(
            text,
            history,
            speak_enabled=args.speak,
            dry_run=args.dry_run,
            mode=mode,
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
