"""
差速轉彎遙控車 — Pico W AP 模式（獨立運作版）
Pico W 自己開 WiFi 熱點 + WebSocket 伺服器
Mac/手機連上 Pico W 的 WiFi → 開瀏覽器就能玩

連線方式：
  1. 手機/電腦 WiFi 搜尋 "PicoCar" 密碼 "12345678"
  2. 瀏覽器開 http://192.168.4.1:8080
"""
import network
import socket
import json
import time
from machine import Pin, PWM, reset

# ===== AP 設定 =====
AP_SSID = "PicoCar"
AP_PASS = "12345678"

# ===== 馬達驅動腳位（L298N）=====
L_IN1 = Pin(0, Pin.OUT)
L_IN2 = Pin(1, Pin.OUT)
L_EN  = PWM(Pin(4)); L_EN.freq(1000)

R_IN1 = Pin(2, Pin.OUT)
R_IN2 = Pin(3, Pin.OUT)
R_EN  = PWM(Pin(5)); R_EN.freq(1000)

# ===== 按鈕 =====
btn_fwd   = Pin(14, Pin.IN, Pin.PULL_UP)
btn_back  = Pin(12, Pin.IN, Pin.PULL_UP)
btn_left  = Pin(11, Pin.IN, Pin.PULL_UP)
btn_right = Pin(13, Pin.IN, Pin.PULL_UP)
btn_spare = Pin(15, Pin.IN, Pin.PULL_UP)
btn_stop  = Pin(16, Pin.IN, Pin.PULL_UP)

led = Pin("LED", Pin.OUT)

SPEED_FULL = 45000
SPEED_TURN = 40000
SPEED_SPIN = 30000


def motor_stop():
    L_IN1.off(); L_IN2.off(); L_EN.duty_u16(0)
    R_IN1.off(); R_IN2.off(); R_EN.duty_u16(0)

def motor_forward(speed=SPEED_FULL):
    L_IN1.on();  L_IN2.off(); L_EN.duty_u16(speed)
    R_IN1.on();  R_IN2.off(); R_EN.duty_u16(speed)

def motor_backward(speed=SPEED_FULL):
    L_IN1.off(); L_IN2.on();  L_EN.duty_u16(speed)
    R_IN1.off(); R_IN2.on();  R_EN.duty_u16(speed)

def motor_left(speed=SPEED_TURN):
    L_IN1.off(); L_IN2.off(); L_EN.duty_u16(0)
    R_IN1.on();  R_IN2.off(); R_EN.duty_u16(speed)

def motor_right(speed=SPEED_TURN):
    L_IN1.on();  L_IN2.off(); L_EN.duty_u16(speed)
    R_IN1.off(); R_IN2.off(); R_EN.duty_u16(0)

def motor_spin_left(speed=SPEED_SPIN):
    L_IN1.off(); L_IN2.on();  L_EN.duty_u16(speed)
    R_IN1.on();  R_IN2.off(); R_EN.duty_u16(speed)


# ===== 開啟 AP =====
def start_ap():
    ap = network.WLAN(network.AP_IF)
    ap.config(essid=AP_SSID, password=AP_PASS)
    ap.active(True)
    while not ap.active():
        led.toggle()
        time.sleep(0.3)
    led.on()
    print("=" * 40)
    print("AP 已啟動！")
    print("WiFi 名稱: %s" % AP_SSID)
    print("密碼: %s" % AP_PASS)
    print("IP: %s" % ap.ifconfig()[0])
    print("=" * 40)
    return ap


# ===== 簡易 WebSocket 握手 =====
def ws_handshake(cl):
    """讀取 HTTP 請求，回傳 WebSocket 握手或 HTTP 頁面"""
    try:
        data = cl.recv(2048).decode()
    except:
        return None

    if "Upgrade: websocket" in data:
        # WebSocket 握手
        import hashlib, binascii
        key = ""
        for line in data.split("\r\n"):
            if "Sec-WebSocket-Key:" in line:
                key = line.split(":")[1].strip()
                break
        if not key:
            cl.close()
            return None
        magic = key + "258EAFA5-E914-47DA-95CA-5AB4BD0B2882"
        accept = binascii.b2a_base64(hashlib.sha1(magic.encode()).digest()).strip().decode()
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: %s\r\n\r\n" % accept
        )
        cl.send(response.encode())
        return "ws"

    elif "GET / " in data or "GET /index" in data:
        # 傳送內建網頁
        page = get_control_page()
        cl.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n".encode())
        # 分段送（記憶體有限）
        chunk = 512
        for i in range(0, len(page), chunk):
            cl.send(page[i:i+chunk].encode())
        cl.close()
        return "http"

    else:
        cl.send("HTTP/1.1 404 Not Found\r\n\r\n".encode())
        cl.close()
        return None


def ws_send(cl, msg):
    """送 WebSocket text frame"""
    b = msg.encode()
    header = bytearray()
    header.append(0x81)  # text frame
    if len(b) < 126:
        header.append(len(b))
    elif len(b) < 65536:
        header.append(126)
        header.append((len(b) >> 8) & 0xFF)
        header.append(len(b) & 0xFF)
    cl.send(header + b)


def ws_recv(cl):
    """讀 WebSocket frame，回傳 payload 字串或 None"""
    try:
        hdr = cl.recv(2)
        if not hdr or len(hdr) < 2:
            return None
        opcode = hdr[0] & 0x0F
        if opcode == 0x8:  # close
            return None
        masked = hdr[1] & 0x80
        length = hdr[1] & 0x7F
        if length == 126:
            ext = cl.recv(2)
            length = (ext[0] << 8) | ext[1]
        elif length == 127:
            cl.recv(8)  # 跳過（不支援超大 frame）
            return None
        mask = cl.recv(4) if masked else None
        payload = cl.recv(length)
        if mask:
            payload = bytearray(payload)
            for i in range(len(payload)):
                payload[i] ^= mask[i % 4]
        return payload.decode()
    except:
        return None


# ===== 內建控制網頁 =====
def get_control_page():
    return """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PicoCar</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-user-select:none;user-select:none;}
body{background:#0b0f14;color:#fff;font-family:system-ui;display:flex;flex-direction:column;
  align-items:center;justify-content:center;min-height:100vh;gap:18px;}
h1{font-size:22px;color:#f5c842;letter-spacing:2px;}
#status{font-size:13px;padding:4px 14px;border-radius:20px;border:1px solid #333;}
.on{color:#0b6;border-color:#0b644!important;}
.off{color:#e03030;border-color:#e0303044!important;}
.pad{position:relative;width:260px;height:280px;}
.btn{position:absolute;width:80px;height:80px;border:none;border-radius:50%;
  font-size:28px;font-weight:700;color:#fff;cursor:pointer;
  display:flex;align-items:center;justify-content:center;
  transition:all .12s;box-shadow:0 4px 12px rgba(0,0,0,0.4);}
.btn:active{transform:scale(0.88);filter:brightness(1.3);}
#fwd{background:#f5c842;left:90px;top:60px;}
#back{background:#E03030;left:90px;top:190px;}
#left{background:#4488FF;left:20px;top:125px;}
#right{background:#00CC44;left:160px;top:125px;}
#spin{background:#fff;color:#333;left:180px;top:0;width:64px;height:64px;font-size:22px;}
.motors{display:flex;gap:20px;font-size:12px;color:#888;}
.mbar{width:80px;height:12px;background:#222;border-radius:6px;overflow:hidden;position:relative;}
.mfill{height:100%;border-radius:6px;position:absolute;transition:width .1s;}
.info{font-size:11px;color:#445;text-align:center;line-height:1.8;}
</style></head><body>
<h1>PicoCar</h1>
<div id="status" class="off">連線中...</div>
<div class="pad">
  <button class="btn" id="fwd">&#x2B06;</button>
  <button class="btn" id="back">&#x2B07;</button>
  <button class="btn" id="left">&#x21B0;</button>
  <button class="btn" id="right">&#x21B1;</button>
  <button class="btn" id="spin">&#x27F3;</button>
</div>
<div class="motors">
  <div>左輪 <div class="mbar"><div class="mfill" id="lb" style="width:0;left:50%;background:#48f;"></div></div></div>
  <div>右輪 <div class="mbar"><div class="mfill" id="rb" style="width:0;left:50%;background:#0c4;"></div></div></div>
</div>
<div class="info">
  按住不放＝持續動作　放開＝停車<br>
  鍵盤 W/S/A/D/Q/Space
</div>
<script>
let ws,action='stop';
function connect(){
  ws=new WebSocket('ws://'+location.host+'/ws');
  ws.onopen=()=>{document.getElementById('status').className='on';
    document.getElementById('status').textContent='已連線';};
  ws.onmessage=(e)=>{try{const d=JSON.parse(e.data);updateBars(d.l||0,d.r||0);}catch(x){}};
  ws.onclose=()=>{document.getElementById('status').className='off';
    document.getElementById('status').textContent='已斷線';setTimeout(connect,1000);};
  ws.onerror=()=>{try{ws.close();}catch(x){}};
}
function send(a){action=a;if(ws&&ws.readyState===1)ws.send(JSON.stringify({action:a}));}
function updateBars(l,r){
  const lb=document.getElementById('lb'),rb=document.getElementById('rb');
  lb.style.width=Math.abs(l)*50+'%';lb.style.left=l>=0?'50%':(50-Math.abs(l)*50)+'%';
  lb.style.background=l>=0?'#48f':'#e03030';
  rb.style.width=Math.abs(r)*50+'%';rb.style.left=r>=0?'50%':(50-Math.abs(r)*50)+'%';
  rb.style.background=r>=0?'#0c4':'#e03030';
}
['fwd','back','left','right','spin'].forEach(id=>{
  const el=document.getElementById(id);
  const start=()=>send(id);const stop=()=>send('stop');
  el.addEventListener('mousedown',start);el.addEventListener('mouseup',stop);el.addEventListener('mouseleave',stop);
  el.addEventListener('touchstart',(e)=>{e.preventDefault();start();});
  el.addEventListener('touchend',(e)=>{e.preventDefault();stop();});
});
const keyMap={KeyW:'fwd',KeyS:'back',KeyA:'left',KeyD:'right',KeyQ:'spin',Space:'stop',
  ArrowUp:'fwd',ArrowDown:'back',ArrowLeft:'left',ArrowRight:'right'};
const held={};
addEventListener('keydown',(e)=>{if(!held[e.code]&&keyMap[e.code]){held[e.code]=1;send(keyMap[e.code]);}});
addEventListener('keyup',(e)=>{if(held[e.code]){delete held[e.code];send('stop');}});
connect();
</script></body></html>"""


# ===== 主程式 =====
def main():
    ap = start_ap()
    motor_stop()

    # HTTP + WebSocket 伺服器
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", 8080))
    srv.listen(2)
    srv.settimeout(0.05)  # non-blocking
    print("伺服器啟動 http://192.168.4.1:8080")

    ws_client = None
    blink = 0

    while True:
        blink += 1

        # 接受新連線
        try:
            cl, addr = srv.accept()
            cl.settimeout(2)
            result = ws_handshake(cl)
            if result == "ws":
                if ws_client:
                    try: ws_client.close()
                    except: pass
                ws_client = cl
                ws_client.settimeout(0.02)
                print("WebSocket 連線: %s" % str(addr))
            # http 已在 ws_handshake 裡關閉
        except:
            pass

        # 讀按鈕
        action = "stop"
        left_pwr = 0
        right_pwr = 0

        if btn_stop.value() == 0:
            action = "stop"
            motor_stop()
        elif btn_fwd.value() == 0:
            action = "fwd"; motor_forward()
            left_pwr = 1; right_pwr = 1
        elif btn_back.value() == 0:
            action = "back"; motor_backward()
            left_pwr = -1; right_pwr = -1
        elif btn_left.value() == 0:
            action = "left"; motor_left()
            right_pwr = 1
        elif btn_right.value() == 0:
            action = "right"; motor_right()
            left_pwr = 1
        elif btn_spare.value() == 0:
            action = "spin"; motor_spin_left()
            left_pwr = -1; right_pwr = 1
        else:
            motor_stop()

        # 讀 WebSocket 指令（網頁控制）
        if ws_client:
            try:
                msg = ws_recv(ws_client)
                if msg is None:
                    pass  # 沒資料或斷線
                elif msg == "":
                    pass
                else:
                    d = json.loads(msg)
                    wa = d.get("action", "stop")
                    if wa == "fwd":
                        motor_forward(); left_pwr = 1; right_pwr = 1
                    elif wa == "back":
                        motor_backward(); left_pwr = -1; right_pwr = -1
                    elif wa == "left":
                        motor_left(); right_pwr = 1; left_pwr = 0
                    elif wa == "right":
                        motor_right(); left_pwr = 1; right_pwr = 0
                    elif wa == "spin":
                        motor_spin_left(); left_pwr = -1; right_pwr = 1
                    else:
                        motor_stop(); left_pwr = 0; right_pwr = 0
                    action = wa
            except OSError:
                pass  # timeout = 沒資料，正常
            except Exception as e:
                print("WS 錯誤: %s" % e)
                try: ws_client.close()
                except: pass
                ws_client = None

            # 回傳馬達狀態給網頁
            if ws_client:
                try:
                    ws_send(ws_client, json.dumps({"l": left_pwr, "r": right_pwr, "a": action}))
                except:
                    try: ws_client.close()
                    except: pass
                    ws_client = None

        # LED
        if action != "stop":
            led.value(blink % 2)
        else:
            led.value(blink % 20 < 2)

        time.sleep(0.05)


main()
