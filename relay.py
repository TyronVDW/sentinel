#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["anthropic", "websocket-client"]
# ///
"""
Sentinel Relay Client
Usage: python3 relay.py
"""
import json
import os
import sys
import subprocess
import platform
import socket
import threading
import time
import base64
import getpass
import hashlib
import struct
from urllib.parse import quote

try:
    import websocket  # websocket-client (optional; hub features disabled if missing)
except Exception:
    websocket = None

SENTINEL_TOKEN = "VCgM03D-YI-Tn_s1-ZjhgDzEpgdbajHECIdslBgU-fIzhpEgOXl5gmXCwQ3zmkGqwC3CLzgGJMLChYTy-O3aYgfngyF-XrE1ABZiBiDWBiBtpO2c1zP-ir2rrmUfZ3nAs3bBw7nctjb_KPzrkxalsRWjS2fMEwDpZPBH29-WHBgCWCJ-lmdkjJ1ZViymU1jLHO3zU6rJ0xYzhe7xNbWr-jVvz-kiac6qcZjGmQxpPm_AEQG1txXw6YKJWfekr8sXK-7Y7hQ0Qm5JVEKMnu8B0M1bz103BbJHt4u2j1sihjB71EJMaomal6SvZm3xIIsv1HdLADjP4hrfJEKbo0JPUjsji0h6BC0lRt0TF9w8JW28Nmle6PsClRI"
SALT        = b'sentinel_v1_salt'
HUB_SALT    = "sentinel_hub_v1"
MAX_OUTPUT  = 50 * 1024
BETA        = "managed-agents-2026-04-01"
ENV_PW_KEY  = "SENTINEL_PASSWORD"

# Cloudflare hub. Leave blank to run purely local (terminal only).
# After deploying the hub, set this to  wss://<your-worker>.workers.dev/ws
# or export SENTINEL_HUB_URL to override without editing this file.
HUB_URL = "wss://sentinel-hub.tyvdw.workers.dev/ws"


def derive_key(password: str) -> bytes:
    return hashlib.pbkdf2_hmac('sha256', password.encode(), SALT, 480000)


def keystream(key: bytes, iv: bytes, length: int) -> bytes:
    seed = hashlib.sha256(key + iv).digest()
    out = b''
    i = 0
    while len(out) < length:
        out += hashlib.sha256(seed + struct.pack('>I', i)).digest()
        i += 1
    return out[:length]


def unlock(password: str) -> dict:
    try:
        pad = SENTINEL_TOKEN + '=' * (-len(SENTINEL_TOKEN) % 4)
        raw = base64.urlsafe_b64decode(pad)
        iv, ct = raw[:16], raw[16:]
        key = derive_key(password)
        pt = bytes(a ^ b for a, b in zip(ct, keystream(key, iv, len(ct))))
        return json.loads(pt.decode())
    except Exception:
        return None


def derive_hub_token(password: str) -> str:
    """Token the hub checks. Matches the dashboard's SHA-256(password+salt)."""
    d = hashlib.sha256((password + HUB_SALT).encode()).digest()
    return base64.urlsafe_b64encode(d).rstrip(b'=').decode()


def save_password(password: str):
    """Persist password to user environment (Windows) or shell profile (Unix)."""
    if platform.system() == "Windows":
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f'[System.Environment]::SetEnvironmentVariable("SENTINEL_PASSWORD", "{password}", "User")'],
            capture_output=True
        )
    else:
        for profile in [os.path.expanduser("~/.zshrc"),
                        os.path.expanduser("~/.bashrc"),
                        os.path.expanduser("~/.profile")]:
            if os.path.exists(profile):
                with open(profile, "a") as f:
                    f.write(f'\nexport SENTINEL_PASSWORD="{password}"\n')
                break


def get_config() -> dict:
    password = os.environ.get(ENV_PW_KEY, "")
    if password:
        cfg = unlock(password)
        if cfg:
            cfg["_password"] = password
            return cfg

    try:
        password = getpass.getpass("Sentinel password: ")
    except EOFError:
        print("\nNo input stream available for the password prompt "
              "(stdin isn't a terminal). Run 'sentinel' directly in your shell.",
              file=sys.stderr)
        sys.exit(1)

    if not password:
        print("No password entered.", file=sys.stderr)
        sys.exit(1)

    cfg = unlock(password)
    if not cfg:
        print("Incorrect password.", file=sys.stderr)
        sys.exit(1)

    save_password(password)
    os.environ[ENV_PW_KEY] = password
    cfg["_password"] = password
    return cfg


# ── shell helpers ──────────────────────────────────────────────────────────────

def detect_shell():
    if platform.system() == "Windows":
        try:
            subprocess.run(["powershell", "-Command", "exit"], capture_output=True, timeout=5)
            return "powershell"
        except Exception:
            return "cmd"
    return "sh"


def run_shell(command, timeout=30):
    shell = detect_shell()
    try:
        if shell == "powershell":
            args = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
        elif shell == "cmd":
            args = ["cmd", "/c", command]
        else:
            args = ["sh", "-c", command]
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, errors="replace")
        out, err = r.stdout, r.stderr
        trunc = False
        if len(out) > MAX_OUTPUT:
            out = out[:MAX_OUTPUT] + f"\n[truncated]"; trunc = True
        if len(err) > MAX_OUTPUT:
            err = err[:MAX_OUTPUT] + f"\n[truncated]"; trunc = True
        return {"stdout": out, "stderr": err, "exit_code": r.returncode, "truncated": trunc}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"Timed out after {timeout}s", "exit_code": -1, "truncated": False}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "exit_code": -1, "truncated": False}


def read_file(path):
    try:
        with open(path, "r", errors="replace") as f:
            content = f.read()
        if len(content) > MAX_OUTPUT:
            return {"content": content[:MAX_OUTPUT] + "\n[truncated]", "truncated": True}
        return {"content": content, "truncated": False}
    except Exception as e:
        return {"error": str(e)}


def write_file(path, content):
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}


def dispatch_tool(name, inp):
    if name == "run_shell":  return json.dumps(run_shell(inp["command"], inp.get("timeout", 30)))
    if name == "read_file":  return json.dumps(read_file(inp["path"]))
    if name == "write_file": return json.dumps(write_file(inp["path"], inp["content"]))
    return json.dumps({"error": f"unknown tool: {name}"})


# ── hub client (optional) ────────────────────────────────────────────────────────

class HubClient:
    """Keeps a WebSocket to the Cloudflare hub. Reconnects forever.
    Forwards agent output up; delivers dashboard messages via on_text."""

    def __init__(self, url, on_text):
        self.url = url
        self.on_text = on_text
        self.ws = None
        self._connected = False
        self._stop = False

    def _on_open(self, ws):
        self._connected = True

    def _on_close(self, ws, *a):
        self._connected = False

    def _on_error(self, ws, err):
        self._connected = False

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
        except Exception:
            return
        if data.get("type") == "message":
            txt = data.get("text", "")
            if txt and self.on_text:
                try:
                    self.on_text(txt)
                except Exception:
                    pass

    def run_forever(self):
        while not self._stop:
            try:
                self.ws = websocket.WebSocketApp(
                    self.url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_close=self._on_close,
                    on_error=self._on_error,
                )
                self.ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception:
                pass
            self._connected = False
            if self._stop:
                break
            time.sleep(5)

    def send(self, obj):
        if not self._connected or not self.ws:
            return
        try:
            self.ws.send(json.dumps(obj))
        except Exception:
            self._connected = False

    def send_output(self, text):
        if text:
            self.send({"type": "output", "text": text})


# ── relay ──────────────────────────────────────────────────────────────────────

class SentinelRelay:
    def __init__(self, cfg):
        self.cfg      = cfg
        self.hostname = socket.gethostname()
        self._done    = threading.Event()

        from anthropic import Anthropic
        self.client  = Anthropic(api_key=cfg["api_key"])
        self.session = None

        # Optional hub
        self.hub = None
        hub_url = os.environ.get("SENTINEL_HUB_URL", HUB_URL).strip()
        password = cfg.get("_password", "")
        if hub_url and password and websocket is not None:
            os_name = f"{platform.system()} {platform.release()}".strip()
            token = derive_hub_token(password)
            full = (f"{hub_url}?role=relay"
                    f"&machine={quote(self.hostname)}"
                    f"&os={quote(os_name)}"
                    f"&token={quote(token)}")
            self.hub = HubClient(full, on_text=self._on_hub_message)

    def _on_hub_message(self, text):
        self.send_message(text)

    def new_session(self):
        self.session = self.client.beta.sessions.create(
            agent={"type": "agent", "id": self.cfg["agent_id"]},
            environment_id=self.cfg["env_id"],
            resources=[{
                "type": "memory_store",
                "memory_store_id": self.cfg["memory_store_id"],
                "access": "read_write",
                "instructions": (
                    f"Maintain one file per machine keyed by hostname. "
                    f"Current machine hostname: {self.hostname}. "
                    "Track past issues, resolutions, installed software and preferences."
                )
            }],
            extra_headers={"anthropic-beta": BETA}
        )

    def send_event(self, events):
        self.client.beta.sessions.events.send(
            self.session.id, events=events,
            extra_headers={"anthropic-beta": BETA}
        )

    def send_message(self, text):
        self.send_event([{"type": "user.message", "content": [{"type": "text", "text": text}]}])

    def send_tool_result(self, tool_use_id, result_text):
        self.send_event([{
            "type": "user.custom_tool_result",
            "custom_tool_use_id": tool_use_id,
            "content": [{"type": "text", "text": result_text}]
        }])

    def emit(self, text, end="\n"):
        """Print locally and mirror to the hub."""
        print(text, end=end, flush=True)
        if self.hub:
            self.hub.send_output(text)

    def stream_loop(self):
        try:
            with self.client.beta.sessions.events.stream(
                self.session.id, extra_headers={"anthropic-beta": BETA}
            ) as stream:
                for event in stream:
                    etype = getattr(event, "type", None)

                    if etype == "agent.message":
                        for block in getattr(event, "content", []):
                            btype = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
                            if btype == "text":
                                text = getattr(block, "text", None) or (block.get("text", "") if isinstance(block, dict) else "")
                                self.emit(text)

                    elif etype == "agent.text_delta":
                        delta = getattr(event, "delta", None)
                        text  = (delta.get("text", "") if isinstance(delta, dict) else getattr(delta, "text", "")) if delta else ""
                        print(text, end="", flush=True)

                    elif etype == "agent.custom_tool_use":
                        tid    = getattr(event, "id", None)
                        tname  = getattr(event, "name", "")
                        tinp   = getattr(event, "input", {})
                        tinp   = tinp if isinstance(tinp, dict) else {}
                        if self.hub and tname == "run_shell" and tinp.get("command"):
                            self.hub.send_output(">> " + str(tinp["command"]))
                        result = dispatch_tool(tname, tinp)
                        try:
                            self.send_tool_result(tid, result)
                        except Exception as e:
                            print(f"\n[relay error: {e}]", file=sys.stderr)

                    elif etype in ("session.status_idle", "session.thread_status_idle"):
                        pass

        except Exception as e:
            if not self._done.is_set():
                print(f"\n[stream error: {e}]", file=sys.stderr)

    def stdin_loop(self):
        try:
            while True:
                line = sys.stdin.readline()
                if not line:
                    break
                line = line.rstrip("\n")
                if line.strip():
                    self.send_message(line)
        except Exception:
            pass
        finally:
            # With a hub attached the relay stays up (driven from the web) even
            # when there is no local terminal; only local-only mode exits on EOF.
            if not self.hub:
                self._done.set()

    def run(self):
        if self.hub:
            threading.Thread(target=self.hub.run_forever, daemon=True).start()
        threading.Thread(target=self.stdin_loop, daemon=True).start()

        # Supervisor: keep a live session. If the event stream ends or errors
        # (network blip, idle timeout), re-establish it rather than sitting
        # "online" but unresponsive. The hub connection is independent and
        # stays up across these reconnects, so the dashboard keeps showing the
        # machine as online.
        first = True
        while not self._done.is_set():
            try:
                self.new_session()
                if first:
                    time.sleep(0.3)
                    self.send_message("hello")
                    first = False
                self.stream_loop()  # blocks until the event stream ends/errors
            except Exception as e:
                print(f"\n[session error: {e}]", file=sys.stderr)
            if self._done.is_set():
                break
            time.sleep(10)  # backoff, then re-establish the session


def main():
    cfg = get_config()
    relay = SentinelRelay(cfg)
    relay.run()


if __name__ == "__main__":
    main()
