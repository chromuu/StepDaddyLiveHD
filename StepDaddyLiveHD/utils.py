import os
import re
import base64
import json
import gzip
import hashlib
import io
import struct
import tempfile

from PIL import Image

KEY_FILE = os.environ.get("URL_KEY_FILE", ".url_key")


def _load_key_bytes() -> bytes:
    """Key that obscures upstream URLs inside /key and /content links.

    It must be identical in every backend worker and survive restarts, or
    players holding links issued earlier get undecryptable URLs. URL_SECRET
    pins it explicitly; otherwise it is generated once and kept in KEY_FILE.
    """
    secret = os.environ.get("URL_SECRET", "")
    if secret:
        return hashlib.sha512(secret.encode()).digest()
    try:
        with open(KEY_FILE, "rb") as f:
            key = f.read()
        if len(key) == 64:
            return key
    except OSError:
        pass
    # Write to a temp file and link it into place: link fails if another
    # worker won the race, and then everyone uses that worker's key.
    key = os.urandom(64)
    directory = os.path.dirname(os.path.abspath(KEY_FILE))
    fd, tmp = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        os.link(tmp, KEY_FILE)
    except FileExistsError:
        with open(KEY_FILE, "rb") as f:
            existing = f.read()
        if len(existing) == 64:
            key = existing
        else:  # corrupt or truncated: replace it
            os.replace(tmp, KEY_FILE)
            return key
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return key


key_bytes = _load_key_bytes()


def encrypt(input_string: str):
    input_bytes = input_string.encode()
    result = xor(input_bytes)
    return base64.urlsafe_b64encode(result).decode().rstrip('=')


def decrypt(input_string: str):
    padding_needed = 4 - (len(input_string) % 4)
    if padding_needed:
        input_string += '=' * padding_needed
    input_bytes = base64.urlsafe_b64decode(input_string)
    result = xor(input_bytes)
    return result.decode()


def xor(input_bytes):
    return bytes([input_bytes[i] ^ key_bytes[i % len(key_bytes)] for i in range(len(input_bytes))])


def urlsafe_base64(input_string: str) -> str:
    input_bytes = input_string.encode("utf-8")
    base64_bytes = base64.urlsafe_b64encode(input_bytes)
    base64_string = base64_bytes.decode("utf-8")
    return base64_string


def urlsafe_base64_decode(base64_string: str) -> str:
    padding = '=' * (-len(base64_string) % 4)
    base64_string_padded = base64_string + padding
    base64_bytes = base64_string_padded.encode("utf-8")
    decoded_bytes = base64.urlsafe_b64decode(base64_bytes)
    return decoded_bytes.decode("utf-8")


def extract_and_decode_var(var_name: str, response: str) -> str:
    pattern = rf'var\s+{re.escape(var_name)}\s*=\s*atob\("([^"]+)"\);'
    matches = re.findall(pattern, response)
    if not matches:
        raise ValueError(f"Variable '{var_name}' not found in response")
    b64 = matches[-1]
    return base64.b64decode(b64).decode("utf-8")


def decode_bundle(response_text: str) -> dict:
    candidates = set()
    candidates.update(re.findall(r'JSON\.parse\s*\(\s*atob\s*\(\s*["\']([^"\']{40,})["\']\s*\)\s*\)', response_text))
    candidates.update(re.findall(r'atob\s*\(\s*["\'](eyJ[A-Za-z0-9+/=]{40,})["\']\s*\)', response_text))
    candidates.update(re.findall(r'(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*["\'](eyJ[A-Za-z0-9+/=]{40,})["\']', response_text))
    candidates.update(re.findall(r'["\'](eyJ[A-Za-z0-9+/=]{40,})["\']', response_text))
    candidates.update(re.findall(r'["\']([A-Za-z0-9+/=]{80,})["\']', response_text))

    for candidate in candidates:
        try:
            decoded_candidate = base64.b64decode(candidate).decode("utf-8")
            data = json.loads(decoded_candidate)
            if not all(key in data for key in ['b_ts', 'b_sig', 'b_rnd', 'b_host']):
                continue
            decoded = {}
            for k, v in data.items():
                if isinstance(v, str):
                    try:
                        pad = '=' * (-len(v) % 4)
                        decoded[k] = base64.b64decode(v + pad).decode("utf-8")
                    except Exception:
                        decoded[k] = v
                else:
                    decoded[k] = v
            return decoded
        except Exception:
            continue
    return {}


def _b64_text(value: str) -> str:
    value = value.strip()
    return base64.b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")


def decode_econfig(blob: str) -> dict:
    """Decode the ``window._econfig`` blob from the embed page.

    Mirrors the player JS: base64-decode, split into 4 equal chunks, drop the
    4th character of each chunk, base64-decode each chunk, reorder them as
    [2, 0, 3, 1], join, base64-decode once more and parse as JSON.
    """
    order = [2, 0, 3, 1]
    outer = _b64_text(blob)
    chunk_len = len(outer) // len(order)
    parts = [None] * len(order)
    for i, target in enumerate(order):
        chunk = outer[i * chunk_len:(i + 1) * chunk_len]
        chunk = chunk[:3] + chunk[4:]
        parts[target] = _b64_text(chunk)
    return json.loads(_b64_text("".join(parts)))


TS_SYNC = 0x47
TS_PACKET = 188
TPIX = b"TIKTIKPX"
TRAW = b"TIKTIKRAW"
TSGZ = b"TIKTIKTSGZ"


def _looks_like_ts(data: bytes, start: int = 0) -> bool:
    return (len(data) > start + TS_PACKET and data[start] == TS_SYNC
            and data[start + TS_PACKET] == TS_SYNC)


def _webp_exif_ts(data: bytes) -> bytes | None:
    if len(data) < 16 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    off = 12
    while off + 8 <= len(data):
        tag = data[off:off + 4]
        (n,) = struct.unpack("<I", data[off + 4:off + 8])
        off += 8
        if off + n > len(data):
            return None
        if tag == b"EXIF":
            chunk = data[off:off + n]
            return chunk if _looks_like_ts(chunk) else None
        off += n + (n & 1)
    return None


def _png_trailer_ts(data: bytes) -> bytes | None:
    off = 8
    while off + 8 <= len(data):
        (n,) = struct.unpack(">I", data[off:off + 4])
        if n > len(data) - off - 12:
            return None
        chunk_type = data[off + 4:off + 8]
        off += 12 + n
        if chunk_type == b"IEND":
            return data[off:] if _looks_like_ts(data, off) else None
    return None


def _png_pixels_ts(data: bytes) -> bytes | None:
    image = Image.open(io.BytesIO(data))
    if image.mode not in ("RGB", "RGBA"):
        return None
    rgb = image.convert("RGB").tobytes()
    if rgb[:8] != TPIX:
        return None
    (n,) = struct.unpack(">I", rgb[8:12])
    gz = rgb[12:12 + n]
    if n <= 0 or len(gz) < n or gz[:2] != b"\x1f\x8b":
        return None
    ts = gzip.decompress(gz)
    return ts if ts and ts[0] == TS_SYNC else None


def unwrap_segment(data: bytes) -> bytes:
    """Recover the MPEG-TS payload from a segment the CDN disguises as an image.

    Mirrors the embed player's ``unwrap()``: TS hidden in a WebP EXIF chunk,
    appended after a PNG's IEND, packed into PNG pixels (``TIKTIKPX`` + length
    + gzip), or after a ``TIKTIKRAW``/``TIKTIKTSGZ`` marker. Plain TS is
    returned unchanged. Raises ValueError if no payload is found.
    """
    if _looks_like_ts(data):
        return data
    ts = _webp_exif_ts(data)
    if ts:
        return ts
    if data[:2] == b"\x89P":
        ts = _png_trailer_ts(data) or _png_pixels_ts(data)
        if ts:
            return ts
        raise ValueError("TS payload not found in PNG")
    i = data.find(TRAW)
    if i != -1 and data[i + len(TRAW):i + len(TRAW) + 1] == bytes([TS_SYNC]):
        return data[i + len(TRAW):]
    i = data.find(TSGZ)
    if i != -1:
        return gzip.decompress(data[i + len(TSGZ):])
    i = data.find(bytes([TS_SYNC]))
    while i != -1:
        if _looks_like_ts(data, i):
            return data[i:]
        i = data.find(bytes([TS_SYNC]), i + 1)
    raise ValueError("TS payload not found")
