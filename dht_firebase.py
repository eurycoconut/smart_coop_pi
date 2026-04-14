#!/usr/bin/env python3

import time
from datetime import datetime

# ============ CONFIGURATION ============
DHT_PIN = 4           # GPIO pin for DHT11 data
DHT_SENSOR_TYPE = 11  # DHT11 sensor (use 22 for DHT22)
READ_INTERVAL = 5     # Seconds between readings


FIREBASE_DATABASE_URL = "https://smart-coop-6cdfa-default-rtdb.asia-southeast1.firebasedatabase.app/" 
FIREBASE_CREDENTIALS_PATH = "firebase_credentials.json"
FIREBASE_BASE_PATH = "smart_coop"

# ============ IMPORTS ============
try:
    import Adafruit_DHT
    DHT_AVAILABLE = True
    print("✓ Adafruit_DHT library loaded")
except ImportError:
    DHT_AVAILABLE = False
    print("✗ Adafruit_DHT not found - will use mock data")

try:
    import firebase_admin
    from firebase_admin import credentials, db
    FIREBASE_AVAILABLE = True
    print("✓ Firebase library loaded")
except ImportError:
    FIREBASE_AVAILABLE = False
    print("✗ Firebase library not found")

# ============ SENSOR SETUP ============
if DHT_AVAILABLE:
    if DHT_SENSOR_TYPE == 11:
        DHT_SENSOR = Adafruit_DHT.DHT11
    else:
        DHT_SENSOR = Adafruit_DHT.DHT22
    print(f"✓ Using DHT{DHT_SENSOR_TYPE} on GPIO {DHT_PIN}")

# ============ FIREBASE SETUP ============
firebase_ref = None

def init_firebase():
    """Initialize Firebase connection."""
    global firebase_ref
    
    if not FIREBASE_AVAILABLE:
        print("✗ Firebase not available")
        return False
    
    try:
        import os
        if not os.path.exists(FIREBASE_CREDENTIALS_PATH):
            print(f"✗ Credentials file not found: {FIREBASE_CREDENTIALS_PATH}")
            return False
        
        cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
        firebase_admin.initialize_app(cred, {
            'databaseURL': FIREBASE_DATABASE_URL
        })
        
        firebase_ref = db.reference(FIREBASE_BASE_PATH)
        
        # Test connection
        firebase_ref.child('system').update({
            'pi_online': True,
            'last_boot': datetime.now().isoformat()
        })
        
        print("✓ Firebase connected successfully!")
        return True
        
    except Exception as e:
        print(f"✗ Firebase error: {e}")
        return False

def read_dht():
    """Read temperature and humidity from DHT sensor."""
    if not DHT_AVAILABLE:
        # Mock data for testing without sensor
        import random
        temp = 25 + random.uniform(-2, 2)
        humidity = 60 + random.uniform(-5, 5)
        print(f"[MOCK] Temp: {temp:.1f}°C, Humidity: {humidity:.1f}%")
        return temp, humidity
    
    try:
        humidity, temperature = Adafruit_DHT.read_retry(
            DHT_SENSOR, 
            DHT_PIN,
            retries=3,
            delay_seconds=0.5
        )
        
        if humidity is not None and temperature is not None:
            print(f"[REAL] Temp: {temperature:.1f}°C, Humidity: {humidity:.1f}%")
            return temperature, humidity
        else:
            print("✗ Failed to read DHT sensor")
            return None, None
            
    except Exception as e:
        print(f"✗ DHT error: {e}")
        return None, None

def send_to_firebase(temperature, humidity):
    """Send sensor data to Firebase."""
    if firebase_ref is None:
        print("✗ Firebase not initialized")
        return False
    
    try:
        data = {
            'temperature': round(temperature, 2),
            'humidity': round(humidity, 2),
            'is_raining': False,  # No rain sensor yet
            'timestamp': datetime.now().isoformat()
        }
        
        firebase_ref.child('environment').update(data)
        print(f"✓ Sent to Firebase: {data}")
        return True
        
    except Exception as e:
        print(f"✗ Firebase send error: {e}")
        return False

def main():
    """Main loop."""
    print("\n" + "="*50)
    print("  Smart Coop - DHT11 to Firebase")
    print("="*50)
    print(f"Sensor: DHT{DHT_SENSOR_TYPE} on GPIO {DHT_PIN}")
    print(f"Interval: {READ_INTERVAL} seconds")
    print(f"Firebase: {FIREBASE_DATABASE_URL}")
    print("="*50 + "\n")
    
    # Initialize Firebase
    firebase_ok = init_firebase()
    
    if not firebase_ok:
        print("\n⚠ Running in LOCAL MODE (no Firebase)")
        print("Check your firebase_credentials.json file\n")
    
    print("\nStarting sensor readings... (Press Ctrl+C to stop)\n")
    
    reading_count = 0
    
    try:
        while True:
            reading_count += 1
            print(f"\n--- Reading #{reading_count} ---")
            
            # Read sensor
            temperature, humidity = read_dht()
            
            if temperature is not None and humidity is not None:
                # Send to Firebase if connected
                if firebase_ok:
                    send_to_firebase(temperature, humidity)
            
            # Wait for next reading
            time.sleep(READ_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n\nStopping...")
        if firebase_ref:
            firebase_ref.child('system').update({
                'pi_online': False,
                'last_shutdown': datetime.now().isoformat()
            })
        print("Goodbye!")

if __name__ == '__main__':
    main()
