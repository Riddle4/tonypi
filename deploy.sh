#!/bin/bash
set -e

ROBOT_HOST="pi@192.168.1.15"
REMOTE_DIR="/home/pi/cosmo_robotics"

echo "Deploying to TonyPi..."
rsync -avz \
  --exclude ".git" \
  --exclude "__pycache__" \
  --exclude "*.pyc" \
  --exclude "recording.wav" \
  --exclude "reply.mp3" \
  --exclude "woody_wake.wav" \
  --exclude "woody_turn.wav" \
  --exclude "woody_reply.mp3" \
  ./ "$ROBOT_HOST:$REMOTE_DIR/"

echo "Done."
