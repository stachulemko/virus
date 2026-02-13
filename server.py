import os
from aiohttp import web

connected_clients = set()


async def health(request):
    """Odpowiada na healthchecki Rendera (HEAD/GET /)."""
    return web.Response(text="ok")


async def websocket_handler(request):
    """Obsługuje połączenia WebSocket."""
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)

    connected_clients.add(ws)
    print(f"Klient połączony (aktywnych: {len(connected_clients)})")

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                print(f"Odebrano: {msg.data}")
                await ws.send_str(f"Serwer otrzymał: {msg.data}")
            elif msg.type == web.WSMsgType.BINARY:
                print(f"Odebrano dane binarne: {len(msg.data)} bajtów")
                await ws.send_str(f"Serwer otrzymał {len(msg.data)} bajtów")
            elif msg.type == web.WSMsgType.ERROR:
                print(f"Błąd WebSocket: {ws.exception()}")
    finally:
        connected_clients.discard(ws)
        print(f"Klient rozłączony (aktywnych: {len(connected_clients)})")

    return ws


def create_app():
    app = web.Application()
    app.router.add_get("/", health)               # healthcheck Rendera
    app.router.add_get("/ws", websocket_handler)   # WebSocket endpoint
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    app = create_app()
    print(f"Serwer startuje na 0.0.0.0:{port}")
    web.run_app(app, host="0.0.0.0", port=port)