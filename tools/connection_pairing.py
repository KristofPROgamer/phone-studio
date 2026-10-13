"""Private, bounded notebook connection codes. Importing this module does no setup.

Codes contain the existing credentials. They are a local transfer format, not an
authentication bypass, public URL or remotely hosted QR service.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import html
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import unquote, urlsplit, urlunsplit
import uuid

PREFIX = "PHONE-STUDIO:1:"
MAX_CODE_LENGTH = 8192
MAX_PAYLOAD_BYTES = 4096
QR_PACKAGE = "qrcode==8.2"
_FIELDS = {"version", "kind", "name", "serverUrl", "tunnelUser", "tunnelPassword", "studioToken", "workerId"}


class PairingError(ValueError):
    """Messages deliberately never include the supplied code or credentials."""


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PairingError("Connection code contains duplicate fields.")
        result[key] = value
    return result


def _text(value, label, limit, *, trimmed=False):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 or 0xD800 <= ord(char) <= 0xDFFF for char in value)
            or (trimmed and value != value.strip())):
        raise PairingError(f"Connection {label} is invalid.")
    return value


def _token(value):
    value = _text(value, "token", 512, trimmed=True)
    if any(not 32 <= ord(char) <= 126 for char in value):
        raise PairingError("Connection token must use visible ASCII text for the authenticated header.")
    return value


def clean_server_url(value):
    value = _text(value, "address", 2048, trimmed=True)
    if not value.startswith("https://") or any(char.isspace() for char in value) or "\\" in value:
        raise PairingError("Use a clean HTTPS server address.")
    try:
        parsed = urlsplit(value)
        hostname, port = parsed.hostname, parsed.port
    except ValueError:
        raise PairingError("Use a clean HTTPS server address.") from None
    if (parsed.scheme != "https" or not hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or "?" in value or "#" in value
            or not re.fullmatch(r"[A-Za-z0-9.:-]+", hostname)
            or (port is not None and not 1 <= port <= 65535)):
        raise PairingError("Use a clean HTTPS server address without credentials or query fields.")
    try:
        if ":" in hostname:
            ipaddress.IPv6Address(hostname)
        elif (len(hostname) > 253 or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                                      for label in hostname.removesuffix(".").split("."))):
            raise ValueError
        if parsed.netloc.endswith(":"):
            raise ValueError
    except ValueError:
        raise PairingError("Connection address host is invalid.") from None
    try:
        decoded_path = unquote(parsed.path, encoding="utf-8", errors="strict")
    except UnicodeError:
        raise PairingError("Connection address path encoding is invalid.") from None
    if ("\\" in decoded_path or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in decoded_path)
            or any(part in (".", "..") for part in decoded_path.split("/"))
            or re.search(r"%(?![0-9A-Fa-f]{2})", parsed.path)):
        raise PairingError("Connection address path is invalid.")
    host = "[" + hostname.lower() + "]" if ":" in hostname else hostname.lower().removesuffix(".")
    netloc = host + (":" + str(port) if port is not None and port != 443 else "")
    return urlunsplit(("https", netloc, parsed.path.rstrip("/"), "", ""))


def validate_pairing(body, *, expected_kind=None):
    if not isinstance(body, dict) or set(body) - _FIELDS:
        raise PairingError("Connection code contains unsupported fields.")
    if type(body.get("version")) is not int or body["version"] != 1:
        raise PairingError("Connection code version is unsupported.")
    kind = body.get("kind")
    if kind not in ("router", "worker"):
        raise PairingError("Connection code has an invalid role.")
    if expected_kind is not None and kind != expected_kind:
        raise PairingError("Use a router code for the phone or worker codes for the router.")
    required = _FIELDS - {"workerId"}
    if not required <= set(body) or (kind == "router" and "workerId" in body):
        raise PairingError("Connection code fields do not match its role.")
    result = {"version": 1, "kind": kind,
              "name": _text(body["name"], "name", 80, trimmed=True),
              "serverUrl": clean_server_url(body["serverUrl"]),
              "tunnelUser": _text(body["tunnelUser"], "user", 128, trimmed=True),
              "tunnelPassword": _text(body["tunnelPassword"], "password", 512),
              "studioToken": _token(body["studioToken"])}
    if ":" in result["tunnelUser"]:
        raise PairingError("Connection user cannot contain a colon.")
    if kind == "worker":
        worker_id = body.get("workerId")
        if not isinstance(worker_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", worker_id):
            raise PairingError("Connection worker ID is invalid.")
        result["workerId"] = worker_id
    return result


def encode_pairing(body):
    value = json.dumps(validate_pairing(body), ensure_ascii=False, separators=(",", ":"))
    data = value.encode("utf-8")
    if len(data) > MAX_PAYLOAD_BYTES:
        raise PairingError("Connection code is too large.")
    return PREFIX + base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def decode_pairing(code, *, expected_kind=None):
    if not isinstance(code, str) or len(code) > MAX_CODE_LENGTH:
        raise PairingError("Connection code is missing or too large.")
    code = code.strip()
    if not code.startswith(PREFIX):
        raise PairingError("Paste a Phone Studio connection code.")
    encoded = code[len(PREFIX):]
    if not encoded or not re.fullmatch(r"[A-Za-z0-9_-]+", encoded):
        raise PairingError("Connection code encoding is invalid.")
    try:
        data = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        if len(data) > MAX_PAYLOAD_BYTES:
            raise PairingError("Connection code is too large.")
        if base64.urlsafe_b64encode(data).decode("ascii").rstrip("=") != encoded:
            raise PairingError("Connection code encoding is invalid.")
        body = json.loads(data.decode("utf-8", errors="strict"), object_pairs_hook=_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(PairingError("Connection code JSON is invalid.")))
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, PairingError):
            raise
        raise PairingError("Connection code encoding or JSON is invalid.") from None
    return validate_pairing(body, expected_kind=expected_kind)


def workers_from_codes(text):
    if not isinstance(text, str) or len(text) > MAX_CODE_LENGTH * 3 + 8:
        raise PairingError("Provide one to three private worker codes, one per line.")
    codes = [line.strip() for line in text.splitlines() if line.strip()]
    if not 1 <= len(codes) <= 3:
        raise PairingError("Provide one to three private worker codes, one per line.")
    entries = []
    ids, addresses = set(), set()
    for code in codes:
        body = decode_pairing(code, expected_kind="worker")
        if body["workerId"] in ids or body["serverUrl"] in addresses:
            raise PairingError("Worker codes must have distinct IDs and server addresses.")
        ids.add(body["workerId"])
        addresses.add(body["serverUrl"])
        entries.append({key: value for key, value in body.items() if key not in ("version", "kind")})
    return entries


@contextmanager
def _credential_lock(path, timeout):
    if not isinstance(timeout, (int, float)) or not 0 <= timeout <= 30:
        raise PairingError("Credential preparation timeout is invalid.")
    owner = uuid.uuid4().hex
    deadline = time.monotonic() + timeout
    while True:
        if path.is_symlink():
            raise PairingError("Private credential lock is a symlink; preserve it and inspect it privately.")
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="ascii") as output:
                output.write(owner)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise PairingError("Another router owns credential preparation; preserve its lock and finish that preparation.") from None
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    try:
        yield
    finally:
        try:
            if not path.is_symlink() and path.read_text(encoding="ascii") == owner:
                path.unlink()
        except (OSError, UnicodeError):
            pass


def load_router_credentials(path, token_secret="", password_secret="", *, timeout=10):
    """Keep existing Secrets; generate missing credentials once under persistent state.

    Per-notebook Secret overrides never overwrite an existing stored credential file.
    Unknown/corrupt files and occupied locks are preserved rather than reset.
    """
    if not isinstance(token_secret, str) or not isinstance(password_secret, str):
        raise PairingError("Provided router credentials are invalid.")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _credential_lock(path.with_name(path.name + ".lock"), timeout):
        if path.is_symlink():
            raise PairingError("Private credential file is a symlink; preserve it and inspect it privately.")
        try:
            if path.stat().st_size > MAX_PAYLOAD_BYTES:
                raise PairingError("Stored router credentials are invalid; the file was preserved.")
            stored = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object)
            if not isinstance(stored, dict) or set(stored) != {"version", "phone_studio_token", "tunnel_password"} or type(stored["version"]) is not int or stored["version"] != 1:
                raise PairingError("Stored router credentials are invalid; the file was preserved.")
            _token(stored["phone_studio_token"])
            _text(stored["tunnel_password"], "stored password", 512)
        except FileNotFoundError:
            stored = None
        except (OSError, ValueError, UnicodeError):
            raise PairingError("Stored router credentials cannot be read; preserve the file and inspect it privately.") from None
        token = _token(token_secret or (stored or {}).get("phone_studio_token") or secrets.token_urlsafe(32))
        password = _text(password_secret or (stored or {}).get("tunnel_password") or secrets.token_urlsafe(24), "password", 512)
        if stored is None:
            staging = path.with_name(path.name + "." + uuid.uuid4().hex + ".part")
            try:
                descriptor = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                    json.dump({"version": 1, "phone_studio_token": token, "tunnel_password": password}, output)
                staging.replace(path)
            finally:
                staging.unlink(missing_ok=True)
        return token, password


def pairing_html(body, *, with_qr=True):
    """Local SVG only. Missing QR package/capacity never blocks paste-code pairing."""
    value = validate_pairing(body)
    code = encode_pairing(value)
    qr_html = ""
    if with_qr:
        try:
            import qrcode
            from qrcode.image.svg import SvgPathFillImage
            qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=6, border=4)
            qr.add_data(code, optimize=0)
            qr.make(fit=True)
            svg = qr.make_image(image_factory=SvgPathFillImage).to_string(encoding="unicode")
            qr_html = '<div style="background:white;padding:12px;max-width:480px">' + svg + '</div>'
        except Exception:
            qr_html = '<p>QR preview is unavailable. Use the private code below.</p>'
    action = "Scan in Phone Studio → Connect" if value["kind"] == "router" else "Copy into the router’s PHONE_STUDIO_WORKER_CODES Secret"
    return ('<section style="font-family:system-ui;padding:16px;border:1px solid #b7c6d6;border-radius:16px">'
            '<h3>' + html.escape(action) + '</h3><p>' + html.escape(value["name"]) + ' · '
            + html.escape(value["serverUrl"]) + '</p><p>Private: this code contains connection credentials. '
            'Keep this notebook output private and clear outputs before sharing.</p>' + qr_html
            + '<details><summary>Reveal private connection code for copy/paste</summary>'
            '<textarea readonly rows="5" style="width:100%;box-sizing:border-box;margin-top:12px">'
            + html.escape(code) + '</textarea></details></section>')


def display_pairing(body, *, with_qr=True):
    from IPython.display import HTML, display
    display(HTML(pairing_html(body, with_qr=with_qr)))
