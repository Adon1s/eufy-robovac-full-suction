# eufy RoboVac full power

Keep a **eufy RoboVac L60** cleaning at full suction, by only letting it clean while the battery is between 100% and 80%.

> Unofficial project. Not affiliated with, endorsed by or supported by Anker or eufy. "eufy" and "RoboVac" are their trademarks.
> Use at your own risk; a firmware update could change or break any of this.

## The problem

Once the L60's battery drops below **80%**, the robot quietly lowers its suction at *every* level (Quiet, Standard, Turbo and Max).
You can hear it, and you can see it in the results. Meanwhile the app, and the robot's own status data, keep reporting the setting you chose ("Max").
The limit lives in the robot's firmware, so changing the app cannot fix it.

## The workaround

Control the robot directly over your home network and keep it inside the full-power battery range:

1. Split your floor into rooms in the eufy app, each small enough to clean on 20% of the battery.
2. `full_power.py` waits until the robot is at **100%**, cleans **one room**, and sends the robot home if the battery reaches **80%**.
3. Once the robot is back at 100%, it cleans the next room, and so on.
4. `schedule_daily.ps1` runs all of this every night (Windows).

Why rooms, and not just "send it home at 80% and resume later"? On this firmware, sending the robot home *ends* its clean.
A "resume" afterwards starts a brand-new clean from the beginning, so the same part gets cleaned again and the rest never does.

As a rough guide, one 100%→80% charge covered about 10–12 m² of a cluttered room in our tests. Your rooms will differ.

## Tested on

| | |
|---|---|
| Robot | eufy RoboVac L60 (model T2267), firmware 1.4.5 |
| App | eufy Clean 3.20.0 |
| PC | Windows 11, Python 3.13 |

Other eufy robots that use the same protobuf-style data points (DP 152–179) may work but are untested. Reports are welcome.
The Python scripts should run on macOS and Linux too; only the scheduler script is Windows-specific (use cron there).

## Setup

You need Python 3.9 or newer, and a PC on the same network as the robot.

```
pip install -r requirements.txt
```

### 1. Get the robot's local key

```
python get_local_key.py
```

This asks for your eufy account email and password. The password is not shown or stored, and goes only to eufy's own login server.
The script fetches the robot's *local key* (the key that encrypts local network traffic), listens on your network for the robot to find its IP address,
and writes `robot_config.json`. **That file is private:** anyone with it can control your robot on your network. It is in `.gitignore`.

Check that the local connection works (read-only; sends nothing):

```
python read_status.py
```

### 2. Split your map into rooms

In the eufy app, edit the map and divide large areas into rooms that each fit in 20% of the battery.
If a room turns out too big, `full_power.py` says so in its log, and you can split it further.

### 3. Find your map ID

```
python watch.py
```

Leave it running, start any clean in the eufy app, and stop it after a minute. When the clean ends, watch.py prints a "clean record" line that includes `map N`.
Add that number to your robot in `robot_config.json`:

```json
"map_id": 4
```

### 4. Find your room IDs

The app shows room names, but the robot only takes numbers, and it never reports which number is which room. `probe_rooms.py` finds the valid ones.
**The robot will move.** Stay nearby and note which area it heads for each time:

```
python probe_rooms.py 1 6
```

For each ID it starts a room clean, watches for 40 s, then stops. An ID that is not a room makes the robot give up and head home (prompt code P0040).
To double-check one ID, use `python send_mode.py room 2 60`, then `python send_mode.py home`.

### 5. Run it

```
python full_power.py --rooms 1,2 --start-now
```

This cleans room 1, then room 2, each starting at 100%. Everything it does is printed and appended to `full_power.log`. Stop it with Ctrl-C; the robot carries on with whatever it was doing.

Useful options (`python full_power.py --help` lists them all):

| Option | Meaning |
|---|---|
| `--low 80` / `--high 100` | the battery range to clean in |
| `--max-retries N` | times a room may be interrupted at `--low` before giving up on it (default 2) |
| `--too-big finish\|skip` | after that: let the room finish at reduced power, or send the robot home and move on |
| `--give-up-after H` | stop after H hours no matter what (e.g. robot off its dock) |
| `--dry-run` | log what it would do, send nothing |
| no `--rooms` | whole map: restarts from scratch after every recharge (see above for why that is worse) |

### 6. Clean every night (Windows)

```
.\schedule_daily.ps1 -Rooms 1,2              # daily at 02:00
.\schedule_daily.ps1 -Rooms 1,2 -Time 03:30
Start-ScheduledTask "eufy full-power clean"  # run it now, to test
.\schedule_daily.ps1 -Remove
```

The task runs `full_power.py` hidden, with `--max-retries 0 --too-big skip --give-up-after 6`. A room that does not fit in one charge is skipped rather than re-cleaned, and the log tells you to split it.
It wakes the PC if it is asleep, keeps it awake until done, and runs only while you are signed in to Windows (a locked screen is fine). If the PC is off at that time, that day is skipped.
If Do Not Disturb is set for the night in the eufy app, check the log after the first night to make sure the robot started.

## The tools

| Script | What it does |
|---|---|
| `get_local_key.py` | logs in to your eufy account, gets the local key, finds the robot's IP, writes `robot_config.json` |
| `read_status.py` | prints the robot's current data, decoded (read-only) |
| `watch.py` | live, decoded view of everything the robot reports (read-only) |
| `send_mode.py` | sends one command: `start`, `home`, `pause`, `resume`, `stop`, or `room 1,2` |
| `probe_rooms.py` | finds valid room IDs (moves the robot) |
| `full_power.py` | the 100%→80% cleaning loop |
| `schedule_daily.ps1` | registers a daily Windows scheduled task for `full_power.py` |
| `pb_decode.py` | decodes any data-point value as raw protobuf: `python pb_decode.py 153=<value>` |

## What the robot reports

The robot speaks Tuya local protocol 3.3 on TCP port 6668. Most of its data points hold base64 text: a varint length, then a protobuf message.
Field meanings come from the projects credited below, plus our own testing. "?" means unconfirmed.

| DP | Meaning |
|---|---|
| 152 | command (ModeCtrlRequest). Methods: 0 auto clean, 1 room clean, 2 zone, 3 spot, 6 go home, 12 stop, 13 pause, 14 resume, 15 stop going home, 24 scene |
| 153 | work status: state (0 standby, 1 sleep, 2 fault, 3 charging, 5 cleaning, 6 remote control, 7 going home), mode (auto / selected rooms), paused, relocating |
| 158 | suction setting (Quiet / Standard / Turbo / Max). Keeps saying Max below 80% |
| 159 | BoostIQ |
| 160 | locate (beep) |
| 161 | speaker volume |
| 163 | battery % |
| 167 | lifetime and user totals: hours, m², number of cleans |
| 168 | consumable usage in hours: side brush, rolling brush, filter, sensors (field 7 unknown) |
| 169 | device info: model name, MAC, firmware, hardware |
| 176 | settings: child lock (field 1), multi-map (3), Wi-Fi signal % (11), Wi-Fi network (12) |
| 177 | errors and warnings (e.g. 7002 = robot lifted or stuck) |
| 178 | prompt codes (P0031 = clean started, P0040 = room not found) |
| 179 | records: clean record (start/end time, seconds, m², map ID, room count, why it ended), go-home record, control events |
| 151, 164, 170–173 | unknown. 170–172 changed when the map was split into rooms |

Firmware behaviour seen on 1.4.5:

- Going home ends the current clean. `start` and `resume` both begin a new clean afterwards, even after a pause.
- The robot accepts any room ID at first and only rejects an invalid one after relocating (20–40 s later).
- The command echo on DP 152 drops the parameters, so room IDs are never reported back.

## Privacy

- `robot_config.json` holds your local key, device ID and MAC address. Never share or commit it.
- `full_power.log` and `watch_raw.log` contain your Wi-Fi network name, MAC address and cleaning history.
- All three are listed in `.gitignore`.
- Your eufy password is used once, sent only to eufy's servers, and never saved.
- Day-to-day control is entirely local; nothing goes through the cloud.

## Credits

- [damacus/robovac](https://github.com/damacus/robovac) (Apache 2.0, Copyright 2022 Brendan McCluskey) and its L60 fork [Ascendor/robovac-l60-hybrid](https://github.com/Ascendor/robovac-l60-hybrid): Home Assistant integration. The eufy/Tuya login flow in `get_local_key.py` is adapted from it, and the L60 data-point list comes from it.
- [martijnpoppen/eufy-clean](https://github.com/martijnpoppen/eufy-clean): protobuf definitions for eufy's robot messages, used as the reference for field meanings (no code copied).
- Andre Borie's [eufy-device-id-and-local-key-grabber](https://gitlab.com/Rjevski/eufy-device-id-and-local-key-grabber): the original local key method.
- [jasonacox/tinytuya](https://github.com/jasonacox/tinytuya) (MIT): Tuya local protocol and network discovery.

## License

Apache License 2.0. See [LICENSE](LICENSE).
