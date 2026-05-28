# Development Workflow

## Safety Model

The robot has two distinct areas:

- Cosmo application code: `/home/pi/cosmo_robotics`
- HiWonder/vendor robot runtime: `/home/pi/TonyPi`

Normal development must happen in this local Git repository and deploy only into
`/home/pi/cosmo_robotics`. The vendor runtime is already modified locally on the
robot and is required by active systemd services.

## Local-To-Robot Flow

1. Edit files locally in:

   ```text
   /Users/laurentmoreschi/_projets/cosmorobotics/tonypi
   ```

2. Commit changes locally and push to GitHub.

3. Deploy to the robot:

   ```bash
   ./deploy.sh
   ```

4. Run the main voice program:

   ```bash
   ./run_robot.sh
   ```

## Deployment Behavior

`deploy.sh` runs:

```bash
rsync -avz --exclude ".git" ./ pi@192.168.1.15:/home/pi/cosmo_robotics/
```

This copies the repository content to `/home/pi/cosmo_robotics` and excludes the
local Git metadata. It does not copy into `/home/pi/TonyPi`.

## Robot Runtime Dependencies

The Cosmo scripts rely on robot-side dependencies:

- `/home/pi/TonyPi` and `/home/pi/TonyPi/tonypi2025` on `sys.path`
- `hiwonder.ActionGroupControl`
- `/home/pi/large_models/config.py` for `llm_api_key` and `llm_base_url`
- microphone device `hw:2,0`
- `arecord` for audio capture
- `mpg123` for optional reply playback
- OpenAI-compatible API access through the configured client

## Testing Ladder

Use the smallest test that proves the layer you changed:

```bash
python3 cosmo_command_parser.py
```

Tests command parsing only.

```bash
python3 cosmo_text_to_robot.py
```

Tests parsing plus action execution, without microphone recording.

```bash
python3 cosmo_asr_test.py
```

Tests microphone recording and transcription.

```bash
python3 cosmo_voice_to_robot.py
```

Tests the full voice-to-action loop.

## Safe Action Policy

AI output must map to an explicit allowlist. The current allowlist intentionally
uses simple, known action groups:

- `go_forward_one_step`
- `back_one_step`
- `turn_left_fast`
- `turn_right_fast`
- `wave`
- `bow`
- `squat`
- `sit_ups`
- `stand`

Rules for future additions:

- Add only action groups confirmed to exist on the robot.
- Prefer short, stable, low-risk motions first.
- Cap repeats.
- End movement sequences with `stand` where appropriate.
- Never let the model emit arbitrary servo positions or arbitrary filenames.

## When A Vendor Change Is Needed

Avoid this path by default. If it becomes necessary:

1. Inspect without modifying:

   ```bash
   ssh pi@192.168.1.15 'git -C /home/pi/TonyPi status --short --branch'
   ```

2. Back up exact files:

   ```bash
   ssh pi@192.168.1.15 'mkdir -p /home/pi/backup_tonypi_$(date +%Y%m%d_%H%M)'
   ```

3. Stop services only if the change requires it:

   ```bash
   ssh pi@192.168.1.15 'sudo systemctl stop tonypi.service'
   ```

4. Make the smallest change and restart:

   ```bash
   ssh pi@192.168.1.15 'sudo systemctl start tonypi.service'
   ```

5. Verify:

   ```bash
   ssh pi@192.168.1.15 'systemctl status tonypi.service --no-pager -l'
   ```

Document the change in this repository afterward.

## Useful Read-Only Inspection Commands

```bash
ssh pi@192.168.1.15 'systemctl status tonypi.service --no-pager -l'
```

```bash
ssh pi@192.168.1.15 'ss -ltnup'
```

```bash
ssh pi@192.168.1.15 'find /home/pi/cosmo_robotics -maxdepth 2 -type f -printf "%p\n"'
```

```bash
ssh pi@192.168.1.15 'git -C /home/pi/TonyPi status --short --branch'
```
