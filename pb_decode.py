"""Decode the robot's base64 data-point values as raw protobuf (no schema needed).
Usage:  python pb_decode.py DP=VALUE [DP=VALUE ...]     or import decode()
Values are a varint length prefix followed by a protobuf message.
"""
import base64
import sys


def _varint(b, i):
    shift = result = 0
    while True:
        x = b[i]
        i += 1
        result |= (x & 0x7F) << shift
        if not x & 0x80:
            return result, i
        shift += 7


def parse(b):
    """Return list of (field, value) where value is int, bytes, or nested list. Raises on bad data."""
    out, i = [], 0
    while i < len(b):
        key, i = _varint(b, i)
        field, wtype = key >> 3, key & 7
        if field == 0:
            raise ValueError("field 0")
        if wtype == 0:
            v, i = _varint(b, i)
        elif wtype == 1:
            v, i = int.from_bytes(b[i:i + 8], "little"), i + 8
        elif wtype == 5:
            v, i = int.from_bytes(b[i:i + 4], "little"), i + 4
        elif wtype == 2:
            n, i = _varint(b, i)
            if i + n > len(b):
                raise ValueError("overrun")
            raw = b[i:i + n]
            i += n
            try:
                v = parse(raw) if raw else []
            except Exception:
                v = raw
            if isinstance(v, list) and raw and all(32 <= c < 127 for c in raw):
                v = raw  # printable string, keep as text
        else:
            raise ValueError(f"wire type {wtype}")
        out.append((field, v))
    return out


def fmt(msg, indent=0):
    pad = "  " * indent
    lines = []
    for f, v in msg:
        if isinstance(v, list):
            lines.append(f"{pad}{f}: {{" + ("}" if not v else ""))
            if v:
                lines += fmt(v, indent + 1)
                lines.append(pad + "}")
        elif isinstance(v, bytes):
            txt = v.decode("utf-8", "replace") if all(32 <= c < 127 for c in v) else v.hex()
            lines.append(f"{pad}{f}: {txt!r}")
        else:
            extra = ""
            if 1_600_000_000 < v < 2_000_000_000:
                from datetime import datetime
                extra = f"   (time {datetime.fromtimestamp(v):%Y-%m-%d %H:%M:%S})"
            lines.append(f"{pad}{f}: {v}{extra}")
    return lines


def decode(value):
    b = base64.b64decode(value)
    n, i = _varint(b, 0)
    body = b[i:i + n]
    return parse(body)


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        dp, _, val = arg.partition("=")
        print(f"DP {dp}  {val}")
        try:
            print("\n".join(fmt(decode(val), 1)) or "  (empty)")
        except Exception as e:
            print("  could not decode:", e)
        print()
