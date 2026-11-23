"""Keep the RoboVac L60 cleaning only in its full-power battery range.

The robot's firmware cuts suction below 80% battery. This script keeps it cleaning between --high
(default 100%) and --low (default 80%):
  - while it cleans, it is sent home when the battery reaches --low;
  - once recharged to --high, cleaning starts again.

Two ways to clean:
  * whole map (default): each round is a fresh auto clean.
  * --rooms 1,2,3: clean the rooms one at a time, each starting from a full battery. A room that is
    interrupted at --low is cleaned again from the start after recharging.

Room IDs and the map ID are numbers the app does not show: find them with probe_rooms.py and watch.py
(see README). Each room should be small enough to clean on 20% of the battery.

Firmware behaviour (L60, firmware 1.4.5): sending the robot home ends its clean, and both "start" and
"resume" afterwards begin a NEW clean, even after pausing first. That is why whole-map mode restarts
from scratch every round, and why splitting the map into rooms works better.

Usage examples:
  python full_power.py --start-now                  whole map, start once charged
  python full_power.py --rooms 2,3,1 --start-now    rooms 2, 3, then 1, each from a full battery
  python full_power.py                              watch only; take over a clean you start in the app
  python full_power.py --dry-run --rooms 2,3        log what it would do, send nothing
  python full_power.py --rooms 1,2 --start-now --max-retries 0 --too-big skip --give-up-after 6
                                                    what the daily task runs (see schedule_daily.ps1)
Stop with Ctrl-C (the robot keeps doing whatever it was doing).
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402
from send_mode import COMMANDS, room_clean  # noqa: E402

MODE_DP, BATTERY_DP = 152, "163"

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("--low", type=int, default=80, help="send home at or below this battery %% (default 80)")
p.add_argument("--high", type=int, default=100, help="start cleaning at or above this %% (default 100)")
p.add_argument("--rooms", help="comma-separated room IDs to clean one at a time, in this order")
p.add_argument("--map", type=int, help="map ID for room cleaning (default: map_id in robot_config.json)")
p.add_argument("--start-now", action="store_true", help="start as soon as battery >= --high")
p.add_argument("--max-retries", type=int, default=2,
               help="rooms mode: times a room may be interrupted at --low before skipping it (default 2)")
p.add_argument("--too-big", choices=["finish", "skip"], default="finish",
               help="rooms mode, after --max-retries: 'finish' lets the room finish on reduced power, "
                    "'skip' sends the robot home and moves on to the next room (default finish)")
p.add_argument("--max-rounds", type=int, default=6, help="whole-map mode: recharge cycles before giving up (default 6)")
p.add_argument("--give-up-after", type=float, default=0,
               help="stop the script after this many hours even if not done, e.g. robot off its dock (default never)")
p.add_argument("--poll", type=int, default=20, help="seconds between battery checks (default 20)")
p.add_argument("--dry-run", action="store_true", help="never send commands, only log")
args = p.parse_args()

rooms = [int(x) for x in args.rooms.split(",")] if args.rooms else []
config.load()  # fail early, with a clear message, if robot_config.json is missing or incomplete
if rooms:
    args.map = config.map_id(args.map)
LOG = HERE / "full_power.log"


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    if sys.stdout:  # None when run hidden with pythonw (scheduled task)
        print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def keep_pc_awake():
    """Stop Windows from sleeping while this script runs (released automatically when it exits)."""
    if sys.platform == "win32":
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def device():
    return config.device(timeout=6, retries=2)


def battery():
    try:
        return (device().status().get("dps") or {}).get(BATTERY_DP)
    except Exception as e:
        log(f"read failed: {e}")
        return None


def send(label, value):
    if args.dry_run:
        log(f"[dry run] would send {label}")
        return True
    for attempt in range(3):
        try:
            r = device().set_value(MODE_DP, value)
            if isinstance(r, dict) and not r.get("Error"):
                log(f"sent {label}")
                return True
            log(f"send {label} attempt {attempt + 1} failed: {r}")
        except Exception as e:
            log(f"send {label} attempt {attempt + 1} error: {e}")
        time.sleep(3)
    return False


room_idx = 0
retries = 0


def start_cleaning():
    if rooms:
        rid = rooms[room_idx]
        return send(f"room clean: room {rid} ({room_idx + 1} of {len(rooms)}, map {args.map})",
                    room_clean([rid], args.map))
    return send("start (whole map)", COMMANDS["start"])


def job_name():
    return f"room {rooms[room_idx]}" if rooms else "clean"


# States: WAIT_FULL (charging before the next start), IDLE (watching), CLEANING, CHARGING (sent home by us)
state = "WAIT_FULL" if (args.start_now or rooms) else "IDLE"
rounds = 0
peak = low_seen = home_sent_at_level = last_battery = None

log(f"started: state={state} low={args.low} high={args.high} "
    f"{'rooms=' + str(rooms) + ' map=' + str(args.map) if rooms else 'whole map'}"
    f"{f' too-big={args.too_big} max-retries={args.max_retries}' if rooms else ''}"
    f"{f' give-up-after={args.give_up_after}h' if args.give_up_after else ''}"
    f"{' DRY RUN' if args.dry_run else ''}")
keep_pc_awake()
t0 = time.time()
try:
    while True:
        if args.give_up_after and time.time() - t0 > args.give_up_after * 3600:
            log(f"giving up after {args.give_up_after} h (state {state}, battery {last_battery}%) - "
                "the robot may be off its dock or unreachable. Leaving it alone.")
            break
        b = battery()
        if b is None:
            time.sleep(args.poll)
            continue
        if b != last_battery:
            what = {"WAIT_FULL": f"charging, waiting for {args.high}% to start {job_name()}",
                    "CHARGING": f"recharging, {job_name()} {'starts' if rooms and not retries else 'restarts'} at {args.high}%",
                    "CLEANING": f"cleaning {job_name()}, going home at {args.low}%",
                    "IDLE": "watching for a clean to start",
                    "IDLE_UNTIL_DOCKED": "finishing an oversized room at reduced power"}.get(state, state)
            log(f"battery {b}% - {what}")
            last_battery = b

        if state in ("WAIT_FULL", "CHARGING"):
            if b >= args.high:
                verb = ("starting" if state == "WAIT_FULL" else
                        "recharged, starting" if rooms and not retries else "recharged, restarting")
                log(f"battery {b}% - {verb} {job_name()}")
                if start_cleaning():
                    state, low_seen = "CLEANING", b
            elif state == "CHARGING" and home_sent_at_level is not None and b <= home_sent_at_level - 4:
                log(f"battery still falling ({b}%) after home command - sending home again")
                send("home", COMMANDS["home"])
                home_sent_at_level = b

        elif state == "IDLE":
            # A clean started elsewhere shows up as the battery falling from its recent peak.
            peak = b if peak is None else max(peak, b)
            if b <= peak - 2:
                log(f"battery falling ({peak}% -> {b}%): a clean seems to be running, taking over")
                state, low_seen = "CLEANING", b

        if state == "CLEANING":
            low_seen = min(low_seen, b) if low_seen is not None else b
            if b <= args.low:
                if rooms:
                    retries += 1
                    if retries > args.max_retries:
                        rid = rooms[room_idx]
                        retries = 0
                        room_idx += 1
                        last_room = room_idx >= len(rooms)
                        if args.too_big == "skip":
                            log(f"room {rid} did not fit between {args.high}% and {args.low}% - sending the robot home "
                                "and skipping the rest of it (split it into smaller rooms in the app)")
                            send("home", COMMANDS["home"])
                            if last_room:
                                log("all rooms handled. Done.")
                                break
                            state, home_sent_at_level = "CHARGING", b
                            log(f"next: room {rooms[room_idx]} once battery reaches {args.high}%")
                        else:
                            log(f"room {rid} did not fit between {args.high}% and {args.low}% - "
                                "letting it finish on reduced power, then moving on")
                            if last_room:
                                log("all rooms handled. Done.")
                                break
                            state = "IDLE_UNTIL_DOCKED"
                        time.sleep(args.poll)
                        continue
                elif rounds >= args.max_rounds:
                    log(f"battery {b}% but max rounds ({args.max_rounds}) reached - leaving the robot alone")
                    break
                log(f"battery {b}% <= {args.low}% - sending robot home to recharge ({job_name()} will restart)")
                if send("home", COMMANDS["home"]):
                    state, home_sent_at_level = "CHARGING", b
                    rounds += 1
            elif b >= low_seen + 2:
                log(f"battery rising ({low_seen}% -> {b}%): {job_name()} finished and the robot docked")
                if rooms:
                    room_idx += 1
                    retries = 0
                    if room_idx >= len(rooms):
                        log("all rooms cleaned. Done.")
                        break
                    state = "WAIT_FULL"
                    log(f"next: room {rooms[room_idx]} once battery reaches {args.high}%")
                else:
                    log("Done.")
                    break

        elif state == "IDLE_UNTIL_DOCKED":
            # Skipped room still running at reduced power: wait for it to finish, then continue with the next.
            low_seen = min(low_seen, b) if low_seen is not None else b
            if b >= low_seen + 2:
                log(f"robot docked - next: room {rooms[room_idx]} once battery reaches {args.high}%")
                state = "WAIT_FULL"

        time.sleep(args.poll)
except KeyboardInterrupt:
    log("stopped by user")
except Exception as e:  # a hidden scheduled run has no console, so make sure crashes reach the log
    log(f"script error, stopping: {e!r}")
    raise
