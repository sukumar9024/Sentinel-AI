"""Run API, worker and Vite together. Ctrl+C shuts down all three."""

import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.chdir(root)
python = root / ".venv" / "bin" / "python"
if not python.exists() or not (root / ".env").exists():
    raise SystemExit("Run make setup first.")
commands = [
    [
        str(python),
        "-m",
        "uvicorn",
        "sentinel.api:create_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ],
    [str(python), "-m", "sentinel.worker"],
    [str(python), "-m", "sentinel.integration_worker"],
    [str(python), "-m", "sentinel.maintenance_worker"],
    ["npm", "--prefix", "frontend", "run", "dev", "--", "--port", "5173", "--strictPort"],
]
processes = []
try:
    for command in commands:
        processes.append(subprocess.Popen(command, start_new_session=True))
        if command == commands[0]:
            for attempt in range(50):
                if processes[0].poll() is not None:
                    raise SystemExit("API failed to start")
                try:
                    urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=1)
                    break
                except OSError:
                    time.sleep(0.2)
            else:
                raise SystemExit("API health check timed out")
    print("SentinelAI: http://127.0.0.1:5173 | API docs: http://127.0.0.1:8000/docs", flush=True)
    while all(process.poll() is None for process in processes):
        time.sleep(1)
    raise SystemExit("A service exited; stopping the remaining services.")
except KeyboardInterrupt:
    pass
finally:
    for process in processes:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
