import asyncio
import websockets
import os  # <--- To jest kluczowe

async def handler(websocket):
    print("Klient połączony")
    try:
        async for message in websocket:
            print(f"Odebrano: {message}")
            await websocket.send(f"Serwer otrzymał: {message}")
    except websockets.ConnectionClosed:
        print("Połączenie zamknięte")
    finally:
        print("Klient rozłączony")

async def main():
    # Render podaje port w zmiennej środowiskowej PORT
    # Jeśli jej nie ma (np. lokalnie), używamy 8765
    port = int(os.environ.get("PORT", 8765))
    
    # Nasłuchujemy na 0.0.0.0 (ważne!)
    async with websockets.serve(handler, "0.0.0.0", port):
        print(f"Serwer działa na porcie {port}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())