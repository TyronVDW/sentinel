#!/usr/bin/env python3
"""
Sentinel Relay Client
Connects local machine to the remote Sentinel managed agent.
Usage: python3 relay.py
Requires: ANTHROPIC_API_KEY, config.json in same directory
"""
import json
import os
import sys
import subprocess
import platform
import socket
import threading
import time

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
MAX_OUTPUT  = 50 * 1024   # 50 KB
BETA        = "managed-agents-2026-04-01"


# ── helpers ────────────────────────────────────────────────────────────────────

def load_config():
    if not os.path.exists(CONFIG_PATH):
        print("Error: config.json not found — run setup.py first.", file=sys.stderr)
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)


def detect_shell():
    if platform.system() == "Windows":
        try:
            subprocess.run(["powershell", "-Command", "exit"],
                           capture_output=True, timeout=5)
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

        r = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        out, err = r.stdout, r.stderr
        trunc = False
        if len(out) > MAX_OUTPUT:
            out = out[:MAX_OUTPUT] + f"\n[truncated at {MAX_OUTPUT} bytes]"
            trunc = True
        if len(err) > MAX_OUTPUT:
            err = err[:MAX_OUTPUT] + f"\n[truncated at {MAX_OUTPUT} bytes]"
            trunc = True
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
            return {"content": content[:MAX_OUTPUT] + f"\n[truncated]", "truncated": True}
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
    if name == "run_shell":
        return json.dumps(run_shell(inp["command"], inp.get("timeout", 30)))
    if name == "read_file":
        return json.dumps(read_file(inp["path"]))
    if name == "write_file":
        return json.dumps(write_file(inp["path"], inp["content"]))
    return json.dumps({"error": f"unknown tool: {name}"})


# ── main relay ─────────────────────────────────────────────────────────────────

class SentinelRelay:
    def __init__(self):
        self.cfg = load_config()
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("Error: ANTHROPIC_API_KEY not set.", file=sys.stderr)
            sys.exit(1)

        from anthropic import Anthropic
        self.client   = Anthropic(api_key=api_key)
        self.session  = None
        self.hostname = socket.gethostname()
        self._lock    = threading.Lock()
        self._done    = threading.Event()

    # ── session ────────────────────────────────────────────────────────────────

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
            self.session.id,
            events=events,
            extra_headers={"anthropic-beta": BETA}
        )

    def send_message(self, text):
        self.send_event([{
            "type": "user.message",
            "content": [{"type": "text", "text": text}]
        }])

    def send_tool_result(self, tool_use_id, result_text):
        self.send_event([{
            "type": "user.custom_tool_result",
            "custom_tool_use_id": tool_use_id,
            "content": [{"type": "text", "text": result_text}]
        }])

    # ── stream ─────────────────────────────────────────────────────────────────

    def stream_loop(self):
        """Read SSE events and handle them."""
        try:
            with self.client.beta.sessions.events.stream(
                self.session.id,
                extra_headers={"anthropic-beta": BETA}
            ) as stream:
                for event in stream:
                    etype = getattr(event, "type", None)

                    if etype == "agent.message":
                        for block in getattr(event, "content", []):
                            btype = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
                            if btype == "text":
                                text = getattr(block, "text", None) or (block.get("text","") if isinstance(block, dict) else "")
                                print(text, flush=True)

                    elif etype == "agent.text_delta":
                        delta = getattr(event, "delta", None)
                        text = (delta.get("text","") if isinstance(delta, dict) else getattr(delta,"text","")) if delta else ""
                        print(text, end="", flush=True)

                    elif etype == "agent.text":
                        print(getattr(event, "text", ""), end="", flush=True)

                    elif etype == "agent.custom_tool_use":
                        tid   = getattr(event, "id", None)
                        tname = getattr(event, "name", "")
                        tinp  = getattr(event, "input", {})
                        result = dispatch_tool(tname, tinp if isinstance(tinp, dict) else {})
                        try:
                            self.send_tool_result(tid, result)
                        except Exception as e:
                            print(f"\n[relay error sending tool result: {e}]", file=sys.stderr)

                    elif etype in ("session.status_idle", "session.thread_status_idle"):
                        pass  # idle — ready for next input

        except Exception as e:
            if not self._done.is_set():
                print(f"\n[stream disconnected: {e}]", file=sys.stderr)

    # ── stdin reader ───────────────────────────────────────────────────────────

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

    # ── run ────────────────────────────────────────────────────────────────────

    def run(self):
        self.new_session()

        # Start SSE stream thread first
        t_stream = threading.Thread(target=self.stream_loop, daemon=True)
        t_stream.start()

        # Tiny pause to let stream connect
        time.sleep(0.3)

        # Trigger greeting
        self.send_message("hello")

        # Start stdin reader
        t_stdin = threading.Thread(target=self.stdin_loop, daemon=True)
        t_stdin.start()

        # Wait until stdin closes or stream dies
        self._done.wait()


def main():
    relay = SentinelRelay()
    relay.run()


if __name__ == "__main__":
    main()
