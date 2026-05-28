#!/bin/bash
set -e

ROBOT_HOST="pi@192.168.1.15"
REMOTE_DIR="/home/pi/cosmo_robotics"

echo "Deploying to TonyPi..."
rsync -avz --exclude ".git" ./ "$ROBOT_HOST:$REMOTE_DIR/"

echo "Done."
