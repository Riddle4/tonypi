import json
import sys
from openai import OpenAI

sys.path.append("/home/pi/large_models")
from config import llm_api_key, llm_base_url

client = OpenAI(
    api_key=llm_api_key,
    base_url=llm_base_url,
)

ALLOWED_ACTIONS = {
    "go_forward_one_step": "Avancer d'un pas",
    "back_one_step": "Reculer d'un pas",
    "turn_left_fast": "Tourner à gauche",
    "turn_right_fast": "Tourner à droite",
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
  "spoken_reply": "D'accord, j'exécute la commande."
}}

Rules:
- Do not invent actions.
- If the user asks to move forward by N steps, use go_forward_one_step repeated N times.
- Maximum repeat is 5.
- If the user asks for push-ups but no push-up action exists, use sit_ups or squat as the closest safe action.
- Always end with stand if the command includes physical movement.
- The spoken_reply must be short and natural in French.
"""

def parse_command(user_text: str) -> dict:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
    )

    content = response.choices[0].message.content.strip()
    return json.loads(content)

if __name__ == "__main__":
    while True:
        text = input("Commande > ").strip()
        if text.lower() in ["exit", "quit", "q"]:
            break

        result = parse_command(text)
        print(json.dumps(result, ensure_ascii=False, indent=2))