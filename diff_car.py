"""
差速轉彎遙控車 — Pico W 韌體
適用：國二 STEAM 課程 / 水路兩用車
硬體：2 顆 TT 馬達 + L298N 馬達驅動板
操控：6 顆按鈕（一次按一個，放開就停）

接線圖：
  Pico W GP0  → L298N IN1  (左馬達正轉)
  Pico W GP1  → L298N IN2  (左馬達反轉)
  Pico W GP2  → L298N IN3  (右馬達正轉)
  Pico W GP3  → L298N IN4  (右馬達反轉)
  Pico W GP4  → L298N ENA  (左馬達 PWM 速度)
  Pico W GP5  → L298N ENB  (右馬達 PWM 速度)

按鈕（右手 6 鍵，接 GND + 內建上拉）：
  GP14 = 黃色 → 前進（兩輪同速正轉）
  GP12 = 紅色 → 後退（兩輪同速反轉）
  GP11 = 藍色 → 左轉（右輪轉、左輪停）
  GP13 = 綠色 → 右轉（左輪轉、右輪停）
  GP15 = 白色 → 備用（原地左旋）
  GP16 = 黑色 → 緊急停車
"""
import network
import socket
import json
import time
from machine import Pin, PWM, reset

# ===== WiFi 設定 =====
SSID = "kirin"
PASSWORD = "0920007108"
SERVER_IP = "10.75.40.132"
SERVER_PORT = 9000

# ===== 馬達驅動腳位（L298N）=====
# 左馬達
L_IN1 = Pin(0, Pin.OUT)   # 正轉
L_IN2 = Pin(1, Pin.OUT)   # 反轉
L_EN  = PWM(Pin(4))       # 速度 PWM
L_EN.freq(1000)

# 右馬達
R_IN1 = Pin(2, Pin.OUT)   # 正轉
R_IN2 = Pin(3, Pin.OUT)   # 反轉
R_EN  = PWM(Pin(5))       # 速度 PWM
R_EN.freq(1000)

# ===== 按鈕腳位 =====
btn_fwd   = Pin(14, Pin.IN, Pin.PULL_UP)  # 黃色 = 前進
btn_back  = Pin(12, Pin.IN, Pin.PULL_UP)  # 紅色 = 後退
btn_left  = Pin(11, Pin.IN, Pin.PULL_UP)  # 藍色 = 左轉
btn_right = Pin(13, Pin.IN, Pin.PULL_UP)  # 綠色 = 右轉
btn_spare = Pin(15, Pin.IN, Pin.PULL_UP)  # 白色 = 原地左旋
btn_stop  = Pin(16, Pin.IN, Pin.PULL_UP)  # 黑色 = 緊急停車

# ===== LED =====
led = Pin("LED", Pin.OUT)

# ===== 馬達速度（0~65535）=====
SPEED_FULL = 45000   # 約 70% 動力（可調整）
SPEED_TURN = 40000   # 轉彎時動力輪速度
SPEED_SPIN = 30000   # 原地旋轉速度


def motor_stop():
    """兩輪停止"""
    L_IN1.off(); L_IN2.off(); L_EN.duty_u16(0)
    R_IN1.off(); R_IN2.off(); R_EN.duty_u16(0)


def motor_forward(speed=SPEED_FULL):
    """前進：兩輪同速正轉"""
    L_IN1.on();  L_IN2.off(); L_EN.duty_u16(speed)
    R_IN1.on();  R_IN2.off(); R_EN.duty_u16(speed)


def motor_backward(speed=SPEED_FULL):
    """後退：兩輪同速反轉"""
    L_IN1.off(); L_IN2.on();  L_EN.duty_u16(speed)
    R_IN1.off(); R_IN2.on();  R_EN.duty_u16(speed)


def motor_left(speed=SPEED_TURN):
    """左轉：右輪轉、左輪停（差速轉彎）"""
    L_IN1.off(); L_IN2.off(); L_EN.duty_u16(0)
    R_IN1.on();  R_IN2.off(); R_EN.duty_u16(speed)


def motor_right(speed=SPEED_TURN):
    """右轉：左輪轉、右輪停（差速轉彎）"""
    L_IN1.on();  L_IN2.off(); L_EN.duty_u16(speed)
    R_IN1.off(); R_IN2.off(); R_EN.duty_u16(0)


def motor_spin_left(speed=SPEED_SPIN):
    """原地左旋：左輪反轉、右輪正轉"""
    L_IN1.off(); L_IN2.on();  L_EN.duty_u16(speed)
    R_IN1.on();  R_IN2.off(); R_EN.duty_u16(speed)


# ===== WiFi =====
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        print("WiFi 已連線: %s" % wlan.ifconfig()[0])
        return wlan
    print("連接 WiFi: %s ..." % SSID)
    wlan.connect(SSID, PASSWORD)
    for i in range(20):
        if wlan.isconnected():
            break
        led.toggle()
        time.sleep(0.5)
    if wlan.isconnected():
        print("WiFi OK! IP: %s" % wlan.ifconfig()[0])
        led.on()
        return wlan
    else:
        print("WiFi 失敗!")
        led.off()
        return None


def connect_server():
    try:
        s = socket.socket()
        s.settimeout(5)
        s.connect((SERVER_IP, SERVER_PORT))
        s.settimeout(None)
        print("已連接伺服器 %s:%d" % (SERVER_IP, SERVER_PORT))
        return s
    except Exception as e:
        print("伺服器連線失敗: %s" % e)
        return None


# ===== 主程式 =====
def main():
    wlan = connect_wifi()
    if not wlan:
        for i in range(20):
            led.toggle()
            time.sleep(0.2)
        print("WiFi 無法連線，5 秒後重啟...")
        time.sleep(5)
        reset()

    motor_stop()
    print("=" * 35)
    print("差速轉彎車 Ready!")
    print("黃=前進 紅=後退 藍=左轉 綠=右轉")
    print("白=原地旋轉 黑=停車")
    print("=" * 35)

    sock = None
    tcp_fail = 0
    blink = 0

    while True:
        # TCP 連線
        if sock is None:
            sock = connect_server()
            if sock is None:
                tcp_fail += 1
                delay = min(tcp_fail, 5)
                print("TCP 重連 #%d，等 %ds..." % (tcp_fail, delay))
                time.sleep(delay)
                if tcp_fail >= 50:
                    print("連續失敗太多，重啟...")
                    reset()
                continue
            tcp_fail = 0

        # 讀按鈕（一次只認一個，優先順序：停車 > 前 > 後 > 左 > 右 > 旋轉）
        action = "stop"
        left_speed = 0
        right_speed = 0

        if btn_stop.value() == 0:
            action = "stop"
            motor_stop()
        elif btn_fwd.value() == 0:
            action = "fwd"
            motor_forward()
            left_speed = SPEED_FULL
            right_speed = SPEED_FULL
        elif btn_back.value() == 0:
            action = "back"
            motor_backward()
            left_speed = -SPEED_FULL
            right_speed = -SPEED_FULL
        elif btn_left.value() == 0:
            action = "left"
            motor_left()
            left_speed = 0
            right_speed = SPEED_TURN
        elif btn_right.value() == 0:
            action = "right"
            motor_right()
            left_speed = SPEED_FULL
            right_speed = 0
        elif btn_spare.value() == 0:
            action = "spin"
            motor_spin_left()
            left_speed = -SPEED_SPIN
            right_speed = SPEED_SPIN
        else:
            motor_stop()

        # 送資料給伺服器（遊戲同步用）
        # 格式：左右輪速度 -1.0~1.0 + 動作名稱
        data = {
            "left":  round(left_speed / 65535, 2),
            "right": round(right_speed / 65535, 2),
            "action": action
        }

        try:
            msg = json.dumps(data) + "\n"
            sock.send(msg.encode())
        except:
            try: sock.close()
            except: pass
            sock = None
            continue

        # LED
        blink += 1
        if action != "stop":
            led.value(blink % 2)
        else:
            led.value(blink % 20 < 2)

        time.sleep(0.05)


main()
