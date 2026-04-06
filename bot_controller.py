import os
import subprocess
import sys
import threading
import time
from itertools import islice
from collections import deque
from pathlib import Path


class BotController:
    def __init__(self, bot_script: str = "main.py", max_log_lines: int = 1000) -> None:
        self.bot_script = bot_script
        self.max_log_lines = max_log_lines
        self._process: subprocess.Popen | None = None
        self._logs = deque(maxlen=max_log_lines)
        self._started_at: float | None = None
        self._lock = threading.Lock()
        self._base_dir = Path(__file__).resolve().parent

    def _append_log(self, line: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self._logs.append(f"[{timestamp}] {line.rstrip()}")

    def _stream_logs(self, process: subprocess.Popen) -> None:
        if process.stdout is None:
            return

        for line in process.stdout:
            self._append_log(line)

    def _tail_logs(self, count: int = 8) -> list[str]:
        if count <= 0:
            return []
        return list(islice(self._logs, max(0, len(self._logs) - count), len(self._logs)))

    def start(self) -> dict:
        with self._lock:
            if self.is_running():
                return {"ok": False, "message": "Bot is already running."}

            # Discord bots need a persistent runtime; Vercel serverless cannot host this process.
            if os.getenv("VERCEL") == "1":
                return {
                    "ok": False,
                    "message": (
                        "Start is disabled on Vercel serverless. "
                        "Run the bot on Railway/Render/Fly.io/VPS and keep this panel as UI only."
                    ),
                }

            token = os.getenv("TOKEN") or os.getenv("DISCORD_TOKEN")
            if not token:
                return {
                    "ok": False,
                    "message": "Set TOKEN (or DISCORD_TOKEN) environment variable.",
                }

            script_path = self._base_dir / self.bot_script
            if not script_path.exists():
                return {
                    "ok": False,
                    "message": f"Bot script '{self.bot_script}' was not found.",
                }

            self._append_log("Starting bot process...")
            self._process = subprocess.Popen(
                [sys.executable, "-u", str(script_path)],
                cwd=str(self._base_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=os.environ.copy(),
            )
            self._started_at = time.time()

            log_thread = threading.Thread(
                target=self._stream_logs,
                args=(self._process,),
                daemon=True,
            )
            log_thread.start()

            # Give the child process a moment to fail fast on import/token/login issues.
            time.sleep(1.2)
            if self._process.poll() is not None:
                exit_code = self._process.returncode
                recent_logs = self._tail_logs(10)
                self._append_log(f"Bot exited early with code {exit_code}.")
                self._started_at = None
                return {
                    "ok": False,
                    "message": "Bot process exited right after start. Check logs for details.",
                    "exit_code": exit_code,
                    "logs_tail": recent_logs,
                }

            return {
                "ok": True,
                "message": "Bot started successfully.",
                "pid": self._process.pid,
            }

    def stop(self) -> dict:
        with self._lock:
            if not self.is_running():
                return {"ok": False, "message": "Bot is not running."}

            assert self._process is not None
            self._append_log("Stopping bot process...")
            self._process.terminate()

            try:
                self._process.wait(timeout=10)
                self._append_log("Bot stopped.")
            except subprocess.TimeoutExpired:
                self._append_log("Stop timed out. Killing bot process...")
                self._process.kill()
                self._process.wait(timeout=5)
                self._append_log("Bot process killed.")

            self._started_at = None
            return {"ok": True, "message": "Bot stopped."}

    def restart(self) -> dict:
        stop_result = self.stop() if self.is_running() else {"ok": True}
        if not stop_result.get("ok"):
            return stop_result
        return self.start()

    def clear_logs(self) -> None:
        with self._lock:
            self._logs.clear()

    def get_logs(self, limit: int = 200) -> list[str]:
        with self._lock:
            if limit <= 0:
                return []
            return list(self._logs)[-limit:]

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def status(self) -> dict:
        running = self.is_running()
        pid = self._process.pid if running and self._process else None
        exit_code = None
        if self._process is not None and not running:
            exit_code = self._process.poll()

        uptime_seconds = 0
        if running and self._started_at is not None:
            uptime_seconds = int(time.time() - self._started_at)

        return {
            "running": running,
            "pid": pid,
            "uptime_seconds": uptime_seconds,
            "exit_code": exit_code,
        }
