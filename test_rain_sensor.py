
import RPi.GPIO as GPIO
import time

# ─── Configuration ────────────────────────────────────
DO_PIN      = 17    # Rain sensor DO → GPIO17 (Pin 11)
BUZZER_PIN  = 27    # Buzzer S/SIG  → GPIO27 (Pin 13)
FREQUENCY   = 2000  # Buzzer tone in Hz
HOLD_TIME   = 3.0   # Keep buzzing for this many seconds after rain stops

# ─── GPIO Setup ──────────────────────────────────────
GPIO.setmode(GPIO.BCM)
GPIO.setup(DO_PIN, GPIO.IN)
GPIO.setup(BUZZER_PIN, GPIO.OUT)

pwm = GPIO.PWM(BUZZER_PIN, FREQUENCY)

print("Rain + Buzzer running. Press Ctrl+C to stop.\n")

# ─── Main Loop ───────────────────────────────────────
is_buzzing       = False
last_rain_time   = 0   # timestamp of the last rain detection

try:
    while True:
        rain = GPIO.input(DO_PIN) == GPIO.LOW  # LOW = rain detected

        if rain:
            last_rain_time = time.time()       # reset the hold timer
            if not is_buzzing:
                print("🌧  Rain detected! Buzzer ON")
                pwm.start(50)
                is_buzzing = True

        elif is_buzzing:
            time_since_rain = time.time() - last_rain_time
            if time_since_rain >= HOLD_TIME:   # only stop after hold timer expires
                print(f"☀️  No rain for {HOLD_TIME}s. Buzzer OFF")
                pwm.stop()
                is_buzzing = False

        time.sleep(0.1)

except KeyboardInterrupt:
    print("\nStopped by user.")

finally:
    pwm.stop()
    GPIO.cleanup()
    print("GPIO cleaned up.")