# Woody Companion App

Woody is the planned French companion app for the TonyPi robot.

The goal is to let the user say `Salut Woody`, then talk naturally in French.
Woody should answer like a companion and execute safe robot commands when the
user asks for movement, gestures, or dances.

## Current Findings

The robot already has the pieces we need:

- main robot runtime: `/home/pi/TonyPi/TonyPi.py`
- action runner: `hiwonder.ActionGroupControl`
- JSON-RPC API: `/home/pi/TonyPi/RPCServer.py` on port `9030`
- speech package: `/home/pi/large_models/speech_pkg`
- OpenAI-compatible config: `/home/pi/large_models/config.py`
- Cosmo deployment directory: `/home/pi/cosmo_robotics`

The existing `WonderEchoPro` wake-word helper detects a hardware wake signal on
`/dev/ttyUSB0`, but the inspected class does not expose a custom wake phrase
setter. Because of that, Woody supports two voice modes:

- direct voice mode, which starts listening immediately;
- software wake mode, which records short audio windows, transcribes them in
  French, and starts the companion session when it hears `Salut Woody`.

Direct voice mode is recommended for first real-world tests because software
wake phrase detection can mis-transcribe short noisy clips.

## Dance Mapping

HiWonder already provides synchronized dance actions and music in:

`/home/pi/TonyPi/Functions/voice_interaction/sing_and_dance.py`

The mapping is:

| Dance index | Action group | Audio file |
| --- | --- | --- |
| `1` | `dance1` | `/home/pi/TonyPi/audio/16.wav` |
| `2` | `dance2` | `/home/pi/TonyPi/audio/17.wav` |
| `3` | `dance3` | `/home/pi/TonyPi/audio/18.wav` |
| `4` | `dance4` | `/home/pi/TonyPi/audio/19.wav` |

The Hiwonder RPC method `SingAndDance` uses the same script and accepts:

- `1` to `4`: start the selected dance
- `0`: stop the current dance and return to `stand`

The local Woody app calls the same script instead of reimplementing the timing.

## Initial Safe Action Catalog

The first Woody catalog intentionally exposes a conservative subset of existing
action groups:

| Woody command | TonyPi action group | Meaning |
| --- | --- | --- |
| `stand` | `stand` | stand |
| `stand_slow` | `stand_slow` | stand slowly |
| `forward_step` | `go_forward_one_step` | one step forward |
| `back_step` | `back_one_step` | one step back |
| `turn_left` | `turn_left_fast` | turn left |
| `turn_right` | `turn_right_fast` | turn right |
| `left_move` | `left_move_fast` | move left |
| `right_move` | `right_move_fast` | move right |
| `wave` | `wave` | greet |
| `bow` | `bow` | bow |
| `squat` | `squat` | squat |
| `sit_ups` | `sit_ups` | sit-ups |
| `twist` | `twist` | twist |
| `stepping` | `stepping` | step in place |
| `left_kick` | `left_kick` | left kick |
| `right_kick` | `right_kick` | right kick |
| `left_shot` | `left_shot_fast` | left football shot |
| `right_shot` | `right_shot_fast` | right football shot |
| `wing_chun` | `wing_chun` | wing chun |
| `celebrate` | `chest` | celebration |
| `dance` | `dance1`..`dance4` | dance with music |
| `stop` / `arrete tout` | stop motion | stop action groups and current dance |

More action groups exist, but they should be added after testing one by one.

## Program Files

- `woody_actions.py`: local action and dance catalog.
- `woody_companion.py`: first companion app.

## Private Memory

Woody can load a private memory file at startup:

`memory/private/laurent_bio.md`

That directory is ignored by Git so personal biographical content is not pushed
to GitHub. The normal `deploy.sh` command still copies it to the robot because
it deploys the working folder to `/home/pi/cosmo_robotics`.

To use another memory file without editing code:

```bash
WOODY_MEMORY_FILE=/home/pi/cosmo_robotics/memory/private/laurent_bio.md python3 woody_companion.py --speak
```

The memory is injected into Woody's system prompt as private context. It should
help Woody remember Laurent's background, preferences, family context, projects,
and sensitive topics, while staying discreet unless Laurent brings up those
topics himself.

## Running

Deploy first:

```bash
./deploy.sh
```

Text mode, safest first test:

```bash
ssh pi@192.168.1.15 'cd /home/pi/cosmo_robotics && python3 woody_companion.py --text --dry-run'
```

Text mode with real actions:

```bash
ssh pi@192.168.1.15 'cd /home/pi/cosmo_robotics && python3 woody_companion.py --text'
```

Wake phrase mode without robot actions:

```bash
ssh pi@192.168.1.15 'cd /home/pi/cosmo_robotics && python3 woody_companion.py --wake --dry-run'
```

Direct voice mode with spoken replies:

```bash
ssh pi@192.168.1.15 'cd /home/pi/cosmo_robotics && python3 woody_companion.py --speak'
```

If transcription clips the beginning or end of your sentence, increase the
recording window:

```bash
python3 woody_companion.py --speak --turn-seconds 9
```

Voice mode stops automatically after the end of speech. `--turn-seconds` is only
the maximum recording duration. If Woody cuts too early or waits too long, tune:

```bash
python3 woody_companion.py --speak --silence-seconds 1.1
```

If it does not detect your voice, lower the threshold:

```bash
python3 woody_companion.py --speak --voice-threshold 350
```

If it starts recording from room noise, raise the threshold:

```bash
python3 woody_companion.py --speak --voice-threshold 800
```

If the microphone device changes, override it without editing code:

```bash
WOODY_AUDIO_DEVICE=hw:2,0 python3 woody_companion.py --speak
```

Wake phrase mode with spoken replies:

```bash
ssh pi@192.168.1.15 'cd /home/pi/cosmo_robotics && python3 woody_companion.py --wake --speak'
```

If `Salut Woody` is repeatedly transcribed as a nearby phrase, add temporary
aliases:

```bash
WOODY_WAKE_ALIASES='salut woody,salut mon ami' python3 woody_companion.py --wake --speak
```

## Notes

Woody uses `gpt-4o` by default for dialogue and planning because it is more
responsive for live voice conversations. The model can be
changed without editing code:

```bash
WOODY_LLM_MODEL=gpt-4o-mini python3 woody_companion.py --text
```

For deeper but slower conversations, you can still run:

```bash
WOODY_LLM_MODEL=gpt-5.5 python3 woody_companion.py --text
```

OpenAI's current guidance recommends the Responses API for new agentic or
multi-turn workflows, but this implementation still uses the robot's existing
Chat Completions client style. A later version can migrate the planner to the
Responses API after basic robot behavior is validated.
