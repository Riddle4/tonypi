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

Woody only executes physical actions when the request is explicit. Ambiguous
phrases such as "bonjour", "a gauche", or "devant" are treated as conversation,
not robot commands.

In voice mode, Woody executes explicit physical actions immediately by default.
For safer tests, you can make Woody ask for confirmation before moving:

```bash
python3 woody_companion.py --speak --confirm-actions
```

When confirmation is enabled, say `oui`, `vas-y`, or `confirme` to execute. Say
`non`, `annule`, or stay silent to cancel.

## Program Files

- `woody_actions.py`: local action and dance catalog.
- `woody_companion.py`: first companion app.
- `go`: simple terminal launcher for robot actions.

## Terminal Action Launcher

For direct movement tests without voice or AI:

```bash
cd /home/pi/cosmo_robotics
./go salue
./go squat
./go danse 2
./go avance 2
./go bat
./go stop
./go woody
```

List available aliases:

```bash
./go list
```

Woody shortcuts:

```bash
./go woody       # voice companion mode
./go woody realtime # experimental low-latency Realtime mode
./go woody darkrealtime # experimental Dark Woody Realtime mode with Grok
./go woody text  # typed companion mode
./go woody wake  # software wake phrase mode
```

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

## Personalities and Grok

Woody has two conversational personalities:

- normal Woody: OpenAI `gpt-4o`, warm, structured, fast, and used by default;
- Dark Woody: xAI Grok, more incisive, sarcastic, rebellious, but still loyal
  and kind underneath.

Switch personality by saying:

```text
Active Dark Woody.
Redeviens Woody.
Passe en mode normal.
```

Questions that look time-sensitive, such as news, weather, recent events, web
research, current prices, or "today" questions, are routed to Grok with xAI
Web Search when an xAI key is available.

Add the xAI key in the private secrets file:

```bash
nano /home/pi/cosmo_robotics/memory/private/woody_secrets.env
```

Then add:

```bash
XAI_API_KEY=xai-your-key-here
```

This file is ignored by Git and loaded automatically when Woody starts. You can
also choose another Grok model without editing code:

```bash
WOODY_XAI_MODEL=grok-4.3 python3 woody_companion.py --speak
```

## Spoken voice

Woody uses OpenAI text-to-speech with `gpt-4o-mini-tts`. The default normal
voice is `shimmer`, with instructions asking for a natural French female voice
and a European French accent.

Dark Woody uses a separate default voice, `onyx`, with stronger instructions for
a native French delivery, less Anglo-American melody, and a deeper, hoarser,
more guttural male tone where the model can produce it.

You can test another built-in OpenAI voice without editing code:

```bash
WOODY_TTS_VOICE=nova python3 woody_companion.py --speak
```

You can test another voice only for Dark Woody:

```bash
WOODY_DARK_TTS_VOICE=ash python3 woody_companion.py --speak
```

You can also override the French voice direction:

```bash
WOODY_TTS_INSTRUCTIONS="Parle en francais naturel, voix de femme francaise, ton pose." python3 woody_companion.py --speak
WOODY_DARK_TTS_INSTRUCTIONS="Parle uniquement en francais de France, voix d'homme francais tres grave, rauque et gutturale, sans accent anglais, ton ironique et sombre." python3 woody_companion.py --speak
```

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
python3 woody_companion.py --speak --silence-seconds 0.6
```

Woody defaults to a fast voice loop: `--silence-seconds 0.35`,
`--start-timeout 4.0`, and `--chunk-ms 50`. If the room is noisy, increase
`--silence-seconds` slightly. If Woody waits too long after you stop speaking,
lower it carefully.

Woody streams text-to-speech by default, so audio playback can start while the
OpenAI speech response is still being generated. If the audio player behaves
badly on the robot, disable streaming for a test:

```bash
WOODY_TTS_STREAM=0 python3 woody_companion.py --speak
```

Spoken replies are allowed up to 30 seconds by default. If a long answer is cut
off, increase this guard:

```bash
WOODY_SPEECH_TIMEOUT=45 python3 woody_companion.py --speak
```

## Experimental Realtime Mode

The current stable mode is still `go woody`. For lower latency voice
conversation experiments, use:

```bash
./go woody realtime
```

This runs `woody_realtime.py`, a separate WebSocket Realtime client. It streams
24 kHz PCM16 microphone audio to OpenAI, lets server VAD detect turn endings,
and plays returned `response.output_audio.delta` chunks immediately through
`aplay`.

Probe the Realtime session without opening the microphone:

```bash
python3 woody_realtime.py --probe
```

The first Realtime version is conversation-only. Robot movement tools will be
added after the live voice path is stable.

Dark Woody can also run in experimental Realtime mode with xAI Grok Voice:

```bash
./go woody darkrealtime
```

This uses `XAI_API_KEY`, the `grok-voice-latest` model by default, and the xAI
Realtime WebSocket endpoint. You can override the model or voice:

```bash
WOODY_XAI_REALTIME_MODEL=grok-voice-think-fast-1.0 WOODY_XAI_REALTIME_VOICE=rex ./go woody darkrealtime
```

xAI/Grok uses a more sensitive VAD threshold by default (`0.22`). If Dark Woody
still does not hear you, lower it for a test:

```bash
WOODY_XAI_REALTIME_VAD_THRESHOLD=0.12 ./go woody darkrealtime
```

Dark Woody Realtime uses local VAD by default because xAI's server VAD can be
less reliable on the TonyPi microphone. If it still misses your voice, lower the
local RMS threshold:

```bash
python3 woody_realtime.py --provider xai --dark --local-vad-rms-threshold 650 --verbose
```

The default local threshold is `650`, and Dark Woody requires two consecutive
voice chunks before starting a turn. This helps catch quieter speech without
reacting to every short noise spike.

Dark Woody Realtime also uses a text bridge by default: OpenAI transcribes
Laurent's French speech first, then the clean text is sent to Grok Voice for the
Dark Woody response. This avoids xAI mishearing French phrases as English or
Turkish while still keeping Grok as the Dark Woody personality and voice.
The Realtime bridge uses a neutral transcription prompt so it does not bias
phrases toward the stable robot command examples.
It also includes a hint for news questions so "quelles sont les nouvelles du
jour" is not mistaken for "nouveau jour".

Realtime mode loads the same private memory as the stable Woody mode. Woody is
explicitly instructed that his name is Woody, that he is speaking with Laurent,
and that he can use Laurent's private memory when it is relevant without
reciting it unprompted.

TonyPi's USB microphone may reject direct 24 kHz mono capture. The Realtime
script therefore records the microphone in the known-good TonyPi format
`48000Hz/2ch`, then converts it to `24000Hz/mono` before streaming to OpenAI.
If Woody does not seem to hear you, run:

```bash
python3 woody_realtime.py --verbose
```

The `audio rms` value should rise clearly when you speak.

If Woody answers himself or chains replies too quickly, increase the echo guard.
It mutes microphone streaming while Woody's speaker is playing:

```bash
WOODY_REALTIME_ECHO_GUARD_MS=1300 ./go woody realtime
```

Realtime now runs half-duplex by default: while Woody is speaking, microphone
audio is not sent to OpenAI. When the log prints `[realtime] a toi`, Woody is
listening again.

If a long Realtime answer is cut off while Woody is still speaking, increase the
audio drain timeout:

```bash
WOODY_REALTIME_PLAYBACK_DRAIN_TIMEOUT=90 ./go woody realtime
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
