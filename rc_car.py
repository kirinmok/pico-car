import network
import socket
import json
import time
from machine import Pin, ADC, reset

# ===== WiFi 設定 =====
SSID = "kirin"
PASSWORD = "0920007108"
SERVER_IP = "10.75.40.132"
SERVER_PORT = 9000

# ===== 左邊類比搖桿 =====
joy_x = ADC(26)  # GP26 = X 軸（左右）
joy_y = ADC(27)  # GP27 = Y 軸（前後）

# ===== 搖桿調校參數（v4 自動最佳化版）=====
# 經 900 組參數 × 7 項測試自動掃描後的最佳結果
# 四層防護：取樣平均 → 低通濾波 → 死區 → 遲滯
# 特點：零誤觸（含災難級雜訊）、20%微推可感知、釋放僅 3 幀（90ms）
DEADZONE = 0.15        # 死區 15%（搭配 LP=0.30 濾波後雜訊已被壓制）
EXPO = 1.0             # 線性回應（不吃小值，微推也能通過）
SMOOTH_SAMPLES = 10    # 單次讀取內平均次數（壓高頻雜訊）
LP_ALPHA = 0.30        # 低通濾波係數：平衡反應速度與穩定性
HYST = 0.02            # 遲滯門檻：輸出值變化 < 2% 就不更新，防止微抖

# ===== 右邊按鈕腳位 =====
btn_fwd   = Pin(14, Pin.IN, Pin.PULL_UP)  # 黃色 = 前進
btn_back  = Pin(12, Pin.IN, Pin.PULL_UP)  # 紅色 = 後退
btn_left  = Pin(11, Pin.IN, Pin.PULL_UP)  # 藍色 = 左轉
btn_right = Pin(13, Pin.IN, Pin.PULL_UP)  # 綠色 = 右轉
btn_boost = Pin(15, Pin.IN, Pin.PULL_UP)  # 白色 = 加速
btn_brake = Pin(16, Pin.IN, Pin.PULL_UP)  # 黑色 = 煞車

# ===== 板載 LED =====
led = Pin("LED", Pin.OUT)

# ===== 重連參數 =====
WIFI_CHECK_INTERVAL = 50   # 每 50 個 loop 檢查一次 WiFi
TCP_RETRY_DELAY = [1, 2, 3, 5, 5]  # 重連等待秒數（逐次增加）
MAX_TOTAL_FAILS = 100  # 連續失敗超過這個數就硬重啟


# ===== 校準搖桿（改良版）=====
def calibrate_joystick():
    """開機讀 100 次取平均，間隔拉長抵消 ADC 波動
    同時記錄 min/max 計算靜態雜訊範圍"""
    sx, sy = 0, 0
    xmin, xmax = 65535, 0
    ymin, ymax = 65535, 0
    n = 100
    for _ in range(n):
        rx = joy_x.read_u16()
        ry = joy_y.read_u16()
        sx += rx
        sy += ry
        if rx < xmin: xmin = rx
        if rx > xmax: xmax = rx
        if ry < ymin: ymin = ry
        if ry > ymax: ymax = ry
        time.sleep(0.015)  # 15ms 間隔，共 1.5 秒
    cx, cy = sx // n, sy // n
    noise_x = xmax - xmin
    noise_y = ymax - ymin
    print("搖桿校準: X=%d (%.2fV) Y=%d (%.2fV)" %
          (cx, cx * 3.3 / 65535, cy, cy * 3.3 / 65535))
    print("靜態雜訊: X=+/-%d Y=+/-%d (佔 %.1f%% / %.1f%%)" %
          (noise_x // 2, noise_y // 2,
           noise_x / 655.35, noise_y / 655.35))
    return cx, cy


# ===== 低通濾波器狀態（跨幀持續平滑）=====
_lp_x = 0.0   # X 軸濾波後的值
_lp_y = 0.0   # Y 軸濾波後的值
_out_x = 0.0  # X 軸最後輸出值（遲滯用）
_out_y = 0.0  # Y 軸最後輸出值（遲滯用）


def read_joystick_raw():
    """讀搖桿原始值，取 SMOOTH_SAMPLES 次平均消除高頻雜訊"""
    sx, sy = 0, 0
    for _ in range(SMOOTH_SAMPLES):
        sx += joy_x.read_u16()
        sy += joy_y.read_u16()
    return sx // SMOOTH_SAMPLES, sy // SMOOTH_SAMPLES


def read_joystick(cx, cy):
    """四層防護搖桿讀取：
    1. 單次取樣平均（壓高頻雜訊）
    2. 跨幀低通濾波 EMA（壓低頻飄移）
    3. 死區 + Scaled Dead Zone（消除靜止誤觸）
    4. 遲滯門檻（防止輸出值微抖）"""
    global _lp_x, _lp_y, _out_x, _out_y

    rx, ry = read_joystick_raw()

    # --- 映射到 -1.0 ~ 1.0 ---
    if rx < cx:
        ax = -(cx - rx) / max(cx, 1)
    else:
        ax = (rx - cx) / max(65535 - cx, 1)

    if ry < cy:
        ay = -(cy - ry) / max(cy, 1)
    else:
        ay = (ry - cy) / max(65535 - cy, 1)

    # --- 低通濾波（EMA：指數移動平均）---
    # 每 30ms 一幀，LP_ALPHA=0.25 → 約 4 幀（120ms）才反映完整變化
    # 雜訊是隨機的會被平滑掉，真正推搖桿是持續的會通過
    _lp_x = _lp_x * (1.0 - LP_ALPHA) + ax * LP_ALPHA
    _lp_y = _lp_y * (1.0 - LP_ALPHA) + ay * LP_ALPHA
    ax, ay = _lp_x, _lp_y

    # --- 死區過濾 + Scaled Dead Zone ---
    if abs(ax) < DEADZONE:
        ax = 0.0
    else:
        sign = 1 if ax > 0 else -1
        ax = sign * (abs(ax) - DEADZONE) / (1.0 - DEADZONE)

    if abs(ay) < DEADZONE:
        ay = 0.0
    else:
        sign = 1 if ay > 0 else -1
        ay = sign * (abs(ay) - DEADZONE) / (1.0 - DEADZONE)

    # --- 指數回應曲線 ---
    if ax != 0:
        sign = 1 if ax > 0 else -1
        ax = sign * (abs(ax) ** EXPO)
    if ay != 0:
        sign = 1 if ay > 0 else -1
        ay = sign * (abs(ay) ** EXPO)

    ax = max(-1.0, min(1.0, ax))
    ay = max(-1.0, min(1.0, ay))

    # --- 遲滯（Hysteresis）：變化太小就不更新 ---
    # 特殊規則：死區回 0 時強制歸零（不被遲滯卡住）
    if ax == 0.0:
        _out_x = 0.0
    elif abs(ax - _out_x) < HYST:
        ax = _out_x
    else:
        _out_x = ax

    if ay == 0.0:
        _out_y = 0.0
    elif abs(ay - _out_y) < HYST:
        ay = _out_y
    else:
        _out_y = ay

    return ax, ay


# ===== WiFi 連線（帶重試）=====
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
        ip = wlan.ifconfig()[0]
        print("WiFi 連線成功! IP: %s" % ip)
        led.on()
        return wlan
    else:
        print("WiFi 連線失敗!")
        led.off()
        return None


def ensure_wifi(wlan):
    """檢查 WiFi，斷了就重連。回傳 True=正常，False=失敗"""
    if wlan and wlan.isconnected():
        return True

    print("[!] WiFi 斷線，嘗試重連...")
    wlan = network.WLAN(network.STA_IF)
    wlan.active(False)
    time.sleep(1)
    wlan.active(True)
    wlan.connect(SSID, PASSWORD)

    for i in range(20):
        if wlan.isconnected():
            print("WiFi 重連成功: %s" % wlan.ifconfig()[0])
            led.on()
            return True
        led.toggle()
        time.sleep(0.5)

    print("WiFi 重連失敗")
    led.off()
    return False


# ===== TCP 連線（帶 timeout）=====
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

    # 校準（放開搖桿）
    print("=" * 35)
    print("校準中...請放開搖桿！(1.5 秒)")
    print("=" * 35)
    time.sleep(1)
    cx, cy = calibrate_joystick()
    print("死區: %.0f%% | 曲線: x^%.1f | 取樣: %d次" %
          (DEADZONE * 100, EXPO, SMOOTH_SAMPLES))
    print("=" * 35)

    sock = None
    blink = 0
    loop_count = 0
    tcp_fail_count = 0

    while True:
        loop_count += 1

        # === 定期檢查 WiFi ===
        if loop_count % WIFI_CHECK_INTERVAL == 0:
            if not ensure_wifi(wlan):
                if sock:
                    try:
                        sock.close()
                    except:
                        pass
                    sock = None
                time.sleep(2)
                continue

        # === TCP 連線 ===
        if sock is None:
            sock = connect_server()
            if sock is None:
                idx = min(tcp_fail_count, len(TCP_RETRY_DELAY) - 1)
                delay = TCP_RETRY_DELAY[idx]
                tcp_fail_count += 1
                print("TCP 重連 #%d，等 %ds..." % (tcp_fail_count, delay))
                led.toggle()
                time.sleep(delay)

                if tcp_fail_count >= MAX_TOTAL_FAILS:
                    print("連續失敗 %d 次，重啟 Pico W..." % tcp_fail_count)
                    reset()
                continue
            else:
                tcp_fail_count = 0

        # === 讀取輸入 ===
        # 1. 類比搖桿（已含平滑+死區+曲線）
        ax, ay = read_joystick(cx, cy)

        # 2. 數位按鈕
        djx, djy = 0, 0
        if btn_fwd.value() == 0:
            djy = 1
        if btn_back.value() == 0:
            djy = -1
        if btn_left.value() == 0:
            djx = -1
        if btn_right.value() == 0:
            djx = 1

        # 3. 搖桿優先，沒推就用按鈕
        jx = round(ax, 2) if ax != 0 else djx
        jy = round(ay, 2) if ay != 0 else djy

        a = 1 if btn_boost.value() == 0 else 0
        b = 1 if btn_brake.value() == 0 else 0

        data = {"jx": jx, "jy": jy, "a": a, "b": b}

        try:
            msg = json.dumps(data) + "\n"
            sock.send(msg.encode())
        except Exception as e:
            print("傳送失敗: %s" % e)
            try:
                sock.close()
            except:
                pass
            sock = None
            continue

        # === LED 狀態指示 ===
        blink += 1
        if jx != 0 or jy != 0 or a or b:
            led.value(blink % 2)       # 有輸入 → 快閃
        else:
            led.value(blink % 20 < 2)  # 閒置 → 慢閃

        time.sleep(0.03)


main()
