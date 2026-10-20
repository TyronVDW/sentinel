#!/usr/bin/env python3
"""
Sentinel Setup - Run once to create the managed agent.
Usage: python3 setup.py
Requires: ANTHROPIC_API_KEY environment variable
"""
import json
import os
import sys

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        return 1

    try:
        from anthropic import Anthropic
    except ImportError:
        print("Error: anthropic SDK not installed. Run: pip install anthropic")
        return 1

    client = Anthropic(api_key=api_key)
    beta = "managed-agents-2026-04-01"

    # Read system prompt
    prompt_path = os.path.join(os.path.dirname(__file__), "prompt.md")
    with open(prompt_path, "r") as f:
        system_prompt = f.read()

    print("Creating Sentinel agent infrastructure...")

    # 1. Create memory store
    print("  [1/3] Creating memory store...")
    memory_store = client.beta.memory_stores.create(
        name="sentinel-machines",
        extra_headers={"anthropic-beta": beta}
    )
    memory_store_id = memory_store.id
    print(f"         Memory store: {memory_store_id}")

    # 2. Create cloud environment
    print("  [2/3] Creating cloud environment...")
    environment = client.beta.environments.create(
        name="sentinel-env",
        config={"type": "cloud", "networking": {"type": "limited"}},
        extra_headers={"anthropic-beta": beta}
    )
    env_id = environment.id
    print(f"         Environment: {env_id}")

    # 3. Create agent with custom tools, bash disabled
    print("  [3/3] Creating agent...")
    agent = client.beta.agents.create(
        name="Sentinel",
        model="claude-opus-5-5",
        system=system_prompt,
        tools=[
            {
                "type": "agent_toolset_20260401",
                "configs": [
                    {"name": "bash",       "enabled": False},
                    {"name": "web_search", "enabled": True},
                    {"name": "web_fetch",  "enabled": True},
                ]
            },
            {
                "type": "custom",
                "name": "run_shell",
                "description": (
                    "Execute a shell command on the client machine. "
                    "Returns stdout, stderr, and exit code. "
                    "Runs in PowerShell on Windows, sh/bash on Unix."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The shell command to execute"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Timeout in seconds (default 30)",
                            "default": 30
                        }
                    },
                    "required": ["command"]
                }
            },
            {
                "type": "custom",
                "name": "read_file",
                "description": "Read the contents of a file from the client machine.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Full path to the file to read"
                        }
                    },
                    "required": ["path"]
                }
            },
            {
                "type": "custom",
                "name": "write_file",
                "description": "Write content to a file on the client machine. Creates or overwrites the file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Full path to the file to write"
                        },
                        "content": {
                            "type": "string",
                            "description": "Content to write to the file"
                        }
                    },
                    "required": ["path", "content"]
                }
            }
        ],
        extra_headers={"anthropic-beta": beta}
    )
    agent_id = agent.id
    print(f"         Agent: {agent_id}")

    # Save configuration
    config = {
        "agent_id": agent_id,
        "env_id": env_id,
        "memory_store_id": memory_store_id
    }
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print("\n✓ Setup complete!")
    print(f"  config.json written to: {config_path}")
    print("\nNext step: distribute relay.py + config.json to your machines")
    print("  Unix:    curl -sSL <your-url>/install.sh | sh")
    print("  Windows: irm <your-url>/install.ps1 | iex")
    return 0

if __name__ == "__main__":
    sys.exit(main())
