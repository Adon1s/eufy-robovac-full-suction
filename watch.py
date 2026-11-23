"""Read-only live view of everything the RoboVac reports, decoded into plain language.
Usage:  python watch.py [seconds]      (default: run until Ctrl-C)
Sends no commands. Raw values are also appended to watch_raw.log (private: it holds your Wi-Fi name and MAC).

Field meanings come from community reverse-engineering of eufy's protobuf messages
(martijnpoppen/eufy-clean .proto files, damacus/robovac decoders). Fields marked "?" are unconfirmed.
"""
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402
from pb_decode import decode  # noqa: E402

STATE = {0: "standby", 1: "sleep", 2: "fault", 3: "charging", 4: "fast mapping", 5: "cleaning",
         6: "remote control", 7: "returning to dock", 8: "cruising"}
MODE = {0: "auto", 1: "selected rooms", 2: "zones", 3: "spot", 4: "fast mapping"}
FAIL = {0: "none/unknown", 1: "robot fault", 2: "robot alert", 3: "stopped manually"}
METHOD = {0: "start auto clean", 1: "start room clean", 2: "start zone clean", 3: "spot clean",
          6: "go home", 12: "stop", 13: "pause", 14: "resume", 15: "stop going home", 24: "scene clean"}
RAW_LOG = Path(__file__).with_name("watch_raw.log")
CODES = {  # eufy T22xx list; not confirmed for every code on the L60
    2112: "roller brush stuck", 2213: "side brush stuck", 2310: "dustbin not installed",
    4012: "laser cover stuck", 5014: "low battery shutdown", 7000: "robot trapped",
    7002: "robot suspended / lifted or stuck",
}


def f(msg, *path, default=None):
    """Get nested field value by field numbers."""
    cur = msg
    for num in path:
        if not isinstance(cur, list):
            return default
        cur = next((v for k, v in cur if k == num), None)
        if cur is None:
            return default
    return cur


def packed(v):
    """Packed repeated varints arrive as bytes."""
    if isinstance(v, int):
        return [v]
    if isinstance(v, (bytes, bytearray)):
        out, cur, shift = [], 0, 0
        for b in v:
            cur |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                out.append(cur)
                cur = shift = 0
        return out
    return []


def ts(v):
    return datetime.fromtimestamp(v).strftime("%H:%M:%S") if isinstance(v, int) and v > 1_600_000_000 else "?"


def describe(dp, val):
    if dp == "163":
        return f"battery {val}%"
    if dp == "158":
        return f"suction setting {val}"
    if dp == "159":
        return f"BoostIQ {'on' if val else 'off'}"
    if dp == "161":
        return f"speaker volume {val}"
    if not isinstance(val, str):
        return f"DP {dp} = {val!r}"
    try:
        m = decode(val)
    except Exception:
        return f"DP {dp} = {val!r} (not decodable)"

    if dp == "152":
        method = f(m, 1, default=0)
        text = f"command echo: {METHOD.get(method, f'method {method}')}"
        rooms = f(m, 4)
        if method == 1 and isinstance(rooms, list):  # SelectRoomsClean
            ids = [f(r, 1) for k, r in rooms if k == 1 and isinstance(r, list)]
            text = (f"command echo: ROOM CLEAN rooms {ids} map_id {f(rooms, 3)} releases {f(rooms, 4)}"
                    f" clean_times {f(rooms, 2)} mode {f(rooms, 5, default=0)}")
        elif method == 2:
            text = "command echo: ZONE CLEAN " + str(f(m, 5))
        return text
    if dp == "153":
        state = f(m, 2, default=0)
        text = STATE.get(state, f"state {state}")
        if f(m, 6) is not None:
            text += " (paused)" if f(m, 6, 1) == 1 else ""
        if f(m, 10) is not None:
            text += ", relocating"
        if f(m, 3, 1) == 1:
            text += " (charge complete)"
        return f"status: {text}, mode {MODE.get(f(m, 1, 1, default=0), '?')}"
    if dp == "167":
        tot, usr = f(m, 2) or [], f(m, 3) or []
        return (f"lifetime totals: {f(tot, 1, default=0) / 3600:.1f} h, {f(tot, 2)} m2, {f(tot, 3)} cleans"
                f" | user totals: {f(usr, 1, default=0) / 3600:.1f} h, {f(usr, 2)} m2, {f(usr, 3)} cleans")
    if dp == "168":
        r = f(m, 1) or []
        names = {1: "side brush", 2: "rolling brush", 3: "filter", 4: "scraper", 5: "sensors", 6: "mop", 7: "field 7 (unknown)"}
        parts = [f"{n} {f(r, k, 1)}h" for k, n in names.items() if f(r, k, 1) is not None]
        return "consumable usage: " + ", ".join(parts)
    if dp == "169":
        return (f"device: {f(m, 1, default=b'').decode()} mac {f(m, 3, default=b'').decode()}"
                f" firmware {f(m, 4, default=b'').decode()} hardware {f(m, 5)}")
    if dp == "176":
        aps = f(m, 12, 1) or []
        ssid = f(aps, 1, default=b"").decode() if aps else "?"
        return (f"settings: child lock {'on' if f(m, 1, 1) else 'off'}, multi-map {'on' if f(m, 3, 1) else 'off'},"
                f" wifi '{ssid}' signal {f(m, 11)}%")
    if dp == "177":
        errs = packed(f(m, 2)) + packed(f(m, 10, 1))
        warns = packed(f(m, 3)) + packed(f(m, 10, 2))
        if not errs and not warns:
            return "errors: none"
        lab = lambda c: f"{c} ({CODES.get(c, 'unknown code')})"
        parts = []
        if errs:
            parts.append("errors: " + ", ".join(map(lab, sorted(set(errs)))))
        if warns:
            parts.append("warnings: " + ", ".join(map(lab, sorted(set(warns)))))
        return " | ".join(parts)
    if dp == "178":
        return "prompt codes: " + ", ".join(f"P{c:04d}" for c in packed(f(m, 2)))
    if dp == "179":
        c = f(m, 2, 1)
        if c:
            return (f"clean record #{f(c, 1)}: {MODE.get(f(c, 4, default=0), '?')} clean {ts(f(c, 6))}-{ts(f(c, 7))},"
                    f" {f(c, 8, default=0) // 60} min {f(c, 8, default=0) % 60} s cleaning, {f(c, 9)} m2 cleaned"
                    f" (map area {f(c, 10)} m2), map {f(c, 11)}, rooms {f(c, 12)},"
                    f" ended: {FAIL.get(f(c, 3, default=0), '?')}")
        g = f(m, 2, 2)
        if g:
            return f"go-home record #{f(g, 1)}: battery {f(g, 4)}%, {ts(f(g, 5))}-{ts(f(g, 6))}"
        e = f(m, 2, 5)
        if e:
            return f"control event #{f(e, 1)} at {ts(f(e, 4))}"
        return f"analysis event {m}"
    return f"DP {dp} (undocumented) {m}"


def main():
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else float("inf")
    dev = config.device(persistent=True, timeout=5)
    start = time.time()
    for dp, v in (dev.status().get("dps") or {}).items():
        print(f"{datetime.now():%H:%M:%S}  {describe(dp, v)}")
    try:
        dev.updatedps([153, 154, 167, 168, 169, 176, 177])  # ask for the values that are only pushed on change
    except Exception:
        pass
    while time.time() - start < limit:
        data = dev.receive()
        if data and data.get("dps"):
            for dp, v in data["dps"].items():
                print(f"{datetime.now():%H:%M:%S}  {describe(dp, v)}", flush=True)
                with RAW_LOG.open("a", encoding="utf-8") as log:
                    log.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}\t{dp}\t{v}\n")
        else:
            dev.heartbeat()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
