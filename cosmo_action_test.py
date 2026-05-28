import sys
import time

sys.path.append("/home/pi/TonyPi")
sys.path.append("/home/pi/TonyPi/tonypi2025")

import hiwonder.ActionGroupControl as AGC

def run_action(action_name, repeat=1):
    for i in range(repeat):
        print(f"Running action: {action_name} ({i+1}/{repeat})")
        AGC.runAction(action_name)
        time.sleep(0.3)

if __name__ == "__main__":
    run_action("stand", 1)
    time.sleep(1)
    run_action("wave", 1)
    time.sleep(1)
    run_action("stand", 1)