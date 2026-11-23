"""Send one command to the RoboVac, then print every update it reports for N seconds.
Usage:
  python send_mode.py start|home|pause|resume|stop [watch_seconds]
  python send_mode.py room ROOM_IDS [watch_seconds] [--map N] [--releases N] [--order-base 0|1] [--times 1]
      e.g. python send_mode.py room 1 30         python send_mode.py room 2,3 30 --map 4
The map ID comes from robot_config.json unless you pass --map.

Commands go on data point 152 as a protobuf ModeCtrlRequest (base64, varint length prefix).
Tested on an L60 (T2267), firmware 1.4.5.
"""
import argparse
import base64
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402

COMMANDS = {
    "start": "BBoCCAE=",   # method 0 START_AUTO_CLEAN, auto_clean{clean_times=1}
    "home": "AggG",        # method 6 START_GOHOME
    "stop": "AggM",        # method 12 STOP_TASK
    "pause": "AggN",       # method 13 PAUSE_TASK
    "resume": "AggO",      # method 14 RESUME_TASK
}
MODE_DP = 152


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field_int(num, value):
    return _varint(num << 3) + _varint(value) if value else b""


def _field_msg(num, body):
    return _varint((num << 3) | 2) + _varint(len(body)) + body


def room_clean(room_ids, map_id, releases=0, clean_times=1, order_base=0):
    """ModeCtrlRequest{method=1 START_SELECT_ROOMS_CLEAN, select_rooms_clean(4){rooms(1){id,order}, clean_times(2), map_id(3), releases(4)}}"""
    sel = b"".join(_field_msg(1, _field_int(1, rid) + _field_int(2, i + order_base)) for i, rid in enumerate(room_ids))
    sel += _field_int(2, clean_times) + _field_int(3, map_id) + _field_int(4, releases)
    body = _field_int(1, 1) + _field_msg(4, sel)
    return base64.b64encode(_varint(len(body)) + body).decode()


def connect():
    return config.device(persistent=True, timeout=3)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=[*COMMANDS, "room"])
    p.add_argument("rooms_or_seconds", nargs="?")
    p.add_argument("seconds", nargs="?", type=int)
    p.add_argument("--map", type=int, help="map ID (default: map_id in robot_config.json)")
    p.add_argument("--releases", type=int, default=0)
    p.add_argument("--order-base", type=int, default=0)
    p.add_argument("--times", type=int, default=1)
    a = p.parse_args()

    if a.command == "room":
        rooms = [int(x) for x in a.rooms_or_seconds.split(",")]
        map_id = config.map_id(a.map)
        value = room_clean(rooms, map_id, a.releases, a.times, a.order_base)
        label = f"room clean rooms={rooms} map={map_id} releases={a.releases} order_base={a.order_base}"
        watch = a.seconds or 30
    else:
        value = COMMANDS[a.command]
        label = a.command
        watch = int(a.rooms_or_seconds) if a.rooms_or_seconds else 30

    dev = connect()
    print("before:", dev.status().get("dps"))
    print(f"sending {label} ({value}) on DP {MODE_DP}")
    reply = dev.set_value(MODE_DP, value)
    print("reply:", reply.get("dps") if isinstance(reply, dict) else reply)

    end = time.time() + watch
    while time.time() < end:
        data = dev.receive()
        if data and data.get("dps"):
            print(f"  +{int(watch - (end - time.time())):>3}s update: {data['dps']}")
        else:
            dev.heartbeat()
    print("after:", dev.status().get("dps"))


if __name__ == "__main__":
    main()
