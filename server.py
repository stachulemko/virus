import asyncio

# Ten serwer WebSocket przyjmuje wiadomości i wypisuje je w konsoli.
# Uruchom: python server.py
# Wymaga: pip install websockets

import websockets


async def handler(websocket):
	print("Klient połączony")
	try:
		async for message in websocket:
			print(f"Odebrano: {message}")
			await websocket.send(f"Serwer otrzymał: {message}")
	except websockets.ConnectionClosedOK:
		print("Klient poprawnie zakończył połączenie")
	except websockets.ConnectionClosedError:
		print("Połączenie zamknięte z błędem")
	finally:
		print("Klient rozłączony")


async def main():
	# Nasłuchuj na porcie 8765 na wszystkich interfejsach
	async with websockets.serve(handler, host="0.0.0.0", port=8765):
		print("Serwer WebSocket wystartował na ws://0.0.0.0:8765")
		await asyncio.Future()  # keep running


if __name__ == "__main__":
	asyncio.run(main())
