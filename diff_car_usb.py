"""
差速轉彎遙控車 — USB 串口版（純遙控器，馬達可選）
透過 USB 線直接和 Mac 通訊，不需要 WiFi。

按鈕（接 GND + 內建上拉）：
  GP14 = 黃色 → 前進
  GP12 = 紅色 → 後退
  GP11 = 藍色 → 左轉
  GP13 = 綠色 → 右轉
  GP15 = 白色 → 原地左旋
  GP16 = 黑色 → 停車

如需接馬達，取消下方 ENABLE_MOTOR 註解
"""
import sys
import json
import time
import select
from machine import Pin

# ===== 馬達開關（沒接 L298N 就設 False）=====
ENABLE_MOTOR = False

# ===== 按鈕 =====
btn_fwd   = Pin(14, Pin.IN, Pin.PULL_UP)
btn_back  = Pin(12, Pin.IN, Pin.PULL_UP)
btn_left  = Pin(11, Pin.IN, Pin.PULL_UP)
btn_right = Pin(13, Pin.IN, Pin.PULL_UP)
btn_spare = Pin(15, Pin.IN, Pin.PULL_UP)
btn_stop  = Pin(16, Pin.IN, Pin.PULL_UP)

led = Pin("LED", Pin.OUT)

# ===== 搖桿（如果有的話）=====
try:
    from machine import ADC
    joy_x = ADC(Pin(26))
    joy_y = ADC(Pin(27))
    HAS_JOYSTICK = True
except:
    HAS_JOYSTICK = False

# ===== 馬達（可選）=====
if ENABLE_MOTOR:
    from machine import PWM
    L_IN1 = Pin(0, Pin.OUT); L_IN2 = Pin(1, Pin.OUT)
    L_EN = PWM(Pin(4)); L_EN.freq(1000)
    R_IN1 = Pin(2, Pin.OUT); R_IN2 = Pin(3, Pin.OUT)
    R_EN = PWM(Pin(5)); R_EN.freq(1000)

    SPEED_FULL = 45000
    SPEED_TURN = 40000
    SPEED_SPIN = 30000

    def motor_stop():
        L_IN1.off(); L_IN2.off(); L_EN.duty_u16(0)
        R_IN1.off(); R_IN2.off(); R_EN.duty_u16(0)
    def motor_forward():
        L_IN1.on(); L_IN2.off(); L_EN.duty_u16(SPEED_FULL)
        R_IN1.on(); R_IN2.off(); R_EN.duty_u16(SPEED_FULL)
    def motor_backward():
        L_IN1.off(); L_IN2.on(); L_EN.duty_u16(SPEED_FULL)
        R_IN1.off(); R_IN2.on(); R_EN.duty_u16(SPEED_FULL)
    def motor_left():
        L_IN1.off(); L_IN2.off(); L_EN.duty_u16(0)
        R_IN1.on(); R_IN2.off(); R_EN.duty_u16(SPEED_TURN)
    def motor_right():
        L_IN1.on(); L_IN2.off(); L_EN.duty_u16(SPEED_FULL)
        R_IN1.off(); R_IN2.off(); R_EN.duty_u16(0)
    def motor_spin():
        L_IN1.off(); L_IN2.on(); L_EN.duty_u16(SPEED_SPIN)
        R_IN1.on(); R_IN2.off(); R_EN.duty_u16(SPEED_SPIN)

    MOTOR_FN = {"fwd": motor_forward, "back": motor_backward,
                "left": motor_left, "right": motor_right,
                "spin": motor_spin, "stop": motor_stop}
else:
    def motor_stop(): pass
    MOTOR_FN = {}

# ===== USB 串口輸入 =====
poll = select.poll()
poll.register(sys.stdin, select.POLLIN)
usb_buf = ""

def check_usb():
    global usb_buf
    while poll.poll(0):
        ch = sys.stdin.read(1)
        if ch == "\n":
            line = usb_buf.strip()
            usb_buf = ""
            if line:
                try:
                    return json.loads(line).get("action", "stop")
                except:
                    pass
        else:
            usb_buf += ch
    return None

# ===== 搖桿讀取 =====
DEADZONE = 0.20

def read_joy():
    if not HAS_JOYSTICK:
        return 0, 0
    rx = joy_x.read_u16()
    ry = joy_y.read_u16()
    ax = (rx - 32768) / 32768.0
    ay = (32768 - ry) / 32768.0
    if abs(ax) < DEADZONE: ax = 0
    if abs(ay) < DEADZONE: ay = 0
    return round(ax, 2), round(ay, 2)

# ===== 主程式 =====
def main():
    motor_stop()
    print('{"status":"ready"}')
    blink = 0

    while True:
        blink += 1
        action = "stop"
        l_pwr = 0
        r_pwr = 0

        # 1. 實體按鈕
        # 黑+白同時按 = 重開
        if btn_stop.value() == 0 and btn_spare.value() == 0:
            action = "restart"
        elif btn_stop.value() == 0:
            action = "ok"
        elif btn_fwd.value() == 0:
            action = "fwd"; l_pwr = 1; r_pwr = 1
        elif btn_back.value() == 0:
            action = "back"; l_pwr = -1; r_pwr = -1
        elif btn_left.value() == 0:
            action = "left"; r_pwr = 1
        elif btn_right.value() == 0:
            action = "right"; l_pwr = 1
        elif btn_spare.value() == 0:
            action = "spin"; l_pwr = -1; r_pwr = 1

        # 2. 搖桿（如果沒按按鈕）
        if action == "stop" and HAS_JOYSTICK:
            jx, jy = read_joy()
            if jy > 0:
                action = "fwd"; l_pwr = 1; r_pwr = 1
            elif jy < 0:
                action = "back"; l_pwr = -1; r_pwr = -1
            elif jx < 0:
                action = "left"; r_pwr = 1
            elif jx > 0:
                action = "right"; l_pwr = 1

        # 3. USB 指令（網頁控制）
        usb_cmd = check_usb()
        if usb_cmd and usb_cmd != "stop":
            action = usb_cmd
            if usb_cmd == "fwd":    l_pwr = 1;  r_pwr = 1
            elif usb_cmd == "back": l_pwr = -1; r_pwr = -1
            elif usb_cmd == "left": l_pwr = 0;  r_pwr = 1
            elif usb_cmd == "right":l_pwr = 1;  r_pwr = 0
            elif usb_cmd == "spin": l_pwr = -1; r_pwr = 1
            else:                   l_pwr = 0;  r_pwr = 0

        # 馬達
        if ENABLE_MOTOR:
            fn = MOTOR_FN.get(action, motor_stop)
            fn()

        # 輸出狀態
        print(json.dumps({"a": action, "l": l_pwr, "r": r_pwr}))

        # LED
        if action != "stop":
            led.value(blink % 2)
        else:
            led.value(blink % 20 < 2)

        time.sleep(0.05)

main()
