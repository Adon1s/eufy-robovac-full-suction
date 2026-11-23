"""Read-only: connect to the RoboVac on the local network and print its current data points, decoded.
Sends no commands. Usage:  python read_status.py
Good first test after get_local_key.py: if this prints your battery level, the local connection works.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402
from watch import describe  # noqa: E402

robot = config.load()
result = config.device(timeout=8).status()

if "dps" not in result:
    print("No data returned:", {k: v for k, v in result.items() if k != "payload"})
    print("Check the IP address in robot_config.json, and that no firewall blocks TCP port 6668.")
    raise SystemExit(1)

print(f"Connected to {robot.get('name')} ({robot.get('model')}) at {robot['ip']}\n")
for dp, value in sorted(result["dps"].items(), key=lambda kv: int(kv[0])):
    print(f"  DP {dp:>4}  {describe(dp, value)}")
