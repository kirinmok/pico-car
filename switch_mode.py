#!/usr/bin/env python3
"""
PicoCar 模式切換器
用法：python3 switch_mode.py

兩個模式：
  USB  → diff_car_usb.py → 透過 Mac bridge 控制（遊戲模擬用）
  AP   → diff_car_ap.py  → Pico 自己開 WiFi（手機直連用）
"""
import subprocess
import sys
import os
import time
import serial.tools.list_ports

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

MODES = {
    "1": ("USB 模式（Mac bridge + 遊戲模擬）", "diff_car_usb.py"),
    "2": ("AP 模式（手機/iPad 直連）", "diff_car_ap.py"),
}

def find_pico():
    for p in serial.tools.list_ports.comports():
        if "usbmodem" in p.device.lower():
            return p.device
    return None

def kill_bridge():
    subprocess.run(["pkill", "-f", "serial_bridge"], capture_output=True)
    time.sleep(1)

def upload(port, filename):
    filepath = os.path.join(SCRIPT_DIR, filename)
    if not os.path.exists(filepath):
        print(f"  找不到 {filepath}")
        return False
    print(f"  上傳 {filename} → main.py ...")
    r = subprocess.run(["mpremote", "connect", port, "cp", filepath, ":main.py"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  上傳失敗: {r.stderr}")
        return False
    print("  重啟 Pico W ...")
    subprocess.run(["mpremote", "connect", port, "reset"], capture_output=True)
    return True

def start_bridge():
    print("  啟動 serial_bridge.py ...")
    subprocess.Popen([sys.executable, "serial_bridge.py"],
                     cwd=SCRIPT_DIR,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    print("  bridge 已啟動")

def main():
    print("=" * 40)
    print("  PicoCar 模式切換器")
    print("=" * 40)

    port = find_pico()
    if not port:
        print("\n找不到 Pico W！請確認 USB 已連接。")
        return

    print(f"\nPico W: {port}\n")
    for k, (desc, _) in MODES.items():
        print(f"  [{k}] {desc}")
    print(f"  [q] 離開")

    choice = input("\n選擇模式: ").strip()
    if choice not in MODES:
        print("掰掰！")
        return

    desc, filename = MODES[choice]
    print(f"\n切換到: {desc}")

    # 停 bridge
    print("  停止 serial_bridge ...")
    kill_bridge()

    # 等串口釋放
    time.sleep(1)

    # 上傳
    if not upload(port, filename):
        return

    time.sleep(3)

    # USB 模式自動啟動 bridge
    if choice == "1":
        start_bridge()
        print(f"\n  遊戲: http://localhost:8080/diff_game.html")
        print(f"  遙控: http://localhost:8080/controller.html")
    else:
        print(f"\n  手機 WiFi 連: PicoCar-01（密碼 12345678）")
        print(f"  然後開: http://192.168.4.1:8080")

    print("\n切換完成！")

if __name__ == "__main__":
    main()
