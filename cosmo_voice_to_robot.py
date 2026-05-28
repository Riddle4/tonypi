import json
import subprocess
import sys
import time
from openai import OpenAI

# === CONFIG OPENAI EXISTANTE HIWONDER ===
sys.path.append("/home/pi/large_models")
from config import llm_api_key, llm_base_url

# === LIBRAIRIES TONYPI ===
sys.path.append("/home/pi/TonyPi")
sys.path.append("/home/pi/TonyPi/tonypi2025")

import hiwonder.ActionGroupControl as AGC

client = OpenAI(
    api_key=llm_api_key,
    base_url=llm_base_url,
)

AUDIO_FILE = "/home/pi/cosmo_robotics/recording.wav"
REPLY_AUDIO_FILE = "/home/pi/cosmo_robotics/reply.mp3"

# Actions autorisees uniquement.
# On ne laisse jamais l'IA inventer des mouvements arbitraires.
ALLOWED_ACTIONS = {
    "go_forward_one_step": "Avancer d'un pas",
    "back_one_step": "Reculer d'un pas",
    "turn_left_fast": "Tourner a gauche",
    "turn_right_fast": "Tourner a droite",
    "wave": "Saluer",
    "bow": "S'incliner",
    "squat": "S'accroupir",
    "sit_ups": "Faire des abdos",
    "stand": "Se remettre debout",
}

SYSTEM_PROMPT = f"""
You convert French or English voice commands into safe TonyPi robot action commands.

You must only use these allowed actions:
{json.dumps(ALLOWED_ACTIONS, ensure_ascii=False, indent=2)}

Return only valid JSON in this exact format:
{{
  "commands": [
    {{"action": "go_forward_one_step", "repeat": 1}},
    {{"action": "wave", "repeat": 1}}
  ],
  "spoken_reply": "D'accord, j'execute la commande."
}}

Rules:
- Do not invent actions.
- If the user asks to move forward by N steps, use go_forward_one_step repeated N times.
- Maximum repeat is 5.
- If the user asks for push-ups but no push-up action exists, use sit_ups or squat as the closest safe action.
- Always end with stand if the command includes physical movement.
- The spoken_reply must be short and natural in French.
- Avoid accented characters in spoken_reply for now.
- If the command is unclear, return an empty commands list and explain briefly in spoken_reply.
"""

def record_audio(seconds=5):
    print(f"\nEnregistrement pendant {seconds} secondes...")
    print("Parle maintenant.")

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
    print("Enregistrement termine.")

def transcribe_audio():
    print("Transcription OpenAI...")

    with open(AUDIO_FILE, "rb") as audio:
        transcript = client.audio.transcriptions.create(
            model="gpt-4o-transcribe",
            file=audio,
            language="fr",
        )

    text = transcript.text.strip()
    return text

def parse_command(user_text: str) -> dict:
    print("Interpretation de la commande...")

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
    )

    content = response.choices[0].message.content.strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        print("Erreur: la reponse IA n'est pas un JSON valide.")
        print(content)
        return {
            "commands": [],
            "spoken_reply": "Je n'ai pas compris la commande."
        }

def speak_text(text: str):
    if not text:
        return

    print("Generation de la voix du robot...")

    response = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice="alloy",
        input=text,
    )

    response.write_to_file(REPLY_AUDIO_FILE)

    print("Lecture audio...")
    subprocess.run(["mpg123", "-q", REPLY_AUDIO_FILE], check=False)

def run_action(action_name: str, repeat: int = 1):
    if action_name not in ALLOWED_ACTIONS:
        print(f"Action refusee: {action_name}")
        return

    try:
        repeat = int(repeat)
    except Exception:
        repeat = 1

    repeat = max(1, min(repeat, 5))

    for i in range(repeat):
        print(f"Action: {action_name} ({i+1}/{repeat})")
        AGC.runAction(action_name)
        time.sleep(0.3)

def execute_commands(commands):
    if not commands:
        print("Aucune action a executer.")
        return

    for command in commands:
        action = command.get("action")
        repeat = command.get("repeat", 1)
        run_action(action, repeat)

def main():
    print("=== Cosmo Voice to Robot ===")
    print("Appuie sur Entree pour enregistrer une commande vocale.")
    print("Tape q puis Entree pour quitter.\n")

    while True:
        user_input = input("Pret ? [Entree/q] ").strip().lower()

        if user_input in ["q", "quit", "exit"]:
            print("Fin.")
            break

        try:
            record_audio(seconds=5)
            text = transcribe_audio()

            print("\nTexte reconnu:")
            print(text)

            result = parse_command(text)

            print("\nCommandes interpretees:")
            print(json.dumps(result, ensure_ascii=False, indent=2))

            spoken_reply = result.get("spoken_reply", "")
            if spoken_reply:
                print("\nReponse robot:")
                print(spoken_reply)

            confirm = input("\nExecuter ? [y/N] ").strip().lower()

            if confirm == "y":
                if spoken_reply:
                    speak_text(spoken_reply)
                execute_commands(result.get("commands", []))
            else:
                print("Commande annulee.")

        except KeyboardInterrupt:
            print("\nInterrompu.")
            break
        except Exception as e:
            print("Erreur:")
            print(e)

if __name__ == "__main__":
    main()