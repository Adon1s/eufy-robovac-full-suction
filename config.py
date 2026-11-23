"""Shared settings for all scripts: reads robot_config.json (written by get_local_key.py).

robot_config.json is a list of robots. The first one is used. Fields:
  name, model, device_id, mac, local_key   from your eufy account (get_local_key.py)
  ip, protocol                             found on your network (get_local_key.py)
  map_id                                   optional, add it yourself (see MAP_HELP)
Keep this file private: the local key gives full control of the robot on your network.
"""
import json
import sys
from pathlib import Path

import tinytuya

CONFIG_FILE = Path(__file__).with_name("robot_config.json")

MAP_HELP = """No map ID set. To find it:
  1. run  python watch.py
  2. start any clean in the eufy app and stop it after a minute
  3. the "clean record" line watch.py prints shows "map N"
Then add  "map_id": N  to your robot in robot_config.json, or pass --map N."""


def load():
    if not CONFIG_FILE.exists():
        sys.exit("robot_config.json not found - run  python get_local_key.py  first (see README).")
    robots = json.loads(CONFIG_FILE.read_text())
    if not robots:
        sys.exit("robot_config.json has no robots in it - run  python get_local_key.py  again.")
    robot = robots[0]
    if not robot.get("ip"):
        sys.exit(f"No IP address for {robot.get('name')} in robot_config.json. Make sure the robot is on and on "
                 "the same network as this PC, then run  python get_local_key.py  again, or add \"ip\" yourself.")
    return robot


def device(persistent=False, timeout=5, retries=None):
    r = load()
    d = tinytuya.Device(r["device_id"], r["ip"], r["local_key"], version=float(r.get("protocol") or 3.3))
    d.set_socketPersistent(persistent)
    d.set_socketTimeout(timeout)
    if retries is not None:
        d.set_socketRetryLimit(retries)
    return d


def map_id(override=None):
    """--map on the command line wins; otherwise map_id from robot_config.json."""
    if override is not None:
        return override
    m = load().get("map_id")
    if m is None:
        sys.exit(MAP_HELP)
    return int(m)
