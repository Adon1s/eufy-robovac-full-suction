"""Find your room IDs: try a room clean for each ID in a range and report which ones are real rooms.

The eufy app shows room names, but the robot only takes numeric IDs, and it does not report them back.
So this script asks the robot to clean room 1, 2, 3, ... in turn, watches for --watch seconds, then stops it.
An ID that is not a room makes the robot give up and head home (prompt code P0040).
Sends the robot home at the end. THE ROBOT WILL MOVE - stay nearby and watch which area it heads for,
so you can match each valid ID to a room name in the app.

Usage:  python probe_rooms.py [first_id] [last_id] [--map N] [--watch 40]
Watch at least ~40 s: the robot accepts any ID at first and only checks it after relocating itself.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402
from send_mode import COMMANDS, connect, room_clean  # noqa: E402
from watch import describe  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("first", type=int, nargs="?", default=1)
p.add_argument("last", type=int, nargs="?", default=6)
p.add_argument("--map", type=int, help="map ID (default: map_id in robot_config.json)")
p.add_argument("--watch", type=int, default=40)
a = p.parse_args()
a.map = config.map_id(a.map)

dev = connect()


def collect(seconds):
    out, end = [], time.time() + seconds
    while time.time() < end:
        data = dev.receive()
        if data and data.get("dps"):
            for dp, v in data["dps"].items():
                out.append((dp, v))
        else:
            dev.heartbeat()
    return out


summary = {}
for rid in range(a.first, a.last + 1):
    print(f"\n=== room {rid} (map {a.map}) ===", flush=True)
    dev.set_value(152, room_clean([rid], a.map))
    events = collect(a.watch)
    for dp, v in events:
        if dp in ("152", "153", "177", "178", "179"):
            print(f"    +{dp}", describe(dp, v), flush=True)
    states = [describe(dp, v) for dp, v in events if dp == "153"]
    errors = [describe(dp, v) for dp, v in events if dp == "177" and "none" not in describe(dp, v)]
    prompts = [describe(dp, v) for dp, v in events if dp == "178" and describe(dp, v) != "prompt codes: "]
    # The robot accepts any ID at first; after relocating, an unknown room makes it head home with prompt P0040.
    rejected = any("returning to dock" in s for s in states) or any("P0040" in s for s in prompts)
    started = any("selected rooms" in s and "cleaning" in s for s in states)
    summary[rid] = ("VALID ROOM" if started and not rejected else "not a room") + (f"  {errors}" if errors else "") + (f"  {prompts}" if prompts else "")
    dev.set_value(152, COMMANDS["stop"])
    for dp, v in collect(6):
        if dp == "179" and "clean record" in describe(dp, v):
            print("   ", describe(dp, v))
            summary[rid] += "  | " + describe(dp, v)

print("\nsending robot home")
dev.set_value(152, COMMANDS["home"])
print("\nSUMMARY")
for rid, s in summary.items():
    print(f"  room {rid}: {s}")
