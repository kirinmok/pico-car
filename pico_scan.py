from machine import Pin, ADC
import time

# 設定右側彩色按鈕
btn_red = Pin(16, Pin.IN, Pin.PULL_UP)
btn_green = Pin(17, Pin.IN, Pin.PULL_UP)
btn_blue = Pin(18, Pin.IN, Pin.PULL_UP)
btn_yellow = Pin(19, Pin.IN, Pin.PULL_UP)
btn_white = Pin(20, Pin.IN, Pin.PULL_UP)

# 設定左側按鈕
btn_sw1 = Pin(21, Pin.IN, Pin.PULL_UP)
btn_joy = Pin(28, Pin.IN, Pin.PULL_UP)

# 設定搖桿類比輸入
joy_x = ADC(Pin(26))
joy_y = ADC(Pin(27))
joy_alt = ADC(Pin(28))

print("--- 遙控器測試啟動 ---")
print("請隨意按壓按鈕或推動搖桿，觀察數值變化 (按 Ctrl+C 停止)")
time.sleep(2)

while True:
    print(f"搖桿 ADC26: {joy_x.read_u16():5d} | ADC27: {joy_y.read_u16():5d} | ADC28: {joy_alt.read_u16():5d}")
    print(f"彩色按鍵 -> 紅:{btn_red.value()} 綠:{btn_green.value()} 藍:{btn_blue.value()} 黃:{btn_yellow.value()} 白:{btn_white.value()}")
    print(f"左側按鍵 -> GP21:{btn_sw1.value()} GP28:{btn_joy.value()}")
    print("-" * 50)
    time.sleep(0.5)
