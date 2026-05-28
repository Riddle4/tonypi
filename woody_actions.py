"""Capability catalog for the Woody companion app.

This file contains only references to existing TonyPi action groups. It does not
modify or generate vendor files on the robot.
"""

ACTION_GROUP_DIR = "/home/pi/TonyPi/ActionGroups"
DANCE_SCRIPT = "/home/pi/TonyPi/Functions/voice_interaction/sing_and_dance.py"

DANCE_ROUTINES = {
    1: {
        "label": "dance 1",
        "action_group": "dance1",
        "audio_file": "/home/pi/TonyPi/audio/16.wav",
    },
    2: {
        "label": "dance 2",
        "action_group": "dance2",
        "audio_file": "/home/pi/TonyPi/audio/17.wav",
    },
    3: {
        "label": "dance 3",
        "action_group": "dance3",
        "audio_file": "/home/pi/TonyPi/audio/18.wav",
    },
    4: {
        "label": "dance 4",
        "action_group": "dance4",
        "audio_file": "/home/pi/TonyPi/audio/19.wav",
    },
}

SAFE_ACTIONS = {
    "stand": {
        "label_fr": "se mettre debout",
        "action_group": "stand",
        "max_repeat": 1,
    },
    "stand_slow": {
        "label_fr": "se mettre debout doucement",
        "action_group": "stand_slow",
        "max_repeat": 1,
    },
    "forward_step": {
        "label_fr": "avancer d'un pas",
        "action_group": "go_forward_one_step",
        "max_repeat": 5,
        "movement": True,
    },
    "back_step": {
        "label_fr": "reculer d'un pas",
        "action_group": "back_one_step",
        "max_repeat": 5,
        "movement": True,
    },
    "turn_left": {
        "label_fr": "tourner a gauche",
        "action_group": "turn_left_fast",
        "max_repeat": 4,
        "movement": True,
    },
    "turn_right": {
        "label_fr": "tourner a droite",
        "action_group": "turn_right_fast",
        "max_repeat": 4,
        "movement": True,
    },
    "left_move": {
        "label_fr": "se deplacer a gauche",
        "action_group": "left_move_fast",
        "max_repeat": 4,
        "movement": True,
    },
    "right_move": {
        "label_fr": "se deplacer a droite",
        "action_group": "right_move_fast",
        "max_repeat": 4,
        "movement": True,
    },
    "wave": {
        "label_fr": "saluer",
        "action_group": "wave",
        "max_repeat": 3,
    },
    "bow": {
        "label_fr": "s'incliner",
        "action_group": "bow",
        "max_repeat": 3,
    },
    "squat": {
        "label_fr": "faire un squat",
        "action_group": "squat",
        "max_repeat": 3,
    },
    "sit_ups": {
        "label_fr": "faire des abdos",
        "action_group": "sit_ups",
        "max_repeat": 3,
    },
    "twist": {
        "label_fr": "se tortiller",
        "action_group": "twist",
        "max_repeat": 3,
    },
    "stepping": {
        "label_fr": "marcher sur place",
        "action_group": "stepping",
        "max_repeat": 3,
    },
    "left_kick": {
        "label_fr": "coup de pied gauche",
        "action_group": "left_kick",
        "max_repeat": 2,
        "movement": True,
    },
    "right_kick": {
        "label_fr": "coup de pied droit",
        "action_group": "right_kick",
        "max_repeat": 2,
        "movement": True,
    },
    "left_shot": {
        "label_fr": "tirer du pied gauche",
        "action_group": "left_shot_fast",
        "max_repeat": 2,
        "movement": True,
    },
    "right_shot": {
        "label_fr": "tirer du pied droit",
        "action_group": "right_shot_fast",
        "max_repeat": 2,
        "movement": True,
    },
    "wing_chun": {
        "label_fr": "faire du wing chun",
        "action_group": "wing_chun",
        "max_repeat": 2,
    },
    "celebrate": {
        "label_fr": "celebrer",
        "action_group": "chest",
        "max_repeat": 2,
    },
}

COMMAND_ALIASES_FR = {
    "avance": "forward_step",
    "avance d'un pas": "forward_step",
    "recule": "back_step",
    "tourne a gauche": "turn_left",
    "tourne a droite": "turn_right",
    "va a gauche": "left_move",
    "va a droite": "right_move",
    "salut": "wave",
    "dis bonjour": "wave",
    "incline-toi": "bow",
    "accroupis-toi": "squat",
    "fais des abdos": "sit_ups",
    "danse": "dance",
    "arrete": "stop",
}


def action_prompt_catalog():
    lines = []
    for key, action in SAFE_ACTIONS.items():
        lines.append(
            f"- {key}: {action['label_fr']} -> {action['action_group']}, "
            f"max_repeat={action['max_repeat']}"
        )
    lines.append("- dance: danser avec musique -> dance_index 1..4")
    return "\n".join(lines)
