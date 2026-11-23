"""Fetch the Tuya local key for your eufy RoboVac(s) from your own eufy account.

Run it yourself:  python get_local_key.py
It asks for your eufy email and password (the password is not echoed or stored, and is sent only to
eufy's own login server), then listens on your network for the robot's broadcast to find its IP address,
and writes robot_config.json next to this script. The key is NOT printed. Run it on the same network as
the robot. Running it again keeps any map_id you added.

Login flow adapted (modified and condensed) from the robovac Home Assistant integration,
eufywebapi.py / tuyawebapi.py, Copyright 2022 Brendan McCluskey, Apache License 2.0:
https://github.com/damacus/robovac (and the Ascendor/robovac-l60-hybrid fork), which credits
Andre Borie: https://gitlab.com/Rjevski/eufy-device-id-and-local-key-grabber

Requires:  pip install -r requirements.txt
"""

import getpass
import hmac
import json
import math
import random
import string
import sys
import time
import uuid
from hashlib import md5, sha256
from pathlib import Path

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

OUT_FILE = Path(__file__).with_name("robot_config.json")

# ---------------------------------------------------------------- eufy API
EUFY_HEADERS = {
    "User-Agent": "EufyHome-Android-2.4.0",
    "timezone": "Europe/London",
    "category": "Home",
    "token": "",
    "uid": "",
    "openudid": "sdk_gphone64_arm64",
    "clientType": "2",
    "language": "en",
    "country": "US",
    "Accept-Encoding": "gzip",
}


def eufy_login(email, password):
    r = requests.post(
        "https://home-api.eufylife.com/v1/user/email/login",
        json={
            "client_Secret": "GQCpr9dSp3uQpsOMgJ4xQ",
            "client_id": "eufyhome-app",
            "email": email,
            "password": password,
        },
        headers=EUFY_HEADERS,
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("res_code") != 1:
        sys.exit(f"eufy login failed (res_code={data.get('res_code')}, message={data.get('message')!r})")
    return data


def eufy_get(host, path, user_id, token):
    headers = {**EUFY_HEADERS, "token": token, "id": user_id}
    r = requests.get(host + path, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------- Tuya API
TUYA_HMAC_KEY = b"A_cepev5pfnhua4dkqkdpmnrdxx378mpjr_s8x78u7xwymasd9kqa7a73pjhxqsedaj"
TUYA_INNER_KEY = bytes([36, 78, 109, 138, 86, 172, 135, 145, 36, 67, 45, 139, 108, 188, 162, 196])
TUYA_INNER_IV = bytes([119, 36, 86, 242, 167, 102, 76, 243, 57, 44, 53, 151, 233, 62, 87, 71])
TUYA_BASE_URLS = {
    "AZ": "https://a1.tuyaus.com",
    "AY": "https://a1.tuyacn.com",
    "IN": "https://a1.tuyain.com",
    "EU": "https://a1.tuyaeu.com",
}
SIGNED_PARAMS = {
    "a", "v", "lat", "lon", "lang", "deviceId", "appVersion", "ttid", "isH5",
    "h5Token", "os", "clientId", "postData", "time", "requestId", "et", "n4h5", "sid", "sp",
}


def shuffled_md5(value):
    h = md5(value.encode()).hexdigest()
    return h[8:16] + h[0:8] + h[24:32] + h[16:24]


def unpadded_rsa(exponent, n, plaintext):
    length = math.ceil(n.bit_length() / 8)
    return pow(int.from_bytes(plaintext, "big"), exponent, n).to_bytes(length, "big")


class Tuya:
    def __init__(self, username, region, timezone, phone_code):
        self.username = username
        self.phone_code = phone_code
        self.base_url = TUYA_BASE_URLS.get(region, TUYA_BASE_URLS["EU"])
        self.sid = None
        self.http = requests.Session()
        self.http.headers = {"User-Agent": "TY-UA=APP/Android/2.4.0/SDK/null"}
        chars = string.ascii_letters + string.digits
        self.params = {
            "appVersion": "2.4.0",
            "deviceId": "8534c8ec0ed0" + "".join(random.choice(chars) for _ in range(32)),
            "platform": "sdk_gphone64_arm64",
            "clientId": "yx5v9uc3ef9wg3v9atje",
            "lang": "en",
            "osSystem": "12",
            "os": "Android",
            "timeZoneId": timezone or "",
            "ttid": "android",
            "et": "0.0.1",
            "sdkVersion": "3.0.8cAnker",
        }

    def _sign(self, params, post):
        p = dict(params)
        if post:
            p["postData"] = post
        msg = "||".join(
            k + "=" + (shuffled_md5(v) if k == "postData" else v)
            for k, v in sorted(p.items())
            if k in SIGNED_PARAMS
        )
        return hmac.new(TUYA_HMAC_KEY, msg.encode(), sha256).hexdigest()

    def request(self, action, data=None, version="1.0", need_session=True):
        if need_session and not self.sid:
            self.login()
        params = {
            **self.params,
            "time": str(int(time.time())),
            "requestId": str(uuid.uuid4()),
            "a": action,
            "v": version,
        }
        post = json.dumps(data, separators=(",", ":")) if data else ""
        r = self.http.post(
            self.base_url + "/api.json",
            params={**params, "sign": self._sign(params, post)},
            data={"postData": post} if post else None,
            timeout=20,
        )
        r.raise_for_status()
        body = r.json()
        if "result" not in body:
            raise RuntimeError(f"Tuya {action} failed: {body.get('errorCode')} {body.get('errorMsg')}")
        return body["result"]

    def _password(self):
        uid = self.username
        padded = uid.zfill(16 * math.ceil(len(uid) / 16))
        enc = Cipher(algorithms.AES(TUYA_INNER_KEY), modes.CBC(TUYA_INNER_IV)).encryptor()
        ct = enc.update(padded.encode()) + enc.finalize()
        return md5(ct.hex().upper().encode()).hexdigest()

    def _session(self, password):
        tok = self.request(
            "tuya.m.user.uid.token.create",
            {"uid": self.username, "countryCode": self.phone_code},
            need_session=False,
        )
        enc = unpadded_rsa(int(tok["exponent"]), int(tok["publicKey"]), password.encode())
        return self.request(
            "tuya.m.user.uid.password.login.reg",
            {
                "uid": self.username,
                "createGroup": True,
                "ifencrypt": 1,
                "passwd": enc.hex(),
                "countryCode": self.phone_code,
                "options": '{"group": 1}',
                "token": tok["token"],
            },
            need_session=False,
        )

    def login(self):
        try:
            s = self._session(self._password())
        except Exception:
            s = self._session(md5(b"12345678").hexdigest())
        self.sid = self.params["sid"] = s["sid"]
        self.base_url = s["domain"]["mobileApiUrl"]
        if s.get("phoneCode"):
            self.phone_code = s["phoneCode"]

    def get_device(self, dev_id):
        return self.request("tuya.m.device.get", {"devId": dev_id})


# ---------------------------------------------------------------- local network
def find_on_network(device_ids, seconds=12):
    """Listen for the robots' Tuya UDP broadcasts (ports 6666/6667). Returns {device_id: (ip, protocol)}."""
    try:
        import tinytuya.scanner
        found = tinytuya.scanner.devices(verbose=False, scantime=seconds, color=False, poll=False,
                                         byID=True, wantids=list(device_ids), assume_yes=True)
    except Exception as e:
        print(f"Network scan failed ({e}).")
        return {}
    return {i: (d.get("ip"), str(d.get("version") or "3.3")) for i, d in found.items() if i in device_ids}


# ---------------------------------------------------------------- main
def pick_region(user_info, settings):
    tuya_home = (settings.get("setting", {}).get("home_setting", {}) or {}).get("tuya_home", {}) or {}
    region = tuya_home.get("tuya_region_code")
    phone = user_info.get("phone_code") or ""
    country = (user_info.get("country") or "").upper()
    if not region:
        if phone == "1" or country in ("US", "CA"):
            region = "AZ"
        elif phone == "86" or country == "CN":
            region = "AY"
        elif phone == "91" or country == "IN":
            region = "IN"
        else:
            region = "EU"
    if not phone:
        phone = {"AZ": "1", "AY": "86", "IN": "91"}.get(region, "44")
    return region, phone


def main():
    email = input("eufy account email: ").strip()
    password = getpass.getpass("eufy account password (hidden): ")

    login = eufy_login(email, password)
    user = login["user_info"]
    host, uid, token = user["request_host"], user["id"], login["access_token"]

    devices = eufy_get(host, "/v1/device/v2", uid, token).get("devices", [])
    try:
        settings = eufy_get(host, "/v1/user/setting", uid, token)
    except Exception:
        settings = {}
    region, phone = pick_region(user, settings)
    print(f"Logged in. Tuya region {region}, phone code {phone}. {len(devices)} device(s) on account.")

    tuya = Tuya("eh-" + uid, region, user.get("timezone"), phone)
    found = []
    for d in devices:
        if (d.get("product") or {}).get("appliance") != "Cleaning":
            continue
        try:
            info = tuya.get_device(d["id"])
        except Exception as e:
            print(f"  {d.get('alias_name')} ({d['id']}): not found on Tuya ({e})")
            continue
        found.append({
            "name": d.get("alias_name"),
            "model": (d.get("product") or {}).get("product_code"),
            "device_id": d["id"],
            "mac": (d.get("wifi") or {}).get("mac"),
            "local_key": info.get("localKey"),
            "ip": "",
            "protocol": "3.3",
        })
        key = info.get("localKey") or ""
        print(f"  {d.get('alias_name')} model {found[-1]['model']}: local key found ({len(key)} chars)")

    if not found:
        sys.exit("No robot vacuums with a local key were found.")

    # Keep what the user added earlier (map_id, a hand-entered ip) when re-running.
    old = {}
    if OUT_FILE.exists():
        try:
            old = {r["device_id"]: r for r in json.loads(OUT_FILE.read_text())}
        except Exception:
            pass
    print("Listening for the robot on your network (about 12 s)...")
    on_net = find_on_network({r["device_id"] for r in found})
    for r in found:
        prev = old.get(r["device_id"], {})
        if r["device_id"] in on_net:
            r["ip"], r["protocol"] = on_net[r["device_id"]]
            print(f"  {r['name']}: found at {r['ip']} (protocol {r['protocol']})")
        else:
            r["ip"], r["protocol"] = prev.get("ip", ""), prev.get("protocol", "3.3")
            print(f"  {r['name']}: not heard on the network" + (f", keeping saved IP {r['ip']}" if r["ip"] else
                  " - is it on and on this network? You can add \"ip\" to robot_config.json yourself "
                  "(see your router's device list)"))
        if "map_id" in prev:
            r["map_id"] = prev["map_id"]

    OUT_FILE.write_text(json.dumps(found, indent=2))
    print(f"Saved to {OUT_FILE} (contains your local key - keep it private, never commit it).")


if __name__ == "__main__":
    main()
