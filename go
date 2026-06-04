#!/usr/bin/env python3
"""Small terminal launcher for TonyPi/Woody actions."""

import argparse
import os
import statistics
import subprocess
import sys
import time
import unicodedata

from woody_actions import DANCE_ROUTINES, DANCE_SCRIPT, SAFE_ACTIONS

sys.path.append("/home/pi/TonyPi")
sys.path.append("/home/pi/TonyPi/tonypi2025")

try:
    import hiwonder.ActionGroupControl as AGC
except Exception:
    AGC = None


ALIASES = {
    "stand": "stand",
    "debout": "stand",
    "leve": "stand",
    "releve": "stand",
    "avance": "forward_step",
    "avancer": "forward_step",
    "forward": "forward_step",
    "recule": "back_step",
    "reculer": "back_step",
    "back": "back_step",
    "gauche": "turn_left",
    "left": "turn_left",
    "droite": "turn_right",
    "right": "turn_right",
    "salue": "wave",
    "salut": "wave",
    "coucou": "wave",
    "wave": "wave",
    "courbette": "bow",
    "incline": "bow",
    "bow": "bow",
    "squat": "squat",
    "abdos": "sit_ups",
    "abdo": "sit_ups",
    "situps": "sit_ups",
    "twist": "twist",
    "tortille": "twist",
    "marche": "stepping",
    "stepping": "stepping",
    "celebre": "celebrate",
    "bravo": "celebrate",
    "wingchun": "wing_chun",
    "wing-chun": "wing_chun",
    "kickgauche": "left_kick",
    "kickdroite": "right_kick",
    "tirgauche": "left_shot",
    "tirdroite": "right_shot",
}

DANCE_ALIASES = {"danse", "dance", "dancer"}
STOP_ALIASES = {"stop", "arrete", "arret", "immobile"}
BATTERY_ALIASES = {"bat", "batt", "battery", "batterie", "pile"}
WOODY_ALIASES = {"woody", "compagnon", "companion"}


def normalize(text):
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.replace("_", "").replace(" ", "").replace("'", "")


def clamp_repeat(action_name, repeat):
    maximum = SAFE_ACTIONS[action_name]["max_repeat"]
    return max(1, min(repeat, maximum))


def require_robot(dry_run):
    if dry_run:
        return
    if AGC is None:
        raise RuntimeError("hiwonder.ActionGroupControl is not available")


def stop_motion(dry_run=False):
    print("[go] stop")
    if dry_run:
        return

    for method_name in ("stopActionGroup", "stopAction"):
        method = getattr(AGC, method_name, None) if AGC is not None else None
        if method is not None:
            try:
                method()
            except Exception as exc:
                print(f"[go] {method_name} failed: {exc}")

    try:
        subprocess.run(["python3", DANCE_SCRIPT, "0"], check=False)
    except Exception as exc:
        print(f"[go] dance stop failed: {exc}")


def battery_percent(voltage):
    # TonyPi battery is typically a 3S Li-ion/LiPo pack.
    empty = 10.5
    full = 12.6
    return round(max(0.0, min(1.0, (voltage - empty) / (full - empty))) * 100)


def battery_status(percent):
    if percent >= 70:
        return "OK"
    if percent >= 35:
        return "moyen"
    if percent >= 15:
        return "bas"
    return "critique"


def read_battery(samples=8, timeout=5.0):
    try:
        from hiwonder.ros_robot_controller_sdk import Board
    except Exception as exc:
        raise RuntimeError(f"battery SDK unavailable: {exc}")

    board = Board()
    board.enable_reception(True)
    values = []
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline and len(values) < samples:
        value = board.get_battery()
        if value is not None:
            values.append(value)
        time.sleep(0.03)

    if not values:
        raise RuntimeError("battery value unavailable")

    millivolts = int(statistics.median(values))
    voltage = millivolts / 1000.0
    percent = battery_percent(voltage)
    return millivolts, voltage, percent, len(values)


def show_battery(dry_run=False):
    if dry_run:
        print("[go] battery: dry-run")
        return

    millivolts, voltage, percent, samples = read_battery()
    print(
        f"[go] batterie: {voltage:.2f} V ({millivolts} mV), "
        f"~{percent}% - {battery_status(percent)} "
        f"({samples} mesures)"
    )


def run_action(action_name, repeat=1, dry_run=False):
    if action_name not in SAFE_ACTIONS:
        raise ValueError(f"Unknown action: {action_name}")

    require_robot(dry_run)
    action_group = SAFE_ACTIONS[action_name]["action_group"]
    repeat = clamp_repeat(action_name, repeat)

    for index in range(repeat):
        print(f"[go] {action_name} -> {action_group} ({index + 1}/{repeat})")
        if not dry_run:
            AGC.runActionGroup(action_group)
            time.sleep(0.2)


def run_dance(index=1, dry_run=False):
    if index not in DANCE_ROUTINES:
        index = 1
    routine = DANCE_ROUTINES[index]
    print(f"[go] dance {index} -> {routine['action_group']} + {routine['audio_file']}")
    if not dry_run:
        subprocess.run(["python3", DANCE_SCRIPT, str(index)], check=False)


def run_woody(mode=None, dry_run=False):
    root = os.path.dirname(os.path.abspath(__file__))
    normalized_mode = normalize(mode or "")
    if normalized_mode in {"realtime", "rt", "live"}:
        realtime_script = os.path.join(root, "woody_realtime.py")
        dark_script = os.path.join(root, "woody_companion.py")
        while True:
            cmd = [sys.executable, realtime_script]
            if dry_run:
                cmd.append("--dry-run")
            print("[go] " + " ".join(cmd))
            if dry_run:
                return
            result = subprocess.run(cmd, check=False)
            if result.returncode != 42:
                return

            cmd = [
                sys.executable,
                dark_script,
                "--speak",
                "--voice-threshold",
                "450",
                "--start-mode",
                "dark",
                "--return-realtime-on-normal",
            ]
            print("[go] " + " ".join(cmd))
            result = subprocess.run(cmd, check=False)
            if result.returncode != 42:
                return
        return
    if normalized_mode in {"darkrealtime", "darkrt", "darklive", "grokrealtime"}:
        realtime_script = os.path.join(root, "woody_realtime.py")
        dark_script = os.path.join(root, "woody_companion.py")
        cmd = [
            sys.executable,
            dark_script,
            "--speak",
            "--voice-threshold",
            "450",
            "--start-mode",
            "dark",
            "--return-realtime-on-normal",
        ]
        print("[go] " + " ".join(cmd))
        if dry_run:
            return
        result = subprocess.run(cmd, check=False)
        if result.returncode == 42:
            cmd = [sys.executable, realtime_script]
            print("[go] " + " ".join(cmd))
            subprocess.run(cmd, check=False)
        return

    script = os.path.join(root, "woody_companion.py")
    cmd = [sys.executable, script]

    if normalized_mode in {"text", "texte"}:
        cmd.append("--text")
    elif normalized_mode in {"wake", "reveil"}:
        cmd.extend(["--wake", "--speak", "--voice-threshold", "450"])
    else:
        cmd.extend(["--speak", "--voice-threshold", "450"])

    print("[go] " + " ".join(cmd))
    if not dry_run:
        subprocess.run(cmd, check=False)


def list_commands():
    print("Actions:")
    for alias, action in sorted(ALIASES.items()):
        print(f"  {alias:<12} -> {action}")
    print("\nDanses:")
    print("  danse [1-4]")
    print("\nSecurite:")
    print("  stop")
    print("\nBatterie:")
    print("  bat")
    print("\nWoody:")
    print("  woody       -> lance Woody en mode voix")
    print("  woody realtime -> lance Woody en mode Realtime experimental")
    print("  woody darkrealtime -> lance Dark Woody non-Realtime avec voix gutturale")
    print("  woody text  -> lance Woody en mode texte")
    print("  woody wake  -> lance Woody en mode reveil")


def parse_repeat(value):
    try:
        return int(value)
    except Exception:
        return 1


def main():
    parser = argparse.ArgumentParser(description="Run TonyPi actions from the terminal")
    parser.add_argument("command", nargs="?", help="action alias, danse, stop, or list")
    parser.add_argument("value", nargs="?", help="repeat count or dance index")
    parser.add_argument("--dry-run", action="store_true", help="print without moving")
    args = parser.parse_args()

    if not args.command or normalize(args.command) in {"list", "liste", "help", "aide"}:
        list_commands()
        return

    command = normalize(args.command)

    if command in STOP_ALIASES:
        stop_motion(dry_run=args.dry_run)
        return

    if command in BATTERY_ALIASES:
        show_battery(dry_run=args.dry_run)
        return

    if command in WOODY_ALIASES:
        run_woody(mode=args.value, dry_run=args.dry_run)
        return

    if command in DANCE_ALIASES:
        run_dance(parse_repeat(args.value or "1"), dry_run=args.dry_run)
        return

    action_name = ALIASES.get(command)
    if not action_name:
        print(f"[go] commande inconnue: {args.command}")
        print("Essaie: ./go list")
        raise SystemExit(2)

    run_action(action_name, repeat=parse_repeat(args.value or "1"), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
