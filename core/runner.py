"""Subprocess and Docker runner for antigravity-operator.

Provides live streaming of agent actions, tool executions (ffmpeg, ffprobe, etc.),
and real-time progress parsing from container NDJSON events.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from typing import Sequence

CLR_RESET = "\033[0m"
CLR_BOLD = "\033[1m"
CLR_CYAN = "\033[1;36m"
CLR_GREEN = "\033[1;32m"
CLR_YELLOW = "\033[1;33m"
CLR_RED = "\033[1;31m"
CLR_DIM = "\033[2m"


def format_stream_line(line: str) -> None:
    """Format and print an NDJSON event from agy in human-readable real-time format."""
    line = line.strip()
    if not line:
        return

    # Non-JSON lines (e.g. docker or system warnings)
    if not line.startswith("{") or not line.endswith("}"):
        print(line)
        sys.stdout.flush()
        return

    try:
        data = json.loads(line)
    except Exception:
        print(line)
        sys.stdout.flush()
        return

    event = data.get("event")

    if event == "step_update":
        update = data.get("step_update", {})
        step_type = update.get("step_type")

        if step_type == "tool":
            state = update.get("state")
            tool_name = update.get("tool_name", "tool")
            info = update.get("tool_info", {})

            if state == "ACTIVE":
                cmd = info.get("parameters", {}).get("CommandLine", "")
                if cmd:
                    # Truncate long commands for display
                    disp_cmd = cmd.strip().replace("\n", " ")
                    if len(disp_cmd) > 110:
                        disp_cmd = disp_cmd[:107] + "..."
                    print(f"\n{CLR_CYAN}[Agent Action]{CLR_RESET} ⚙️  {disp_cmd}")
                else:
                    params = info.get("parameters", {})
                    param_str = ", ".join(f"{k}={v}" for k, v in params.items() if k != "Content")
                    if len(param_str) > 80:
                        param_str = param_str[:77] + "..."
                    print(f"\n{CLR_CYAN}[Agent Action]{CLR_RESET} 🔧 {tool_name}({param_str})")
                sys.stdout.flush()

            elif state == "DONE":
                duration = update.get("duration_seconds", 0)
                err = update.get("error")
                if err:
                    print(f"{CLR_RED}[Agent Action]{CLR_RESET} ✗ Failed ({duration:.1f}s): {err}")
                else:
                    print(f"{CLR_GREEN}[Agent Action]{CLR_RESET} ✓ Completed ({duration:.1f}s)")
                sys.stdout.flush()

        elif step_type == "agent_response":
            delta = update.get("text_delta")
            if delta:
                sys.stdout.write(delta)
                sys.stdout.flush()

    elif event == "result":
        # Final result event (all text has already been streamed via deltas)
        pass


def execute_container(cmd: Sequence[str], stream: bool = True) -> int:
    """Execute the docker run command, handling interrupts and real-time streaming."""
    sys.stdout.flush()
    sys.stderr.flush()

    try:
        if not stream:
            # Direct TTY passthrough
            proc = subprocess.Popen(cmd)
            def sig_handler(s, f):
                try:
                    proc.send_signal(s)
                except ProcessLookupError:
                    pass
            old_int = signal.signal(signal.SIGINT, sig_handler)
            old_term = signal.signal(signal.SIGTERM, sig_handler)
            try:
                return proc.wait()
            finally:
                signal.signal(signal.SIGINT, old_int)
                signal.signal(signal.SIGTERM, old_term)

        # Real-time streaming mode
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )

        def sig_handler(s, f):
            try:
                proc.send_signal(s)
            except ProcessLookupError:
                pass

        old_int = signal.signal(signal.SIGINT, sig_handler)
        old_term = signal.signal(signal.SIGTERM, sig_handler)

        try:
            if proc.stdout:
                for line in proc.stdout:
                    format_stream_line(line)
            return proc.wait()
        finally:
            signal.signal(signal.SIGINT, old_int)
            signal.signal(signal.SIGTERM, old_term)

    except FileNotFoundError:
        print(
            "Error: 'docker' CLI not found. Ensure Docker is installed and running on the host system.",
            file=sys.stderr,
        )
        return 127
    except Exception as e:
        print(f"Error executing container: {e}", file=sys.stderr)
        return 1
