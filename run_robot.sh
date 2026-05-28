#!/bin/bash
set -e

ROBOT_HOST="pi@192.168.1.15"
REMOTE_DIR="/home/pi/cosmo_robotics"

ssh "$ROBOT_HOST" "cd $REMOTE_DIR && python3 cosmo_voice_to_robot.py"
