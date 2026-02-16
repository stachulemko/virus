"""
Watchdog — monitoruje proces victim.py i restartuje go jeśli padnie.
Uruchomienie: python3 watchdog.py
"""
import subprocess
import sys
import os
import time
import signal

# ─── Konfiguracja ───────────────────────────────────────────────
VICTIM_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "victim.py")
RESTART_DELAY = 3        # sekundy przed restartem
PYTHON = sys.executable  # ten sam interpreter co watchdog
# ────────────────────────────────────────────────────────────────

running = True


def signal_handler(sig, frame):
    """Pozwala zamknąć watchdoga przez Ctrl+C / SIGTERM."""
    global running
    running = False


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


def start_victim():
    """Uruchamia victim.py jako subprocess w tle."""
    return subprocess.Popen(
        [PYTHON, VICTIM_SCRIPT],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # oddzielna sesja — nie umrze z watchdogiem
    )


def main():
    proc = None

    while running:
        # Uruchom jeśli nie działa
        if proc is None or proc.poll() is not None:
            exit_code = proc.poll() if proc else None
            proc = start_victim()

        # Sprawdzaj co sekundę
        time.sleep(1)

    # Cleanup — zamknij victima jeśli watchdog jest wyłączany
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
