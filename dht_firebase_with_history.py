#!/usr/bin/env python3
"""
Smart Coop - DHT11 to Firebase with History
============================================
This script reads DHT11 sensor data and sends it to Firebase.
- Live data: Updates every 5 seconds (for real-time display)
- History data: Saves every 5 minutes (for charts/history page)
- Auto-cleanup: Deletes data older than 30 days

Author: Smart Coop FYP Project
"""

import time
import json
from datetime import datetime, timedelta

# ============ CONFIGURATION ============
DHT_PIN = 4                          # GPIO pin for DHT11
DHT_SENSOR_TYPE = 11                 # 11 = DHT11, 22 = DHT22
FIREBASE_CREDENTIALS_PATH = "firebase_credentials.json"
FIREBASE_DATABASE_URL = "https://smart-coop-6cdfa-default-rtdb.asia-southeast1.firebasedatabase.app/"
FIREBASE_BASE_PATH = "smart_coop"

# Timing settings
LIVE_UPDATE_INTERVAL = 5             # Seconds between live updates
HISTORY_SAVE_INTERVAL = 300          # Seconds between history saves (5 minutes)
CLEANUP_INTERVAL = 3600              # Seconds between cleanup runs (1 hour)
MAX_HISTORY_AGE_DAYS = 30            # Delete history older than this

# ============ LIBRARY IMPORTS ============
print("=" * 50)
print("  Smart Coop - DHT11 to Firebase (with History)")
print("=" * 50)

# Try to import Adafruit DHT
try:
    import Adafruit_DHT
    print("✓ Adafruit_DHT library loaded")
    if DHT_SENSOR_TYPE == 11:
        DHT_SENSOR = Adafruit_DHT.DHT11
    else:
        DHT_SENSOR = Adafruit_DHT.DHT22
    DHT_AVAILABLE = True
except ImportError:
    print("✗ Adafruit_DHT not found - using simulated data")
    DHT_AVAILABLE = False

# Try to import Firebase
try:
    import firebase_admin
    from firebase_admin import credentials, db
    print("✓ Firebase library loaded")
    FIREBASE_AVAILABLE = True
except ImportError:
    print("✗ Firebase library not found")
    print("  Install with: pip3 install firebase-admin")
    FIREBASE_AVAILABLE = False

# ============ FIREBASE INITIALIZATION ============
firebase_db = None

def init_firebase():
    """Initialize Firebase connection."""
    global firebase_db
    
    if not FIREBASE_AVAILABLE:
        print("⚠ Firebase not available - running in local mode")
        return False
    
    try:
        cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
        firebase_admin.initialize_app(cred, {
            'databaseURL': FIREBASE_DATABASE_URL
        })
        firebase_db = db.reference(FIREBASE_BASE_PATH)
        print("✓ Firebase connected!")
        print(f"  Database: {FIREBASE_DATABASE_URL}")
        print(f"  Base path: {FIREBASE_BASE_PATH}")
        return True
    except FileNotFoundError:
        print("✗ Firebase credentials file not found!")
        print(f"  Expected: {FIREBASE_CREDENTIALS_PATH}")
        return False
    except Exception as e:
        print(f"✗ Firebase error: {e}")
        return False

# ============ SENSOR READING ============
def read_sensor():
    """Read temperature and humidity from DHT sensor."""
    if DHT_AVAILABLE:
        humidity, temperature = Adafruit_DHT.read_retry(DHT_SENSOR, DHT_PIN)
        if humidity is not None and temperature is not None:
            return round(temperature, 1), round(humidity, 1)
        else:
            print("✗ Sensor read failed")
            return None, None
    else:
        # Simulated data for testing
        import random
        temp = round(25 + random.uniform(-2, 2), 1)
        hum = round(60 + random.uniform(-5, 5), 1)
        return temp, hum

# ============ FIREBASE UPDATES ============
def update_live_data(temperature, humidity):
    """Update live environment data in Firebase."""
    if firebase_db is None:
        return False
    
    try:
        timestamp = datetime.now().isoformat()
        data = {
            "temperature": temperature,
            "humidity": humidity,
            "is_raining": False,  # You can integrate rain sensor later
            "timestamp": timestamp
        }
        firebase_db.child("environment").set(data)
        return True
    except Exception as e:
        print(f"✗ Live update error: {e}")
        return False

def save_history_data(temperature, humidity):
    """Save reading to history for charts."""
    if firebase_db is None:
        return False
    
    try:
        timestamp = datetime.now().isoformat()
        data = {
            "temperature": temperature,
            "humidity": humidity,
            "is_raining": False,
            "timestamp": timestamp
        }
        # Push creates unique key automatically
        firebase_db.child("environment_history").push(data)
        print(f"  → History saved: {temperature}°C, {humidity}%")
        return True
    except Exception as e:
        print(f"✗ History save error: {e}")
        return False

def update_system_status():
    """Update system status showing Pi is online."""
    if firebase_db is None:
        return False
    
    try:
        data = {
            "pi_online": True,
            "last_update": datetime.now().isoformat(),
            "uptime_seconds": int(time.time() - start_time)
        }
        firebase_db.child("system").update(data)
        return True
    except Exception as e:
        print(f"✗ System status error: {e}")
        return False

def cleanup_old_history():
    """Delete history data older than MAX_HISTORY_AGE_DAYS."""
    if firebase_db is None:
        return
    
    try:
        cutoff = (datetime.now() - timedelta(days=MAX_HISTORY_AGE_DAYS)).isoformat()
        
        # Get all history entries
        history_ref = firebase_db.child("environment_history")
        all_data = history_ref.order_by_child("timestamp").end_at(cutoff).get()
        
        if all_data:
            deleted_count = 0
            for key in all_data.keys():
                history_ref.child(key).delete()
                deleted_count += 1
            
            if deleted_count > 0:
                print(f"  → Cleaned up {deleted_count} old history entries")
    except Exception as e:
        print(f"✗ Cleanup error: {e}")

# ============ MAIN LOOP ============
start_time = time.time()

def main():
    """Main loop - read sensor and update Firebase."""
    print(f"\n✓ Using DHT{DHT_SENSOR_TYPE} on GPIO {DHT_PIN}")
    
    # Initialize Firebase
    firebase_connected = init_firebase()
    
    if not firebase_connected:
        print("\n⚠ Running in LOCAL MODE (no Firebase)")
        print("  Data will be displayed but not uploaded")
    
    print("\n" + "=" * 50)
    print("Starting sensor readings...")
    print("Press Ctrl+C to stop")
    print("=" * 50 + "\n")
    
    last_history_save = 0
    last_cleanup = 0
    reading_count = 0
    
    try:
        while True:
            current_time = time.time()
            reading_count += 1
            
            # Read sensor
            temperature, humidity = read_sensor()
            
            if temperature is not None and humidity is not None:
                # Get current timestamp
                now = datetime.now()
                time_str = now.strftime("%H:%M:%S")
                
                # Display reading
                print(f"[{time_str}] Temp: {temperature}°C, Humidity: {humidity}%")
                
                # Update live data (every reading)
                if firebase_connected:
                    if update_live_data(temperature, humidity):
                        print(f"  ✓ Live data sent")
                    
                    # Update system status
                    update_system_status()
                
                # Save to history (every HISTORY_SAVE_INTERVAL seconds)
                if current_time - last_history_save >= HISTORY_SAVE_INTERVAL:
                    if firebase_connected:
                        save_history_data(temperature, humidity)
                    last_history_save = current_time
                    
                    # Show next save time
                    next_save = HISTORY_SAVE_INTERVAL
                    print(f"  ℹ Next history save in {next_save} seconds")
                
                # Cleanup old data (every CLEANUP_INTERVAL seconds)
                if current_time - last_cleanup >= CLEANUP_INTERVAL:
                    if firebase_connected:
                        cleanup_old_history()
                    last_cleanup = current_time
                
                print()  # Empty line for readability
            
            # Wait for next reading
            time.sleep(LIVE_UPDATE_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n" + "=" * 50)
        print("Stopping Smart Coop...")
        print(f"Total readings: {reading_count}")
        
        # Update system status to offline
        if firebase_connected and firebase_db:
            try:
                firebase_db.child("system").update({
                    "pi_online": False,
                    "last_update": datetime.now().isoformat()
                })
                print("✓ System marked as offline")
            except:
                pass
        
        print("=" * 50)

if __name__ == "__main__":
    main()
