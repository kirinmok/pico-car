"""
USB 串口 ↔ WebSocket 橋接器
讀取 Pico W USB 串口 → 轉發到 WebSocket → 瀏覽器

用法：python3 serial_bridge.py
然後開瀏覽器 http://localhost:8080/diff_game.html
"""
import asyncio
import json
import serial
import serial.tools.list_ports
import websockets
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading
import os

# 自動偵測 Pico W 串口
def find_pico():
    for p in serial.tools.list_ports.comports():
        if "usbmodem" in p.device.lower():
            return p.device
    return None

# 全域狀態
pico_state = {"a": "stop", "l": 0, "r": 0}
ws_clients = set()
command_queue = asyncio.Queue()

# HTTP 伺服器（另一個 thread，提供靜態檔案）
def start_http(port=8080):
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    httpd = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    print(f"HTTP 伺服器: http://localhost:{port}")
    httpd.serve_forever()

# WebSocket handler
async def ws_handler(websocket):
    ws_clients.add(websocket)
    print(f"WebSocket 連線: {websocket.remote_address}")
    try:
        async for msg in websocket:
            # 網頁送來的控制指令 → 轉發到 Pico W
            await command_queue.put(msg)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        ws_clients.discard(websocket)
        print(f"WebSocket 斷線: {websocket.remote_address}")

# 廣播給所有 WebSocket 客戶端
async def broadcast(msg):
    dead = set()
    for ws in ws_clients:
        try:
            await ws.send(msg)
        except:
            dead.add(ws)
    ws_clients.difference_update(dead)

# 串口讀取 + 轉發
async def serial_loop(port):
    global pico_state
    print(f"串口: {port}")

    ser = serial.Serial(port, 115200, timeout=0.05)
    ser.reset_input_buffer()

    while True:
        # 讀 Pico W 串口輸出
        try:
            if ser.in_waiting:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line.startswith("{"):
                    try:
                        data = json.loads(line)
                        pico_state = data
                        # 轉發給瀏覽器
                        await broadcast(json.dumps(data))
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            print(f"串口讀取錯誤: {e}")
            await asyncio.sleep(1)
            continue

        # 寫入網頁指令到 Pico W
        try:
            while not command_queue.empty():
                cmd = command_queue.get_nowait()
                ser.write((cmd + "\n").encode())
        except Exception as e:
            print(f"串口寫入錯誤: {e}")

        await asyncio.sleep(0.02)

async def main():
    port = find_pico()
    if not port:
        print("找不到 Pico W！請確認 USB 已連接。")
        return

    # HTTP 在背景 thread
    http_thread = threading.Thread(target=start_http, daemon=True)
    http_thread.start()

    # WebSocket 伺服器
    ws_server = await websockets.serve(ws_handler, "0.0.0.0", 8765)
    print(f"WebSocket 伺服器: ws://localhost:8765")
    print("=" * 40)
    print("開啟瀏覽器: http://localhost:8080/diff_game.html")
    print("=" * 40)

    # 串口循環
    await serial_loop(port)

if __name__ == "__main__":
    asyncio.run(main())
