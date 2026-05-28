# Cosmo Robotics TonyPi

This repository contains Cosmo Robotics programs for a HiWonder TonyPi robot.
The repository is the source of truth for our own application code. The robot's
vendor files stay on the Raspberry Pi and should not be edited directly unless a
change is deliberate, backed up, and documented.

## Current Robot

- Model reported on login: `TonyPiPro`
- Audio device profile reported on login: `WonderEchoPro`
- Robot IP used during discovery: `192.168.1.15`
- SSH user: `pi`
- OS: Debian GNU/Linux 12 (bookworm), aarch64
- Main robot service: `tonypi.service`
- Main vendor program: `/home/pi/TonyPi/TonyPi.py`
- Cosmo deployment directory: `/home/pi/cosmo_robotics`

See [docs/robot-inventory.md](docs/robot-inventory.md) for the full read-only
inventory captured from the robot.

## Working Rule

Develop locally in this repository, commit changes to Git, then deploy only the
Cosmo application files to `/home/pi/cosmo_robotics`.

Do not treat `/home/pi/TonyPi` as our application workspace. It is a vendor
runtime with local modifications and active systemd services.

## Useful Commands

Deploy the local repo to the robot:

```bash
./deploy.sh
```

Run the voice control program on the robot:

```bash
./run_robot.sh
```

Run a local parser loop on the robot after deployment:

```bash
ssh pi@192.168.1.15 'cd /home/pi/cosmo_robotics && python3 cosmo_text_to_robot.py'
```

## Project Files

- `cosmo_voice_to_robot.py`: records audio, transcribes French speech, parses a
  safe action plan, optionally speaks a reply, and executes TonyPi actions.
- `cosmo_text_to_robot.py`: text command loop for testing action parsing and
  execution without recording audio.
- `cosmo_command_parser.py`: command parsing only.
- `cosmo_action_test.py`: direct action group smoke test.
- `cosmo_asr_test.py`: audio recording and transcription smoke test.
- `woody_companion.py`: first French companion app with `Salut Woody` software
  wake phrase, dialogue planning, safe action execution, and dance support.
- `woody_actions.py`: Woody action and dance capability catalog.
- `deploy.sh`: rsync deployment to `/home/pi/cosmo_robotics`.
- `run_robot.sh`: SSH helper to run `cosmo_voice_to_robot.py` on the robot.

Files suffixed with `_WORKING_...` are snapshots kept from a known working robot
state. Prefer editing the unsuffixed files.

See [docs/woody-companion.md](docs/woody-companion.md) for the Woody design,
safe action catalog, and dance/audio mapping.
