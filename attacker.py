import time
import os
import struct





#venvVirus/bin/python server.py
# UWAGA: Ten kod wymaga biblioteki websocket-client
# Zainstaluj ją w terminalu wpisując: pip install websocket-client
try:
    from websocket import create_connection, WebSocketConnectionClosedException
except ImportError:
    print("Błąd: Brak biblioteki 'websocket-client'.")
    print("Uruchom w terminalu: pip install websocket-client")
    exit(1)

def send_file(ws, filepath):
    """
    Wysyła plik przez WebSocket jako wiadomość binarną.
    """
    if not os.path.isfile(filepath):
        print(f"Błąd: Plik {filepath} nie istnieje.")
        return

    filesize = os.path.getsize(filepath)
    print(f"Wysyłanie pliku: {filepath} ({filesize} bajtów)...")

    try:
        with open(filepath, 'rb') as f:
            content = f.read()
            # Wysyłanie binarne
            ws.send_binary(content)
        print("Plik wysłany.")
    except Exception as e:
        print(f"Błąd podczas wysyłania pliku: {e}")

def connect_loop(url, message):
    while True:
        try:
            print(f"Próba połączenia z {url}...")
            # create_connection automatycznie obsługuje wss:// (SSL)
            ws = create_connection(url)
            print("Połączono z serwerem (WebSocket)!")

            # Wyślij własną wiadomość natychmiast po połączeniu
            ws.send(message)
            print(f"Wysłano wiadomość: {message}")
            
            # Pętla nasłuchiwania
            while True:
                result = ws.recv()
                if not result:
                    break
                
                print(f"Otrzymano wiadomość: {result}")
                
                # Tu można dodać logikę wykonywania poleceń (ostrożnie!)
                # Odsyłamy potwierdzenie
                ws.send(f"Otrzymałem: {result}")

        except WebSocketConnectionClosedException:
            print("Połączenie zamknięte przez serwer.")
        except ConnectionRefusedError:
             print("Odmowa połączenia (serwer nieaktywny?)")
        except Exception as e:
            print(f"Błąd połączenia: {e}")
        
        print("Ponowna próba za 5 sekund...")
        time.sleep(5)

if __name__ == "__main__":
    # Adres Twojego serwera WebSocket
    SERVER_URL = 'wss://virus-4.onrender.com/ws'
    MESSAGE = 'Hello from client'
    
    connect_loop(SERVER_URL, MESSAGE)