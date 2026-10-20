#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["anthropic"]
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

SENTINEL_TOKEN = "ajjtozFWoeB7VUg3i6cxU6Z7oVoZbmrQR3Dc5pVQreAk7oU4z-_JvN1KZKO6cQ5NAmeSvqqqKn-AYHbQMhfEjSRe5S_wy7m2H8kX1R4593RgmyrsNAeUt6PCR1uLZEchpqvHYHDJVfh_3fCzUTfg5vXCpiSeSN9aV7xDbestDySxWGqH1StZcz5tCW11hshq5JzFi23SJnMShz4sLtnJqyZSoX5Ds9oTJ2gMnu58IHlQZl_uQiXQdYL_fRcc7Ecw4Fph4kJF-K8e9mV1rOjuUYAbg_0LUaTwPhezAoB3F_vYIke4ZEIMIWa9yZkqKJz_BFjYd1ofL0ZKAKlbOk8QRH_PtPOBoO1Y0NFVZGDwjOh9_6g_vmZAhNY"
SALT        = b'sentinel_v1_salt'
MAX_OUTPUT  = 50 * 1024
BETA        = "managed-agents-2026-04-01"
ENV_PW_KEY  = "SENTINEL_PASSWORD"


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
            return cfg

    # Ask for password
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


# ── relay ──────────────────────────────────────────────────────────────────────

class SentinelRelay:
    def __init__(self, cfg):
        self.cfg      = cfg
        self.hostname = socket.gethostname()
        self._done    = threading.Event()

        from anthropic import Anthropic
        self.client  = Anthropic(api_key=cfg["api_key"])
        self.session = None

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
                                print(text, flush=True)

                    elif etype == "agent.text_delta":
                        delta = getattr(event, "delta", None)
                        text  = (delta.get("text", "") if isinstance(delta, dict) else getattr(delta, "text", "")) if delta else ""
                        print(text, end="", flush=True)

                    elif etype == "agent.custom_tool_use":
                        tid    = getattr(event, "id", None)
                        tname  = getattr(event, "name", "")
                        tinp   = getattr(event, "input", {})
                        result = dispatch_tool(tname, tinp if isinstance(tinp, dict) else {})
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
            self._done.set()

    def run(self):
        self.new_session()
        t_stream = threading.Thread(target=self.stream_loop, daemon=True)
        t_stream.start()
        time.sleep(0.3)
        self.send_message("hello")
        t_stdin = threading.Thread(target=self.stdin_loop, daemon=True)
        t_stdin.start()
        self._done.wait()


def main():
    cfg = get_config()
    relay = SentinelRelay(cfg)
    relay.run()


if __name__ == "__main__":
    main()
