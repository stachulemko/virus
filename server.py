import os # Dodaj ten import na górze
import websockets
async def main():
    # Pobierz port ze zmiennej środowiskowej (Render go tam wstawi)
    # Jeśli nie ma zmiennej (lokalnie), użyj 8765
    port = int(os.environ.get("PORT", 8765))
    
    async with websockets.serve(handler, host="0.0.0.0", port=port):
        print(f"Serwer WebSocket wystartował na porcie: {port}")
        await asyncio.Future()  # utrzymuj działanie