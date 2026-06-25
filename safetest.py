import machine
import utime
from ssd1306 import SSD1306_I2C

# --- 1. DISPLAY SETUP ---
# Hardware I2C0 on Pins 0, 1
i2c0 = machine.I2C(0, sda=machine.Pin(0), scl=machine.Pin(1), freq=400000)
# Hardware I2C1 on Pins 2, 3
i2c1 = machine.I2C(1, sda=machine.Pin(2), scl=machine.Pin(3), freq=400000)

# Initialize the three separate displays
disp_left   = SSD1306_I2C(128, 64, i2c0, addr=0x3C) # Screen 1
disp_center = SSD1306_I2C(128, 64, i2c1, addr=0x3C) # Screen 2
disp_right  = SSD1306_I2C(128, 64, i2c1, addr=0x3D) # Screen 3 (Jumper changed)

# --- 2. INPUT SETUP (Rotary Encoder) ---
enc_clk = machine.Pin(16, machine.Pin.IN, machine.Pin.PULL_UP)
enc_dt  = machine.Pin(17, machine.Pin.IN, machine.Pin.PULL_UP)
enc_sw  = machine.Pin(18, machine.Pin.IN, machine.Pin.PULL_UP)

# --- 3. ACTUATOR & AUDIO SETUP ---
servo = machine.PWM(machine.Pin(15))
servo.freq(50) # Standard 50Hz for SG90
buzzer = machine.Pin(14, machine.Pin.OUT)

# --- HELPER FUNCTIONS ---
def set_servo_angle(angle):
    # Map 0-180 degrees to standard duty cycles (approx 1000 to 9000 out of 65535)
    duty = int(1000 + (angle / 180) * 8000)
    servo.duty_u16(duty)

def beep(duration_ms=50):
    buzzer.value(1)
    utime.sleep_ms(duration_ms)
    buzzer.value(0)

def update_screens(left_txt, center_txt, right_txt):
    # Quick clear and rewrite helper
    for disp, txt in [(disp_left, left_txt), (disp_center, center_txt), (disp_right, right_txt)]:
        disp.fill(0)
        disp.text(txt, 10, 25)
        disp.show()

# --- INITIAL STATE ---
set_servo_angle(0) # Locked position
update_screens("READY", "READY", "READY")

# --- MAIN LOOP PLACEHOLDER ---
last_clk = enc_clk.value()
current_value = 0

while True:
    # Basic polling example for the encoder
    current_clk = enc_clk.value()
    if current_clk != last_clk and current_clk == 0:
        if enc_dt.value() != current_clk:
            current_value += 1
        else:
            current_value -= 1
        beep(10) # Click sound
        print(f"Dial Position: {current_value}")
        
    last_clk = current_clk
    
    # Check button press
    if not enc_sw.value():
        beep(100)
        print("Button pressed - Submit guess!")
        # Trigger servo unlock demo
        set_servo_angle(90) # Open
        utime.sleep(3)
        set_servo_angle(0)  # Relock
        
    utime.sleep_ms(1)