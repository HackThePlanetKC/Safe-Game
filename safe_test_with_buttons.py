import machine
import utime
import random
import math
from machine import Pin, I2C, PWM
import ssd1306

# --- Hardware Initialization ---
i2c0 = I2C(0, sda=Pin(0), scl=Pin(1), freq=400000)
i2c1 = I2C(1, sda=Pin(2), scl=Pin(3), freq=400000)

disp_left   = ssd1306.SSD1306_I2C(128, 64, i2c0, addr=0x3C)
disp_center = ssd1306.SSD1306_I2C(128, 64, i2c0, addr=0x3D)
disp_right  = ssd1306.SSD1306_I2C(128, 64, i2c1, addr=0x3C)
disp_gauge  = ssd1306.SSD1306_I2C(128, 32, i2c1, addr=0x3D)

servo = PWM(Pin(15))
servo.freq(50)
buzzer = Pin(14, Pin.OUT)

pin_a = Pin(16, Pin.IN, Pin.PULL_UP)
pin_b = Pin(17, Pin.IN, Pin.PULL_UP)
pin_sw = Pin(18, Pin.IN, Pin.PULL_UP)

btn_easy  = Pin(6, Pin.IN, Pin.PULL_UP)
btn_med   = Pin(7, Pin.IN, Pin.PULL_UP)
btn_hard  = Pin(8, Pin.IN, Pin.PULL_UP)
btn_start = Pin(9, Pin.IN, Pin.PULL_UP)

# --- Game State Settings ---
game_mode = 0 

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

encoder_value = 0
last_state_a = pin_a.value()
current_dial_number = 0

# --- Needle Physics Globals ---
gauge_current_width = 0.0
gauge_velocity = 0.0
SPRING_K = 0.25      # Stiffness of the bounce gauge spring
DAMPING = 0.65       # Friction/absorption constant to let it settle

# --- Audio & Mechanical Helpers ---
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

# --- UI Rendering Functions ---
def render_menu():
    disp_left.fill(0)
    disp_center.fill(0)
    disp_right.fill(0)
    disp_gauge.fill(0)
    
    disp_left.text("DIFFICULTY", 24, 0)
    disp_left.text(" EASY (24)", 12, 24, 1 if selected_diff == "EASY" else 0)
    disp_left.text(" MED  (48)", 12, 36, 1 if selected_diff == "MED" else 0)
    disp_left.text(" HARD (96)", 12, 48, 1 if selected_diff == "HARD" else 0)
    
    disp_center.text("PRESS START", 20, 20)
    disp_center.text("TO BEGIN", 32, 34)
    
    disp_right.text("[ IDLE ]", 36, 28)
    disp_gauge.text(f"MODE: {selected_diff}", 16, 12)
    
    disp_left.show()
    disp_center.show()
    disp_right.show()
    disp_gauge.show()

def update_game_displays():
    # Render Stage 1 (Left)
    disp_left.fill(0)
    disp_left.text("STAGE 1", 36, 0)
    val = f"{current_dial_number:02d}" if current_stage == 0 else f"{stage_locked_values[0]:02d}"
    disp_left.text(val, 52, 28)
    disp_left.show()

    # Render Stage 2 (Center)
    disp_center.fill(0)
    disp_center.text("STAGE 2", 36, 0)
    if current_stage < 1:
        val = "--"
    elif current_stage == 1:
        val = f"{current_dial_number:02d}"
    else:
        val = f"{stage_locked_values[1]:02d}"
    disp_center.text(val, 52, 28)
    disp_center.show()

    # Render Stage 3 (Right)
    disp_right.fill(0)
    disp_right.text("STAGE 3", 36, 0)
    if current_stage < 2:
        val = "--"
    elif current_stage == 2:
        val = f"{current_dial_number:02d}"
    else:
        val = "OPN"
    disp_right.text(val, 52, 28)
    disp_right.show()

def update_tumbler_sensor():
    global gauge_current_width, gauge_velocity
    
    disp_gauge.fill(0)
    disp_gauge.text("TUMBLER SENSOR", 8, 0)
    
    target = secret_combo[current_stage]
    distance = abs(target - current_dial_number)
    
    # Dynamic rollover logic wrapping
    if distance > ((dial_max + 1) / 2):
        distance = (dial_max + 1) - distance

    # Determine our true mathematical target width
    if distance <= proximity_range:
        proximity = 1.0 - (distance / proximity_range)
        target_width = proximity * 104
    else:
        target_width = 0.0

    # Spring-mass-damper physics simulation step
    # Hooke's Law: Force = -k * displacement
    displacement = target_width - gauge_current_width
    spring_force = SPRING_K * displacement
    
    # Update velocity with spring acceleration, then apply damping friction
    gauge_velocity += spring_force
    gauge_velocity *= DAMPING
    
    # Advance the gauge position state step
    gauge_current_width += gauge_velocity

    # Clamp bounds to screen drawing canvas limits
    draw_width = int(gauge_current_width)
    if draw_width < 0:
        draw_width = 0
    elif draw_width > 104:
        draw_width = 104

    # Draw the animated gauge layout frame
    if draw_width > 2:
        disp_gauge.rect(10, 16, 108, 12, 1)
        disp_gauge.fill_rect(12, 18, draw_width, 8, 1)
    else:
        disp_gauge.text("[ NO SIGNAL ]", 16, 16)
        
    disp_gauge.show()

# --- Hardware Interrupt Routine ---
def read_encoder(pin):
    global last_state_a, encoder_value, current_dial_number
    if game_mode != 1:
        return 
        
    current_state_a = pin_a.value()
    if current_state_a != last_state_a:
        if pin_b.value() != current_state_a:
            encoder_value += 1
        else:
            encoder_value -= 1
            
        current_dial_number = abs(encoder_value) % (dial_max + 1)
        last_state_a = current_state_a

pin_a.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=read_encoder)

# --- Core Initialization Run ---
set_servo_angle(0)
tone(1000, 100)

# --- Primary Routine Engine ---
while True:
    if game_mode == 0:
        render_menu()
        
        if btn_easy.value() == 0:
            selected_diff = "EASY"
            tone(600, 50)
            while btn_easy.value() == 0: utime.sleep_ms(10)
            
        elif btn_med.value() == 0:
            selected_diff = "MED"
            tone(750, 50)
            while btn_med.value() == 0: utime.sleep_ms(10)
            
        elif btn_hard.value() == 0:
            selected_diff = "HARD"
            tone(900, 50)
            while btn_hard.value() == 0: utime.sleep_ms(10)
            
        elif btn_start.value() == 0:
            dial_max = difficulty_levels[selected_diff]["max_val"]
            proximity_range = difficulty_levels[selected_diff]["range"]
            
            secret_combo = [random.randint(0, dial_max) for _ in range(3)]
            
            current_stage = 0
            encoder_value = 0
            current_dial_number = 0
            stage_locked_values = ["--", "--", "--"]
            
            # Reset physics tracking values cleanly for the new game run
            gauge_current_width = 0.0
            gauge_velocity = 0.0
            
            tone(880, 100)
            utime.sleep_ms(50)
            tone(1320, 250)
            
            game_mode = 1 
            while btn_start.value() == 0: utime.sleep_ms(10)

    elif game_mode == 1:
        update_game_displays()
        update_tumbler_sensor()
        
        if pin_sw.value() == 0:
            utime.sleep_ms(50) 
            if pin_sw.value() == 0:
                if current_dial_number == secret_combo[current_stage]:
                    tone(1200, 100)
                    utime.sleep_ms(50)
                    tone(1500, 200)
                    
                    stage_locked_values[current_stage] = current_dial_number
                    current_stage += 1
                    encoder_value = 0
                    current_dial_number = 0
                    
                    # Reset spring tracking variables so it doesn't slam into the next window
                    gauge_current_width = 0.0
                    gauge_velocity = 0.0
                    
                    if current_stage >= 3:
                        game_mode = 2 
                else:
                    tone(220, 400) 
                    
                while pin_sw.value() == 0: utime.sleep_ms(10)

    elif game_mode == 2:
        update_game_displays()
        
        disp_gauge.fill(0)
        disp_gauge.text("TUMBLER SENSOR", 8, 0)
        disp_gauge.text("LOCK UNLOCKED", 12, 16)
        disp_gauge.show()
        
        set_servo_angle(90) 
        
        tone(523, 150)
        tone(659, 150)
        tone(784, 150)
        tone(1047, 400)
        
        utime.sleep(8) 
        
        set_servo_angle(0)
        game_mode = 0 
        tone(440, 300)

    utime.sleep_ms(33) # Keeps the physics updates ticking smoothly at ~30Hz