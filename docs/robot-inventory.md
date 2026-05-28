# TonyPi Robot Inventory

Captured read-only over SSH from `pi@192.168.1.15`.

## System

- Hostname: `raspberrypi`
- User inspected: `pi`
- Home directory: `/home/pi`
- Kernel: `Linux raspberrypi 6.6.74+rpt-rpi-2712`
- Architecture: `aarch64`
- OS: Debian GNU/Linux 12 (bookworm)
- Python: `Python 3.11.2`
- Pip: `pip 23.0.1`
- Root filesystem: `/dev/mmcblk0p2`, 28 GB total, about 19 GB used

Login banner reports:

- Machine: `TonyPiPro`
- Mic type: `WonderEchoPro`
- ASR language: `English`
- Version: `V2.0`, dated `2025-12-18`

## Important Directories

### `/home/pi/TonyPi`

Main HiWonder TonyPi runtime. This is the vendor robot tree and the active
systemd service entrypoint.

Notable files and directories:

- `TonyPi.py`: main process started by `tonypi.service`.
- `RPCServer.py`: JSON-RPC API server for robot control.
- `MjpgServer.py`: camera/MJPG server.
- `Joystick.py`: joystick service program.
- `ActionGroups/`: action group `.d6a` files such as `stand`, `wave`,
  `go_forward`, `turn_left`, `turn_right`, etc.
- `Functions/`: high-level robot behaviors, vision functions, agent functions,
  and AI demos.
- `HiwonderSDK/`: local Python SDK used by the robot programs.
- `lab_config.yaml` and `servo_config.yaml`: robot calibration/config files.

This directory is a Git repository but has many local modifications and untracked
files. Treat it as vendor state on the robot, not as the Cosmo application repo.

### `/home/pi/cosmo_robotics`

Cosmo application deployment directory. This is the correct target for our code.

Observed files:

- `cosmo_action_test.py`
- `cosmo_asr_test.py`
- `cosmo_command_parser.py`
- `cosmo_text_to_robot.py`
- `cosmo_voice_to_robot.py`
- known-good snapshot files suffixed with `_WORKING_20260529_0350.py`
- generated runtime files such as `recording.wav` and `reply.mp3`

### `/home/pi/large_models`

HiWonder large-model examples and configuration. The Cosmo scripts import
`llm_api_key` and `llm_base_url` from `/home/pi/large_models/config.py`.

### `/home/pi/hiwonder-toolbox`

HiWonder helper services and scripts:

- `button_scan.py`
- `find_device.py`
- `remote.py`
- `wifi.py`
- matching `.service` files

### `/home/pi/embodied_intelligence`

HiWonder embodied intelligence and multimodal model course code. It is also a
Git repository with local modifications.

### Other Supporting Directories

- `/home/pi/board_demo`: board-level servo, buzzer, IMU, TTS, and ASR demos.
- `/home/pi/servo_tool`: servo control GUI/tooling.
- `/home/pi/LAB_Tool`: color threshold tooling.
- `/home/pi/TonyPi_PC_Software`: PC control software.
- `/home/pi/third_party`: bundled third-party projects including `mjpg-streamer`,
  `yolov5`, `create_ap`, and `neovim`.

## Running Services

Important active services:

- `tonypi.service`: main robot runtime.
- `joystick.service`: PS2/joystick control.
- `multi_control_client.service`: multi-control client.
- `multi_control_server.service`: multi-control server.
- `remote.service`: HiWonder remote helper.
- `button_scan.service`: button scan helper.
- `find_device.service`: device discovery helper.
- `wifi.service`: Wi-Fi helper.
- `ssh.service`: SSH access.
- `wayvnc.service`: VNC server.

`tonypi.service` definition:

```ini
[Service]
Type=simple
User=pi
Restart=always
RestartSec=5
ExecStart=/bin/python3 /home/pi/TonyPi/TonyPi.py
StandardOutput=journal
StandardError=journal
Environment=XDG_RUNTIME_DIR=/run/user/1000
Environment=AUDIODEV=hw:2,0
ExecStartPre=/bin/sleep 5
```

## Listening Ports

Observed listening ports:

- `22/tcp`: SSH
- `5900/tcp`: VNC
- `8080/tcp`: Python process from `TonyPi.py`, likely MJPG/camera stream
- `9030/tcp`: Python process from `TonyPi.py`, JSON-RPC server
- `9026/tcp` and `9027/udp`: HiWonder discovery/remote tooling
- `7788/tcp`: active service, exact process not identified from user-level scan

## Main Robot API

`/home/pi/TonyPi/RPCServer.py` exposes JSON-RPC methods including:

- `RunAction`
- `StopActionGroup`
- `StandUp`
- `LoadFunc`
- `UnloadFunc`
- `StartFunc`
- `StopFunc`
- `FinishFunc`
- `Heartbeat`
- `GetRunningFunc`
- `SetBusServoPulse`
- `SetPWMServo`
- `GetBusServosPulse`
- `SetLABValue`
- `GetLABValue`
- `SaveLABValue`

This gives us two integration styles:

1. Run code directly on the robot and import the HiWonder SDK, as the current
   Cosmo scripts do.
2. Build a controller app that calls the JSON-RPC API on port `9030`.

## Action Groups

The SDK runs action groups from `/home/pi/TonyPi/ActionGroups`.

The current Cosmo allowlist uses:

- `go_forward_one_step`
- `back_one_step`
- `turn_left_fast`
- `turn_right_fast`
- `wave`
- `bow`
- `squat`
- `sit_ups`
- `stand`

Other available action groups include walking, turning, kicking, dancing,
standing up from falls, grabbing, object transport, and athletic course actions.

## Git State Observations

`/home/pi/TonyPi` is a Git repository with remote:

```text
origin http://192.168.11.206:3000/tonypi/tonypi2025.git
```

It has local modifications in robot-critical files such as:

- `TonyPi.py`
- `RPCServer.py`
- `Joystick.py`
- `MjpgServer.py`
- `Functions/Running.py`
- `Functions/pose_control.py`
- `Functions/voice_interaction/*`
- `lab_config.yaml`
- `servo_config.yaml`
- many `ActionGroups/*.d6a`

It also has many untracked files, including agent functions, model files,
`tonypi2025/`, generated logs, and additional action groups.

Because of this, do not run cleanup, reset, checkout, or formatting operations
inside `/home/pi/TonyPi` without an explicit backup and rollback plan.

## Disk Usage Highlights

Approximate `/home/pi` sizes:

- `/home/pi/TonyPi`: 654 MB
- `/home/pi/third_party`: 742 MB
- `/home/pi/large_models`: 72 MB
- `/home/pi/cosmo_robotics`: 1.1 MB
- `/home/pi/.local`: 1.6 GB
- `/home/pi/.vscode-server`: 970 MB
- `/home/pi/.cache`: 560 MB
- `/home/pi/.cursor-server`: 540 MB

Approximate `/usr/local` size: 3.4 GB, mostly `/usr/local/lib/ollama`.

## Recommended Boundary

Use this repository as the source of truth and deploy to `/home/pi/cosmo_robotics`.

Do not edit vendor robot files directly during normal Cosmo development. If a
future feature requires changes in `/home/pi/TonyPi`, first:

1. Capture `git status` and the exact files affected.
2. Back up the files to a timestamped directory.
3. Make the smallest possible patch.
4. Test the service and document the rollback command.
5. Mirror the change in this repository as documentation or a patch artifact.
