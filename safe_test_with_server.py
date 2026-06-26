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
# Dual-bus I2C setup for the four separate display panels
i2c0 = I2C(0, sda=Pin(0), scl=Pin(1), freq=400000)
i2c1 = I2C(1, sda=Pin(2), scl=Pin(3), freq=400000)

disp_left   = ssd1306.SSD1306_I2C(128, 64, i2c0, addr=0x3C)
disp_center = ssd1306.SSD1306_I2C(128, 64, i2c0, addr=0x3D)
disp_right  = ssd1306.SSD1306_I2C(128, 64, i2c1, addr=0x3C)
disp_gauge  = ssd1306.SSD1306_I2C(128, 32, i2c1, addr=0x3D)

# Actuators & Indicators
servo = PWM(Pin(15))
servo.freq(50)
buzzer = Pin(14, Pin.OUT)

# Rotary Encoder (PEC11R-4015F-S0024)
pin_a = Pin(16, Pin.IN, Pin.PULL_UP)
pin_b = Pin(17, Pin.IN, Pin.PULL_UP)
pin_sw = Pin(18, Pin.IN, Pin.PULL_UP)  # Integrated shaft switch

# --- Game State Settings ---
# Modes: 0 = Menu Selection, 1 = Active Safe Cracking, 2 = Victory Unlock Sequence
game_mode = 0 

DIFFICULTIES = ["EASY", "MED", "HARD"]
menu_index = 0  # 0 = Easy, 1 = Med, 2 = Hard

difficulty_levels = {
    "EASY": {"max_val": 23, "range": 6},     
    "MED":  {"max_val": 47, "range": 12},    
    "HARD": {"max_val": 95, "range": 24}     
}

selected_diff = "EASY"
dial_max = 23
proximity_range = 6
secret_combo = [0, 0, 0]
current_stage = 0  
stage_locked_values = ["--", "--", "--"]

# Dial position tracking
encoder_value = 0
last_state_a = pin_a.value()
current_dial_number = 0
last_dial_number = 0

# --- Timer & Leaderboard Storage ---
game_start_time = 0
current_player_nfc = "GUEST"
ip_address = "0.0.0.0"

# High scores array kept in volatile RAM memory
leaderboard_data = []

# --- Needle Physics Globals ---
gauge_current_width = 0.0
gauge_velocity = 0.0
SPRING_K = 0.25      # Virtual spring stiffness coefficient
DAMPING = 0.65       # Viscous friction dampening factor

# --- Web Server Instance Setup ---
app = Microdot()

@app.route('/')
async def index(request):
    # Sort leaderboard output tables by difficulty profile type, then execution duration
    sorted_scores = sorted(leaderboard_data, key=lambda x: (x['diff'], x['time']))
    
    rows_html = ""
    for idx, score in enumerate(sorted_scores, 1):
        rows_html += f"""
        <tr>
            <td>{idx}</td>
            <td>{score['player']}</td>
            <td class="diff-{score['diff']}">{score['diff']}</td>
            <td>{score['time']}</td>
        </tr>"""

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

# --- Network Management Task ---
def connect_wifi():
    global ip_address
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    
    print("Initializing network interface connection status...")
    attempts = 0
    while not wlan.isconnected() and attempts < 10:
        utime.sleep(1)
        attempts += 1
        
    if wlan.isconnected():
        ip_address = wlan.ifconfig()[0]
        print(f"Network online. Device hosted endpoint IP: {ip_address}")
    else:
        print("Wi-Fi timeout frame exceeded. Running locally.")

# --- Functional Utilities ---
def set_servo_angle(angle):
    min_duty = 1638  
    max_duty = 8192  
    duty = int(min_duty + (angle / 180.0) * (max_duty - min_duty))
    servo.duty_u16(duty)

def tone(freq, duration_ms):
    period = 1.0 / freq
    delay = period / 2.0
    cycles = int(freq * (duration_ms / 1000.0))
    for _ in range(cycles):
        buzzer.value(1)
        utime.sleep(delay)
        buzzer.value(0)
        utime.sleep(delay)

# --- Hardware ISR Interrupt Function ---
def read_encoder(pin):
    global last_state_a, encoder_value, current_dial_number, last_dial_number, menu_index
    
    c_state_a = pin_a.value()
    if c_state_a != last_state_a:
        if pin_b.value() != c_state_a: 
            step = 1   # Clockwise movement vector
        else: 
            step = -1  # Counter-Clockwise movement vector
            
        # --- MODE 0: DIFFICULTY SELECTION MENU ---
        if game_mode == 0:
            menu_index += step
            if menu_index > 2: menu_index = 0
            elif menu_index < 0: menu_index = 2
            
            # Crisp menu step click tone
            buzzer.value(1)
            utime.sleep_us(150)
            buzzer.value(0)
            
        # --- MODE 1: ACTIVE CRACKING ENGINE ---
        elif game_mode == 1:
            last_dial_number = current_dial_number
            target_number = (current_dial_number + step)
            
            # Bound handling rollover computations
            if target_number > dial_max: target_number = 0
            elif target_number < 0: target_number = dial_max
            
            # Stage verification rules: Stage 0=CW, Stage 1=CCW, Stage 2=CW
            required_step = -1 if current_stage == 1 else 1
            
            if step != required_step:
                if selected_diff == "EASY":
                    current_dial_number = target_number
                    buzzer.value(1)
                    utime.sleep_us(150)
                    buzzer.value(0)
                elif selected_diff == "MED":
                    # Lock input progression state cleanly (Freeze metric)
                    buzzer.value(1)
                    utime.sleep_us(800) # Heavy friction thud
                    buzzer.value(0)
                elif selected_diff == "HARD":
                    # Mark reset register for execution via safe main async loop thread
                    current_dial_number = -99 
            else:
                current_dial_number = target_number
                
                # Check for tactile alignment positioning targets
                if current_dial_number == secret_combo[current_stage]:
                    buzzer.value(1)
                    utime.sleep_us(400) # Heavy structural layout snap click
                    buzzer.value(0)
                    utime.sleep_ms(12)  # Induced haptic sticky drag pause
                else:
                    buzzer.value(1)
                    utime.sleep_us(150) # Lightweight progression tick
                    buzzer.value(0)

        last_state_a = c_state_a

pin_a.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=read_encoder)

# --- Visual Canvas Rendering Subroutines ---
def update_menu_displays():
    disp_left.fill(0)
    disp_center.fill(0)
    disp_right.fill(0)
    disp_gauge.fill(0)
    
    # Left Panel Layout (EASY Option)
    if menu_index == 0: disp_left.text("> EASY <", 32, 28)
    else: disp_left.text("  EASY  ", 32, 28)
        
    # Center Panel Layout (MEDIUM Option)
    if menu_index == 1: disp_center.text("> MED <", 36, 28)
    else: disp_center.text("  MED  ", 36, 28)
        
    # Right Panel Layout (HARD Option)
    if menu_index == 2: disp_right.text("> HARD <", 32, 28)
    else: disp_right.text("  HARD  ", 32, 28)
        
    disp_gauge.text(f"IP: {ip_address}", 12, 12)
    
    disp_left.show()
    disp_center.show()
    disp_right.show()
    disp_gauge.show()

def update_game_displays():
    # Left Screen
    disp_left.fill(0)
    disp_left.text("STAGE 1", 36, 0)
    val = f"{current_dial_number:02d}" if current_stage == 0 else f"{stage_locked_values[0]:02d}"
    disp_left.text(val, 52, 28)
    disp_left.show()
    
    # Center Screen
    disp_center.fill(0)
    disp_center.text("STAGE 2", 36, 0)
    val = "--" if current_stage < 1 else (f"{current_dial_number:02d}" if current_stage == 1 else f"{stage_locked_values[1]:02d}")
    disp_center.text(val, 52, 28)
    disp_center.show()
    
    # Right Screen
    disp_right.fill(0)
    disp_right.text("STAGE 3", 36, 0)
    val = "--" if current_stage < 2 else (f"{current_dial_number:02d}" if current_stage == 2 else "OPN")
    disp_right.text(val, 52, 28)
    disp_right.show()

def update_tumbler_sensor():
    global gauge_current_width, gauge_velocity
    disp_gauge.fill(0)
    disp_gauge.text("TUMBLER SENSOR", 8, 0)
    
    target = secret_combo[current_stage]
    distance = abs(target - current_dial_number)
    if distance > ((dial_max + 1) / 2):
        distance = (dial_max + 1) - distance

    target_width = (1.0 - (distance / proximity_range)) * 104 if distance <= proximity_range else 0.0

    # Elastic mass-damper system execution steps
    displacement = target_width - gauge_current_width
    gauge_velocity = (gauge_velocity + (SPRING_K * displacement)) * DAMPING
    gauge_current_width += gauge_velocity

    draw_width = max(0, min(104, int(gauge_current_width)))
    if draw_width > 2:
        disp_gauge.rect(10, 16, 108, 12, 1)
        disp_gauge.fill_rect(12, 18, draw_width, 8, 1)
    else:
        disp_gauge.text("[ NO SIGNAL ]", 16, 16)
    disp_gauge.show()

# --- Asynchronous Game Core Thread Execution ---
async def game_loop():
    global game_mode, selected_diff, dial_max, proximity_range, secret_combo, current_stage
    global encoder_value, current_dial_number, stage_locked_values, gauge_current_width, gauge_velocity, game_start_time
    
    while True:
        if game_mode == 0:
            update_menu_displays()
            
            # Scan shaft position select switch changes
            if pin_sw.value() == 0:
                utime.sleep_ms(50) # Filter signal transients
                if pin_sw.value() == 0:
                    selected_diff = DIFFICULTIES[menu_index]
                    dial_max = difficulty_levels[selected_diff]["max_val"]
                    proximity_range = difficulty_levels[selected_diff]["range"]
                    
                    # Compute combo parameters cleanly
                    secret_combo = [random.randint(0, dial_max) for _ in range(3)]
                    current_stage, encoder_value, current_dial_number = 0, 0, 0
                    stage_locked_values = ["--", "--", "--"]
                    gauge_current_width, gauge_velocity = 0.0, 0.0
                    
                    tone(880, 100)
                    utime.sleep_ms(50)
                    tone(1320, 200)
                    
                    game_start_time = utime.ticks_ms()
                    game_mode = 1 
                    while pin_sw.value() == 0: await asyncio.sleep_ms(10)
                
        elif game_mode == 1:
            # Handle execution interruptions routed from Hard Mode violation resets
            if current_dial_number == -99:
                tone(150, 500) # Structural penalty alert chime
                current_stage = 0
                encoder_value = 0
                current_dial_number = 0
                stage_locked_values = ["--", "--", "--"]
                gauge_current_width, gauge_velocity = 0.0, 0.0
                continue

            update_game_displays()
            update_tumbler_sensor()
            
            # Render vector alignment prompt texts onto indicator spaces
            if current_stage == 1: disp_gauge.text("<- SPIN CCW", 8, 24)
            else: disp_gauge.text("SPIN CW ->", 48, 24)
            disp_gauge.show()
            
            if pin_sw.value() == 0:
                utime.sleep_ms(50)
                if pin_sw.value() == 0:
                    # CRITICAL FIX: Evaluate confirmation targets only on exact step match placement
                    if current_dial_number == secret_combo[current_stage]:
                        tone(1200, 100)
                        stage_locked_values[current_stage] = current_dial_number
                        current_stage += 1
                        encoder_value, current_dial_number = 0, 0
                        gauge_current_width, gauge_velocity = 0.0, 0.0
                        if current_stage >= 3: game_mode = 2
                    else:
                        tone(220, 400) # Incorrect tracking attempt notice buzz
                    while pin_sw.value() == 0: await asyncio.sleep_ms(10)

        elif game_mode == 2:
            update_game_displays()
            disp_gauge.fill(0)
            disp_gauge.text("LOCK UNLOCKED", 12, 16)
            disp_gauge.show()
            
            # Format elapsed millisecond run metrics into standard timestamp elements
            final_elapsed_ms = utime.ticks_diff(utime.ticks_ms(), game_start_time)
            time_str = f"{(final_elapsed_ms // 60000):02d}:{(final_elapsed_ms // 1000 % 60):02d}"
            leaderboard_data.append({"player": current_player_nfc, "diff": selected_diff, "time": time_str})
            
            set_servo_angle(90) # Drive mechanical linkage lock down
            tone(523, 150)
            tone(659, 150)
            tone(784, 150)
            tone(1047, 400)
            
            await asyncio.sleep(8) # Maintain latch access window profile timing constraints
            set_servo_angle(0)
            game_mode = 0

        await asyncio.sleep_ms(30) # Yield tracking ticks directly to core web service frame threads

# --- Thread Allocator Setup Initialization Run ---
async def main():
    connect_wifi()
    # Concurrently initialize microdot micro-service instances
    asyncio.create_task(app.start_server(host='0.0.0.0', port=80))
    # Execute primary gameplay sequence engine task 
    await game_loop()

# System startup confirmation execution
set_servo_angle(0)
asyncio.run(main())