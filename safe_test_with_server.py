import machine
import utime
import random
import math
import network
import uasyncio as asyncio
from machine import Pin, I2C, PWM
import ssd1306
from microdot import Microdot

# --- Wi-Fi Configuration ---
WIFI_SSID = "Your_WiFi_Name"
WIFI_PASSWORD = "Your_WiFi_Password"

# --- Hardware Initialization ---
i2c0 = I2C(0, sda=Pin(0), scl=Pin(1), freq=400000)
i2c1 = I2C(1, sda=Pin(2), scl=Pin(3), freq=400000)

# 128x64 Displays for Core Tumblers
disp_left   = ssd1306.SSD1306_I2C(128, 64, i2c0, addr=0x3C)
disp_center = ssd1306.SSD1306_I2C(128, 64, i2c0, addr=0x3D)
disp_right  = ssd1306.SSD1306_I2C(128, 64, i2c1, addr=0x3C)
# 128x32 Display for Proximity Sensor
disp_gauge  = ssd1306.SSD1306_I2C(128, 32, i2c1, addr=0x3D)

servo = PWM(Pin(15))
servo.freq(50)

# Audio & Headphone Detection Pins
buzzer = Pin(14, Pin.OUT)
hp_audio = Pin(13, Pin.OUT)
hp_detect = Pin(12, Pin.IN, Pin.PULL_UP)

# Rotary Encoder (PEC11R-4220K-S0024)
pin_a = Pin(16, Pin.IN, Pin.PULL_UP)
pin_b = Pin(17, Pin.IN, Pin.PULL_UP)
pin_sw = Pin(18, Pin.IN, Pin.PULL_UP)

# --- Game State Settings ---
game_mode = 0  # 0 = Menu Selection, 1 = Active Cracking, 2 = Victory Unlock
DIFFICULTIES = ["EASY", "MED", "HARD"]
menu_index = 0

difficulty_levels = {
    "EASY": {"max_val": 23, "range": 6},     
    "MED":  {"max_val": 47, "range": 12},    
    "HARD": {"max_val": 95, "range": 24}     
}

selected_diff = "EASY"
dial_max = 23
proximity_range = 6
secret_combo = [0, 0, 0]
player_combo = [0, 0, 0]  # Tracks what the user actually submitted
current_stage = 0  
stage_locked_values = ["--", "--", "--"]

encoder_value = 0
last_state_a = pin_a.value()
current_dial_number = 0
last_dial_number = 0

# --- Timer, Inactivity Watchdog, & Leaderboard ---
game_start_time = 0
last_activity_time = 0
IDLE_TIMEOUT_MS = 60000  
current_player_nfc = "GUEST"
ip_address = "0.0.0.0"
leaderboard_data = []

# --- Needle Physics Globals ---
gauge_current_width = 0.0
gauge_velocity = 0.0
SPRING_K = 0.25      
DAMPING = 0.65       

# --- Web Server Instance Setup ---
app = Microdot()

@app.route('/')
async def index(request):
    sorted_scores = sorted(leaderboard_data, key=lambda x: (x['diff'], x['time']))
    rows_html = ""
    for idx, score in enumerate(sorted_scores, 1):
        rows_html += f"<tr><td>{idx}</td><td>{score['player']}</td><td class=\"diff-{score['diff']}\">{score['diff']}</td><td>{score['time']}</td></tr>"

    html = f"""<!DOCTYPE html>
    <html>
    <head>
        <title>Safe Cracker Leaderboard</title>
        <meta http-equiv="refresh" content="5">
        <style>
            body {{ font-family: 'Courier New', monospace; background: #121212; color: #00ff00; text-align: center; padding: 20px; }}
            table {{ margin: 20px auto; border-collapse: collapse; width: 90%; max-width: 600px; background: #1a1a1a; }}
            th, td {{ padding: 10px; border: 1px solid #333; text-align: center; }}
            th {{ background: #222; }}
            .diff-HARD {{ color: #ff3333; font-weight: bold; }}
            .diff-MED {{ color: #ffaa00; font-weight: bold; }}
            .diff-EASY {{ color: #00aaff; font-weight: bold; }}
        </style>
    </head>
    <body>
        <h2>:: VAULT BREAKER LEADERBOARD ::</h2>
        <table>
            <tr><th>Rank</th><th>Player ID</th><th>Difficulty</th><th>Time</th></tr>
            {rows_html if rows_html else '<tr><td colspan="4">No scores locked yet!</td></tr>'}
        </table>
    </body>
    </html>"""
    return html, 200, {'Content-Type': 'text/html'}

def connect_wifi():
    global ip_address
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    attempts = 0
    while not wlan.isconnected() and attempts < 10:
        utime.sleep(1)
        attempts += 1
    if wlan.isconnected():
        ip_address = wlan.ifconfig()[0]
        print(f"Network online. IP: {ip_address}")
    else:
        print("Wi-Fi timeout. Running locally.")

def set_servo_angle(angle):
    min_duty = 1638  
    max_duty = 8192  
    duty = int(min_duty + (angle / 180.0) * (max_duty - min_duty))
    servo.duty_u16(duty)

def tone(freq, duration_ms):
    active_output = hp_audio if hp_detect.value() == 1 else buzzer
    period = 1.0 / freq
    delay = period / 2.0
    cycles = int(freq * (duration_ms / 1000.0))
    for _ in range(cycles):
        active_output.value(1)
        utime.sleep(delay)
        active_output.value(0)
        utime.sleep(delay)

def fast_click(us_duration):
    active_output = hp_audio if hp_detect.value() == 1 else buzzer
    active_output.value(1)
    utime.sleep_us(us_duration)
    active_output.value(0)

def draw_huge_number(display, num_str, x_offset, y):
    font_32 = {
        '0': [0x3F, 0x61, 0x41, 0x41, 0x61, 0x3F],
        '1': [0x00, 0x42, 0x7F, 0x40, 0x00, 0x00],
        '2': [0x43, 0x61, 0x51, 0x49, 0x47, 0x41],
        '3': [0x22, 0x41, 0x49, 0x49, 0x49, 0x36],
        '4': [0x18, 0x14, 0x12, 0x7F, 0x10, 0x10],
        '5': [0x27, 0x45, 0x45, 0x45, 0x4D, 0x31],
        '6': [0x3E, 0x49, 0x49, 0x49, 0x49, 0x32],
        '7': [0x01, 0x01, 0x71, 0x09, 0x05, 0x03],
        '8': [0x36, 0x49, 0x49, 0x49, 0x49, 0x36],
        '9': [0x26, 0x49, 0x49, 0x49, 0x49, 0x3E],
        '-': [0x08, 0x08, 0x08, 0x08, 0x08, 0x08]
    }
    current_x = x_offset
    for char in num_str:
        if char in font_32:
            matrix = font_32[char]
            for col_idx, col_byte in enumerate(matrix):
                for bit_idx in range(8):
                    if col_byte & (1 << bit_idx):
                        display.fill_rect(current_x + (col_idx * 2), y + (bit_idx * 4), 2, 4, 1)
            current_x += 16
        else:
            current_x += 12

def read_encoder(pin):
    global last_state_a, encoder_value, current_dial_number, last_dial_number, menu_index, last_activity_time
    
    c_state_a = pin_a.value()
    if c_state_a != last_state_a:
        if pin_b.value() != c_state_a: 
            step = 1   
        else: 
            step = -1  
            
        if game_mode == 0:
            menu_index += step
            if menu_index > 2: menu_index = 0
            elif menu_index < 0: menu_index = 2
            fast_click(150)
            
        elif game_mode == 1:
            last_activity_time = utime.ticks_ms()  
            last_dial_number = current_dial_number
            target_number = (current_dial_number + step)
            
            if target_number > dial_max: target_number = 0
            elif target_number < 0: target_number = dial_max
            
            required_step = -1 if current_stage == 1 else 1
            
            if step != required_step:
                if selected_diff == "EASY":
                    current_dial_number = target_number
                    fast_click(150)
                elif selected_diff == "MED":
                    fast_click(800) 
                elif selected_diff == "HARD":
                    current_dial_number = -99 
            else:
                current_dial_number = target_number
                if current_dial_number == secret_combo[current_stage]:
                    fast_click(400) 
                    utime.sleep_ms(12)  
                else:
                    fast_click(150) 

        last_state_a = c_state_a

pin_a.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=read_encoder)

def update_menu_displays():
    disp_left.fill(0); disp_center.fill(0); disp_right.fill(0); disp_gauge.fill(0)
    
    if menu_index == 0: disp_left.text("> TIER-1 <", 28, 28)
    else: disp_left.text("  TIER-1  ", 28, 28)
        
    if menu_index == 1: disp_center.text("> TIER-2 <", 32, 28)
    else: disp_center.text("  TIER-2  ", 32, 28)
        
    if menu_index == 2: disp_right.text("> TIER-3 <", 28, 28)
    else: disp_right.text("  TIER-3  ", 28, 28)
        
    disp_gauge.text(f"SYS_IP: {ip_address}", 8, 12)
    
    disp_left.show(); disp_center.show(); disp_right.show(); disp_gauge.show()

def render_individual_stage(display, stage_idx, header_text):
    display.fill(0)
    display.text(header_text, 36, 0)
    
    if current_stage == stage_idx:
        dir_text = "TURN CCW <" if stage_idx == 1 else "TURN CW >"
        display.text(dir_text, 24, 14)
        val_str = f"{current_dial_number:02d}"
        draw_huge_number(display, val_str, 48, 28)
    else:
        display.text("STATUS", 40, 16)
        val_str = f"{stage_locked_values[stage_idx]:02d}" if stage_locked_values[stage_idx] != "--" else "--"
        draw_huge_number(display, val_str, 48, 28)
        
    display.show()

def update_game_displays():
    render_individual_stage(disp_left, 0, "CORE_01")
    render_individual_stage(disp_center, 1, "CORE_02")
    render_individual_stage(disp_right, 2, "CORE_03")

def update_tumbler_sensor():
    global gauge_current_width, gauge_velocity
    disp_gauge.fill(0)
    disp_gauge.text("TUMBLER SENSOR", 8, 0)
    
    target = secret_combo[current_stage]
    distance = abs(target - current_dial_number)
    if distance > ((dial_max + 1) / 2):
        distance = (dial_max + 1) - distance

    target_width = (1.0 - (distance / proximity_range)) * 104 if distance <= proximity_range else 0.0

    displacement = target_width - gauge_current_width
    gauge_velocity = (gauge_velocity + (SPRING_K * displacement)) * DAMPING
    gauge_current_width += gauge_velocity

    draw_width = max(0, min(104, int(gauge_current_width)))
    if draw_width > 2:
        disp_gauge.rect(10, 14, 108, 12, 1)
        disp_gauge.fill_rect(12, 16, draw_width, 8, 1)
    else:
        disp_gauge.text("[ NO SIGNAL ]", 16, 16)
    disp_gauge.show()

def handle_failure():
    """Triggers visual flash error and dramatic alarm buzz on code mismatch."""
    global game_mode, current_stage, encoder_value, current_dial_number, stage_locked_values, player_combo, gauge_current_width, gauge_velocity
    
    # Render static visual error message
    disp_left.fill(0); disp_center.fill(0); disp_right.fill(0); disp_gauge.fill(0)
    disp_left.text("CRACK", 44, 16); disp_left.text("FAILED", 40, 32)
    disp_center.text("CRACK", 44, 16); disp_center.text("FAILED", 40, 32)
    disp_right.text("CRACK", 44, 16); disp_right.text("FAILED", 40, 32)
    disp_gauge.text("!! LOCKOUT !!", 16, 12)
    
    disp_left.show(); disp_center.show(); disp_right.show(); disp_gauge.show()
    
    # Heavy sounding descending failure warning tones
    tone(220, 250)
    utime.sleep_ms(80)
    tone(147, 500)
    
    # Clear state variables entirely back to menu defaults
    current_stage = 0
    encoder_value = 0
    current_dial_number = 0
    stage_locked_values = ["--", "--", "--"]
    player_combo = [0, 0, 0]
    gauge_current_width = 0.0
    gauge_velocity = 0.0
    
    utime.sleep_ms(2000) # Give them 2 full seconds to sit with their failure
    game_mode = 0

# --- Async Game Loop Engine ---
async def game_loop():
    global game_mode, selected_diff, dial_max, proximity_range, secret_combo, current_stage
    global encoder_value, current_dial_number, stage_locked_values, gauge_current_width, gauge_velocity, game_start_time, last_activity_time, player_combo
    
    while True:
        if game_mode == 0:
            update_menu_displays()
            
            if pin_sw.value() == 0:
                utime.sleep_ms(50) 
                if pin_sw.value() == 0:
                    selected_diff = DIFFICULTIES[menu_index]
                    dial_max = difficulty_levels[selected_diff]["max_val"]
                    proximity_range = difficulty_levels[selected_diff]["range"]
                    
                    secret_combo = [random.randint(0, dial_max) for _ in range(3)]
                    player_combo = [0, 0, 0]
                    current_stage, encoder_value, current_dial_number = 0, 0, 0
                    stage_locked_values = ["--", "--", "--"]
                    gauge_current_width, gauge_velocity = 0.0, 0.0
                    
                    tone(880, 100)
                    utime.sleep_ms(50)
                    tone(1320, 200)
                    
                    game_start_time = utime.ticks_ms()
                    last_activity_time = utime.ticks_ms()
                    game_mode = 1 
                    while pin_sw.value() == 0: await asyncio.sleep_ms(10)
                
        elif game_mode == 1:
            if utime.ticks_diff(utime.ticks_ms(), last_activity_time) > IDLE_TIMEOUT_MS:
                tone(600, 100)
                tone(400, 100)
                tone(200, 250)
                game_mode = 0
                continue

            if current_dial_number == -99:
                last_activity_time = utime.ticks_ms()  
                tone(150, 500) 
                current_stage = 0
                encoder_value = 0
                current_dial_number = 0
                stage_locked_values = ["--", "--", "--"]
                player_combo = [0, 0, 0]
                gauge_current_width, gauge_velocity = 0.0, 0.0
                continue

            update_game_displays()
            update_tumbler_sensor()
            
            if pin_sw.value() == 0:
                utime.sleep_ms(50)
                if pin_sw.value() == 0:
                    last_activity_time = utime.ticks_ms()  
                    
                    # Capture user selection unconditionally
                    player_combo[current_stage] = current_dial_number
                    stage_locked_values[current_stage] = current_dial_number
                    tone(1000, 80)  # Standard clean entry beep
                    
                    current_stage += 1
                    encoder_value, current_dial_number = 0, 0
                    gauge_current_width, gauge_velocity = 0.0, 0.0
                    
                    # If all 3 slots are populated, evaluate code entries
                    if current_stage >= 3:
                        if player_combo == secret_combo:
                            game_mode = 2
                        else:
                            handle_failure()
                            
                    while pin_sw.value() == 0: await asyncio.sleep_ms(10)

        elif game_mode == 2:
            disp_left.fill(0); disp_center.fill(0); disp_right.fill(0)
            disp_left.text("CORE", 44, 16); disp_left.text("UNLOCKED", 32, 32); disp_left.show()
            disp_center.text("CORE", 44, 16); disp_center.text("UNLOCKED", 32, 32); disp_center.show()
            disp_right.text("CORE", 44, 16); disp_right.text("UNLOCKED", 32, 32); disp_right.show()
            
            disp_gauge.fill(0)
            disp_gauge.text("ACCESS GRANTED", 12, 12)
            disp_gauge.show()
            
            final_elapsed_ms = utime.ticks_diff(utime.ticks_ms(), game_start_time)
            time_str = f"{(final_elapsed_ms // 60000):02d}:{(final_elapsed_ms // 1000 % 60):02d}"
            leaderboard_data.append({"player": current_player_nfc, "diff": selected_diff, "time": time_str})
            
            set_servo_angle(90) 
            tone(523, 150)
            tone(659, 150)
            tone(784, 150)
            tone(1047, 400)
            
            await asyncio.sleep(8) 
            set_servo_angle(0)
            game_mode = 0

        await asyncio.sleep_ms(30) 

async def main():
    connect_wifi()
    asyncio.create_task(app.start_server(host='0.0.0.0', port=80))
    await game_loop()

set_servo_angle(0)
asyncio.run(main())