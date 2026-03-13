"""
差速轉彎遙控車 — WiFi 直連版
Pico W 連你的 WiFi → 自己開 WebSocket 伺服器
iPad/手機/電腦 同一個 WiFi → 瀏覽器連 Pico W 的 IP

步驟：
  1. Pico W 開機自動連 WiFi，LED 亮 = 連線成功
  2. 看串口印出的 IP（例如 10.75.40.89）
  3. iPad 瀏覽器開 http://10.75.40.89:8080
"""
import network
import socket
import json
import time
from machine import Pin, ADC, reset
import hashlib
import binascii

# ===== WiFi 設定 =====
SSID = "kirin"
PASSWORD = "0920007108"

# ===== 馬達開關 =====
ENABLE_MOTOR = False

# ===== 按鈕 =====
btn_fwd   = Pin(14, Pin.IN, Pin.PULL_UP)
btn_back  = Pin(12, Pin.IN, Pin.PULL_UP)
btn_left  = Pin(11, Pin.IN, Pin.PULL_UP)
btn_right = Pin(13, Pin.IN, Pin.PULL_UP)
btn_spare = Pin(15, Pin.IN, Pin.PULL_UP)
btn_stop  = Pin(16, Pin.IN, Pin.PULL_UP)

led = Pin("LED", Pin.OUT)

# ===== 搖桿 =====
joy_x = ADC(Pin(26))
joy_y = ADC(Pin(27))
DEADZONE = 0.20


def read_joy():
    rx = joy_x.read_u16()
    ry = joy_y.read_u16()
    ax = (rx - 32768) / 32768.0
    ay = (ry - 32768) / 32768.0
    if abs(ax) < DEADZONE: ax = 0
    if abs(ay) < DEADZONE: ay = 0
    return round(ax, 2), round(ay, 2)


# ===== WiFi 連線 =====
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("連接 WiFi: %s ..." % SSID)
        wlan.connect(SSID, PASSWORD)
        for i in range(20):
            if wlan.isconnected(): break
            led.toggle()
            time.sleep(0.5)
    if wlan.isconnected():
        ip = wlan.ifconfig()[0]
        led.on()
        print("WiFi OK! IP: %s" % ip)
        print("=" * 40)
        print("iPad 瀏覽器開: http://%s:8080" % ip)
        print("=" * 40)
        return wlan, ip
    else:
        print("WiFi 失敗!")
        led.off()
        return None, None


# ===== WebSocket 工具 =====
def ws_handshake(cl):
    try:
        data = cl.recv(2048).decode()
    except:
        return None

    if "Upgrade: websocket" in data:
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
        cl.send(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                 "Connection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n" % accept).encode())
        return "ws"

    elif "GET " in data:
        page = get_page()
        cl.send("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n\r\n".encode())
        chunk = 512
        for i in range(0, len(page), chunk):
            cl.send(page[i:i+chunk].encode())
        cl.close()
        return "http"
    else:
        cl.close()
        return None


def ws_send(cl, msg):
    b = msg.encode()
    header = bytearray([0x81])
    if len(b) < 126:
        header.append(len(b))
    else:
        header.append(126)
        header.append((len(b) >> 8) & 0xFF)
        header.append(len(b) & 0xFF)
    cl.send(header + b)


def ws_recv(cl):
    try:
        hdr = cl.recv(2)
        if not hdr or len(hdr) < 2: return None
        if (hdr[0] & 0x0F) == 0x8: return None
        masked = hdr[1] & 0x80
        length = hdr[1] & 0x7F
        if length == 126:
            ext = cl.recv(2)
            length = (ext[0] << 8) | ext[1]
        elif length == 127:
            cl.recv(8)
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
def get_page():
    return """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>PicoCar</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-user-select:none;user-select:none;-webkit-touch-callout:none;}
body{background:#0b0f14;color:#fff;font-family:system-ui;display:flex;flex-direction:column;
  align-items:center;justify-content:center;min-height:100vh;min-height:100dvh;gap:18px;padding:16px;}
h1{font-size:22px;color:#f5c842;letter-spacing:2px;}
#status{font-size:13px;padding:4px 14px;border-radius:20px;border:1px solid #333;}
.on{color:#0b6;border-color:#0b644!important;}
.off{color:#e03030;border-color:#e0303044!important;}
.pad{position:relative;width:260px;height:280px;}
.btn{position:absolute;width:80px;height:80px;border:none;border-radius:50%;
  font-size:28px;font-weight:700;color:#fff;cursor:pointer;
  display:flex;align-items:center;justify-content:center;
  transition:all .12s;touch-action:manipulation;box-shadow:0 4px 12px rgba(0,0,0,0.4);}
.btn:active{transform:scale(0.88);filter:brightness(1.3);}
#fwd{background:#f5c842;left:90px;top:60px;}
#back{background:#E03030;left:90px;top:190px;}
#left{background:#4488FF;left:20px;top:125px;}
#right{background:#00CC44;left:160px;top:125px;}
#spin{background:#fff;color:#333;left:180px;top:0;width:64px;height:64px;font-size:22px;}
.act{font-size:16px;color:#f5c842;font-weight:700;min-height:24px;}
.motors{display:flex;gap:20px;font-size:12px;color:#888;}
.mbar{width:80px;height:12px;background:#222;border-radius:6px;overflow:hidden;position:relative;}
.mfill{height:100%;border-radius:6px;position:absolute;transition:width .1s;}
.info{font-size:11px;color:#445;text-align:center;line-height:1.8;}
</style></head><body>
<h1>PicoCar</h1>
<div id="status" class="off">連線中...</div>
<div class="act" id="act"></div>
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
<div class="info">遙控器按鈕或螢幕觸控皆可操作</div>
<script>
let ws,curAction='stop';
const names={fwd:'前進',back:'後退',left:'左轉',right:'右轉',spin:'旋轉',stop:'停車'};
function connect(){
  ws=new WebSocket('ws://'+location.host+'/ws');
  ws.onopen=()=>{document.getElementById('status').className='on';
    document.getElementById('status').textContent='已連線';};
  ws.onmessage=(e)=>{try{
    const d=JSON.parse(e.data);
    curAction=d.a||'stop';
    document.getElementById('act').textContent=names[curAction]||'';
    updateBars(d.l||0,d.r||0);
    // 高亮對應按鈕
    ['fwd','back','left','right','spin'].forEach(id=>{
      document.getElementById(id).style.opacity=id===curAction?'1':'0.6';
    });
  }catch(x){}};
  ws.onclose=()=>{document.getElementById('status').className='off';
    document.getElementById('status').textContent='已斷線';setTimeout(connect,1500);};
  ws.onerror=()=>{try{ws.close();}catch(x){}};
}
function send(a){if(ws&&ws.readyState===1)ws.send(JSON.stringify({action:a}));}
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
  el.addEventListener('touchstart',(e)=>{e.preventDefault();start();},{passive:false});
  el.addEventListener('touchend',(e)=>{e.preventDefault();stop();},{passive:false});
});
connect();
</script></body></html>"""


# ===== 主程式 =====
def main():
    wlan, ip = connect_wifi()
    if not wlan:
        for i in range(20):
            led.toggle(); time.sleep(0.2)
        print("重啟..."); time.sleep(3); reset()

    # HTTP + WebSocket 伺服器
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", 8080))
    srv.listen(2)
    srv.settimeout(0.02)
    print("伺服器啟動 http://%s:8080" % ip)

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
                ws_client.settimeout(0.01)
                print("WS 連線: %s" % str(addr))
        except:
            pass

        # 讀按鈕
        action = "stop"
        l_pwr = 0
        r_pwr = 0

        if btn_stop.value() == 0:
            action = "stop"
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

        # 搖桿（按鈕沒按時）
        if action == "stop":
            jx, jy = read_joy()
            if jy > 0:
                action = "fwd"; l_pwr = 1; r_pwr = 1
            elif jy < 0:
                action = "back"; l_pwr = -1; r_pwr = -1
            elif jx < 0:
                action = "left"; r_pwr = 1
            elif jx > 0:
                action = "right"; l_pwr = 1

        # 讀網頁指令
        if ws_client:
            try:
                msg = ws_recv(ws_client)
                if msg:
                    d = json.loads(msg)
                    wa = d.get("action", "stop")
                    if wa == "fwd":    action = wa; l_pwr = 1;  r_pwr = 1
                    elif wa == "back": action = wa; l_pwr = -1; r_pwr = -1
                    elif wa == "left": action = wa; l_pwr = 0;  r_pwr = 1
                    elif wa == "right":action = wa; l_pwr = 1;  r_pwr = 0
                    elif wa == "spin": action = wa; l_pwr = -1; r_pwr = 1
                    else:              action = "stop"; l_pwr = 0; r_pwr = 0
            except OSError:
                pass
            except:
                try: ws_client.close()
                except: pass
                ws_client = None

            # 回傳狀態
            if ws_client:
                try:
                    ws_send(ws_client, json.dumps({"a": action, "l": l_pwr, "r": r_pwr}))
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
