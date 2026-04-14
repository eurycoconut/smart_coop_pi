#!/usr/bin/env python3
"""
Smart Coop - DHT11 Sensor + Camera to Firebase
FIXED VERSION v3.0

FIXES APPLIED:
1. Camera buffer flush before each capture (solves stale image issue)
2. Unique timestamp with microseconds (prevents filename collisions)
3. Proper camera reinitialization option
4. Enhanced debug logging throughout
5. Verified command deletion before processing
"""

import time
import base64
import os
from datetime import datetime, timedelta

# ============ CONFIGURATION ============
DHT_PIN = 4
DHT_SENSOR_TYPE = 11
FIREBASE_CREDENTIALS_PATH = "firebase_credentials.json"
FIREBASE_DATABASE_URL = "https://smart-coop-6cdfa-default-rtdb.asia-southeast1.firebasedatabase.app/"
FIREBASE_BASE_PATH = "smart_coop"

LIVE_UPDATE_INTERVAL = 5
HISTORY_SAVE_INTERVAL = 300
CLEANUP_INTERVAL = 3600
MAX_HISTORY_AGE_DAYS = 30

CAMERA_DEVICE = 0
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAPTURE_DIR = "captures"

# FIXED: Buffer flush count - read this many frames to clear old data
BUFFER_FLUSH_COUNT = 5

# Debug mode - set to True to see detailed logs
DEBUG_MODE = True

# FIXED: Option to reinitialize camera for each capture (more reliable but slower)
REINIT_CAMERA_PER_CAPTURE = False  # Set to True if buffer flush doesn't work

# ============ IMPORTS ============
print("=" * 50)
print("  Smart Coop - DHT11 + Camera to Firebase")
print("  (FIXED Version - v3.0)")
print("=" * 50)

try:
    import Adafruit_DHT
    print("[OK] Adafruit_DHT loaded")
    DHT_SENSOR = Adafruit_DHT.DHT11 if DHT_SENSOR_TYPE == 11 else Adafruit_DHT.DHT22
    DHT_AVAILABLE = True
except ImportError:
    print("[!!] Adafruit_DHT not found - using simulated data")
    DHT_AVAILABLE = False
    DHT_SENSOR = None

try:
    import firebase_admin
    from firebase_admin import credentials, db
    print("[OK] Firebase library loaded")
    FIREBASE_AVAILABLE = True
except ImportError:
    print("[XX] Firebase library not found!")
    FIREBASE_AVAILABLE = False

try:
    import cv2
    print("[OK] OpenCV loaded")
    CV2_AVAILABLE = True
except ImportError:
    print("[!!] OpenCV not found - camera disabled")
    CV2_AVAILABLE = False

# ============ GLOBAL VARIABLES ============
firebase_db = None
camera = None
camera_is_open = False
last_command_time = 0  # Timestamp of last processed command
capture_count = 0  # FIXED: Track total captures for debugging


# ============ HELPER FUNCTION: DEBUG LOG ============
def debug_log(message, level="INFO"):
    """Print debug message with timestamp if DEBUG_MODE is enabled."""
    if DEBUG_MODE:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [{level}] {message}")


# ============ FIREBASE FUNCTIONS ============
def init_firebase():
    """Initialize Firebase connection."""
    global firebase_db
    
    if not FIREBASE_AVAILABLE:
        print("[XX] Firebase not available")
        return False
    
    if not os.path.exists(FIREBASE_CREDENTIALS_PATH):
        print(f"[XX] Credentials file not found: {FIREBASE_CREDENTIALS_PATH}")
        return False
    
    try:
        cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
        firebase_admin.initialize_app(cred, {
            'databaseURL': FIREBASE_DATABASE_URL
        })
        firebase_db = db.reference(FIREBASE_BASE_PATH)
        print("[OK] Firebase connected!")
        print(f"     Database: {FIREBASE_DATABASE_URL}")
        print(f"     Base path: {FIREBASE_BASE_PATH}")
        
        # IMPORTANT: Clear any existing command on startup
        clear_camera_command_on_startup()
        
        return True
    except Exception as e:
        print(f"[XX] Firebase connection failed: {e}")
        return False


def clear_camera_command_on_startup():
    """Clear any existing camera command when the script starts.
    This prevents auto-triggering from leftover commands."""
    global firebase_db
    
    if firebase_db is None:
        return
    
    try:
        command_ref = firebase_db.child('camera').child('command')
        existing = command_ref.get()
        
        if existing is not None:
            print(f"\n[!!] Found existing command on startup: '{existing}'")
            print("     This would cause auto-trigger - clearing it...")
            
            # Use delete() instead of set(None)
            command_ref.delete()
            time.sleep(0.5)
            
            # Verify it's gone
            verify = command_ref.get()
            if verify is None:
                print("[OK] Startup command cleared successfully!\n")
            else:
                print(f"[!!] Warning: Command might still exist: {verify}\n")
        else:
            print("[OK] No existing camera command - good!\n")
            
    except Exception as e:
        print(f"[!!] Error clearing startup command: {e}\n")


def update_live_data(temperature, humidity):
    """Send live sensor data to Firebase."""
    if firebase_db is None:
        return False
    
    try:
        data = {
            "temperature": temperature,
            "humidity": humidity,
            "is_raining": False,
            "timestamp": datetime.now().isoformat()
        }
        firebase_db.child("environment").set(data)
        return True
    except Exception as e:
        print(f"[XX] Live data error: {e}")
        return False


def save_history_data(temperature, humidity):
    """Save sensor data to history."""
    if firebase_db is None:
        return False
    
    try:
        data = {
            "temperature": temperature,
            "humidity": humidity,
            "is_raining": False,
            "timestamp": datetime.now().isoformat()
        }
        firebase_db.child("environment_history").push(data)
        return True
    except Exception as e:
        print(f"[XX] History save error: {e}")
        return False


def update_system_status(camera_available=False):
    """Update system status in Firebase."""
    if firebase_db is None:
        return
    
    try:
        firebase_db.child("system").update({
            "pi_online": True,
            "last_update": datetime.now().isoformat(),
            "camera_available": camera_available
        })
    except:
        pass


def upload_snapshot(image_path, is_auto_capture=False):
    """Upload camera snapshot to Firebase as base64."""
    global firebase_db, capture_count
    
    if firebase_db is None:
        debug_log("Firebase not connected", "ERROR")
        return None
    
    if not os.path.exists(image_path):
        debug_log(f"Image file not found: {image_path}", "ERROR")
        return None
    
    try:
        # Read image file
        debug_log(f"Reading image: {image_path}")
        with open(image_path, 'rb') as f:
            image_data = f.read()
        
        original_size = len(image_data)
        debug_log(f"Original size: {original_size/1024:.1f} KB")
        
        # Compress if too large (>400KB)
        if original_size > 400000 and CV2_AVAILABLE:
            debug_log("Compressing image...")
            img = cv2.imread(image_path)
            if img is not None:
                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 50]
                _, compressed = cv2.imencode('.jpg', img, encode_param)
                image_data = compressed.tobytes()
                debug_log(f"Compressed to: {len(image_data)/1024:.1f} KB")
        
        # Convert to base64
        debug_log("Converting to base64...")
        base64_image = base64.b64encode(image_data).decode('utf-8')
        debug_log(f"Base64 size: {len(base64_image)/1024:.1f} KB")
        
        # FIXED: Create unique snapshot ID with microseconds to prevent collisions
        timestamp = datetime.now()
        # Using microseconds ensures uniqueness even for rapid captures
        snapshot_id = f"snap_{timestamp.strftime('%Y%m%d_%H%M%S')}_{timestamp.microsecond:06d}"
        
        snapshot_data = {
            'id': snapshot_id,
            'image_base64': base64_image,
            'image_url': '',
            'timestamp': timestamp.isoformat(),
            'is_auto_capture': is_auto_capture,
        }
        
        # Upload to Firebase
        debug_log(f"Uploading to Firebase as {snapshot_id}...")
        firebase_db.child('camera_snapshots').child(snapshot_id).set(snapshot_data)
        
        # Update camera reference
        firebase_db.child('camera').update({
            'latest_snapshot_id': snapshot_id,
            'latest_timestamp': timestamp.isoformat(),
        })
        
        capture_count += 1
        debug_log(f"Upload complete! Snapshot: {snapshot_id} (Total captures: {capture_count})")
        return snapshot_id
        
    except Exception as e:
        debug_log(f"Upload error: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return None


# ============ CAMERA FUNCTIONS ============
def init_camera():
    """Initialize the USB webcam."""
    global camera, camera_is_open
    
    if not CV2_AVAILABLE:
        print("[!!] OpenCV not available - camera disabled")
        return False
    
    try:
        debug_log("Opening camera...")
        camera = cv2.VideoCapture(CAMERA_DEVICE, cv2.CAP_V4L2)
        
        if not camera.isOpened():
            print("[XX] Camera failed to open")
            camera = None
            camera_is_open = False
            return False
        
        # Set resolution
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        
        # FIXED: Set buffer size to minimum (reduces stale frames)
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        # Warm up camera (skip first frames)
        debug_log("Warming up camera...")
        for i in range(10):
            ret, _ = camera.read()
            if not ret:
                debug_log(f"Warmup frame {i+1} failed", "WARN")
            time.sleep(0.1)
        
        # Create captures directory
        os.makedirs(CAPTURE_DIR, exist_ok=True)
        
        camera_is_open = True
        print(f"[OK] Camera initialized ({CAMERA_WIDTH}x{CAMERA_HEIGHT})")
        return True
        
    except Exception as e:
        print(f"[XX] Camera init error: {e}")
        camera = None
        camera_is_open = False
        return False


def flush_camera_buffer():
    """
    FIXED: Flush the camera buffer to get fresh frames.
    This is crucial for getting current images instead of stale buffered ones.
    """
    global camera
    
    if camera is None:
        return False
    
    debug_log(f"Flushing camera buffer ({BUFFER_FLUSH_COUNT} frames)...")
    
    for i in range(BUFFER_FLUSH_COUNT):
        ret, _ = camera.read()
        if not ret:
            debug_log(f"Buffer flush frame {i+1} failed", "WARN")
        # Small delay to allow new frames to arrive
        time.sleep(0.05)
    
    debug_log("Buffer flush complete")
    return True


def capture_image():
    """
    Capture a single image from the camera.
    
    FIXED: Now flushes buffer before capture to ensure fresh image.
    """
    global camera, camera_is_open
    
    if REINIT_CAMERA_PER_CAPTURE:
        # Option B: Reinitialize camera for each capture (slower but more reliable)
        debug_log("Reinitializing camera for capture...")
        close_camera()
        time.sleep(0.5)
        if not init_camera():
            debug_log("Failed to reinitialize camera", "ERROR")
            return None
    
    if camera is None or not camera_is_open:
        debug_log("Camera not available", "ERROR")
        return None
    
    try:
        # FIXED: Flush buffer to clear stale frames
        flush_camera_buffer()
        
        # Small delay after flush
        time.sleep(0.1)
        
        # Now capture fresh frame
        debug_log("Capturing fresh frame...")
        ret, frame = camera.read()
        
        if not ret or frame is None:
            debug_log("Failed to capture frame", "ERROR")
            return None
        
        # FIXED: Generate unique filename with microseconds
        timestamp = datetime.now()
        filename = f"capture_{timestamp.strftime('%Y%m%d_%H%M%S')}_{timestamp.microsecond:06d}.jpg"
        filepath = os.path.join(CAPTURE_DIR, filename)
        
        # Save image
        cv2.imwrite(filepath, frame)
        
        if os.path.exists(filepath):
            size = os.path.getsize(filepath)
            debug_log(f"Image saved: {filename} ({size/1024:.1f} KB)")
            return filepath
        else:
            debug_log("Failed to save image file", "ERROR")
            return None
            
    except Exception as e:
        debug_log(f"Capture error: {e}", "ERROR")
        return None


def close_camera():
    """Release the camera."""
    global camera, camera_is_open
    
    if camera is not None:
        debug_log("Releasing camera...")
        camera.release()
        camera = None
        camera_is_open = False
        debug_log("Camera released")


# ============ SENSOR FUNCTIONS ============
def read_sensor():
    """Read temperature and humidity from DHT sensor."""
    if DHT_AVAILABLE and DHT_SENSOR is not None:
        try:
            humidity, temperature = Adafruit_DHT.read_retry(
                DHT_SENSOR, DHT_PIN, retries=3, delay_seconds=1
            )
            if humidity is not None and temperature is not None:
                return round(temperature, 1), round(humidity, 1)
            else:
                # Sensor read failed - use simulated data
                debug_log("Sensor read failed - using simulated data", "WARN")
                import random
                return round(25 + random.uniform(-2, 2), 1), round(60 + random.uniform(-5, 5), 1)
        except Exception as e:
            debug_log(f"Sensor error: {e}", "WARN")
            import random
            return round(25 + random.uniform(-2, 2), 1), round(60 + random.uniform(-5, 5), 1)
    else:
        # No sensor - use simulated data
        import random
        return round(25 + random.uniform(-2, 2), 1), round(60 + random.uniform(-5, 5), 1)


# ============ CAMERA COMMAND HANDLER (FIXED) ============
def check_camera_command():
    """
    Check for camera capture command from Firebase.
    
    FIXES APPLIED:
    1. Uses delete() instead of set(None)
    2. Adds cooldown to prevent rapid re-triggering
    3. Verifies deletion before proceeding
    4. Flushes camera buffer for fresh capture
    5. Enhanced debug logging
    """
    global firebase_db, last_command_time
    
    if firebase_db is None:
        return
    
    current_time = time.time()
    
    # COOLDOWN: Don't process commands within 5 seconds of each other
    if current_time - last_command_time < 5:
        return
    
    try:
        command_ref = firebase_db.child('camera').child('command')
        command = command_ref.get()
        
        # DEBUG: Show what we're reading from Firebase
        if DEBUG_MODE and command is not None:
            debug_log(f"Firebase command value: '{command}' (type: {type(command).__name__})")
        
        # Only process if command is exactly 'capture'
        if command == 'capture':
            print("\n" + "=" * 50)
            print("📷 CAMERA CAPTURE COMMAND RECEIVED!")
            print("=" * 50)
            
            # Update timestamp FIRST to prevent re-entry
            last_command_time = current_time
            
            # STEP 1: DELETE the command (not set to None!)
            debug_log("Step 1: Deleting command from Firebase...")
            command_ref.delete()
            
            # Wait for deletion to propagate
            time.sleep(0.5)
            
            # STEP 2: VERIFY the deletion worked
            verify = command_ref.get()
            if verify is not None:
                debug_log(f"Warning: Command still exists: '{verify}'", "WARN")
                debug_log("Trying delete again...")
                command_ref.delete()
                time.sleep(0.3)
                
                verify2 = command_ref.get()
                if verify2 is not None:
                    debug_log("Cannot delete command! Skipping to prevent loop.", "ERROR")
                    return
            
            debug_log("Step 2: Command deleted and verified")
            
            # STEP 3: Initialize camera if needed
            if not camera_is_open:
                debug_log("Step 3: Camera not open, initializing...")
                if not init_camera():
                    debug_log("Failed to initialize camera", "ERROR")
                    return
            else:
                debug_log("Step 3: Camera already open")
            
            # STEP 4: Capture image (buffer flush happens inside)
            debug_log("Step 4: Capturing image...")
            image_path = capture_image()
            
            if image_path is None:
                debug_log("Image capture failed", "ERROR")
                return
            
            # STEP 5: Upload to Firebase
            debug_log("Step 5: Uploading to Firebase...")
            snapshot_id = upload_snapshot(image_path, is_auto_capture=False)
            
            if snapshot_id:
                print("=" * 50)
                print(f"✅ SUCCESS! Snapshot: {snapshot_id}")
                print("=" * 50 + "\n")
            else:
                debug_log("Upload failed", "ERROR")
        
        # Clean up any weird/unexpected command values
        elif command is not None and command != '':
            debug_log(f"Unexpected command value: '{command}' - clearing it", "WARN")
            command_ref.delete()
                
    except Exception as e:
        debug_log(f"Command check error: {e}", "ERROR")


# ============ MAIN LOOP ============
def main():
    """Main program loop."""
    global camera_is_open
    
    print()
    
    # Initialize Firebase
    firebase_ok = init_firebase()
    if not firebase_ok:
        print("\n[XX] Cannot continue without Firebase!")
        return
    
    # Initialize Camera
    camera_ok = init_camera()
    
    print("\n" + "=" * 50)
    print(f"Sensor: DHT{DHT_SENSOR_TYPE} on GPIO {DHT_PIN}")
    print(f"Firebase: {'CONNECTED' if firebase_ok else 'OFFLINE'}")
    print(f"Camera: {'READY' if camera_ok else 'DISABLED'}")
    print(f"Debug Mode: {'ON' if DEBUG_MODE else 'OFF'}")
    print(f"Buffer Flush: {BUFFER_FLUSH_COUNT} frames")
    print(f"Reinit Per Capture: {'YES' if REINIT_CAMERA_PER_CAPTURE else 'NO'}")
    print("=" * 50)
    print("Press Ctrl+C to stop")
    print("=" * 50 + "\n")
    
    last_history_save = 0
    
    try:
        while True:
            current_time = time.time()
            
            # Check for camera command from app
            check_camera_command()
            
            # Read sensor
            temperature, humidity = read_sensor()
            
            if temperature is not None and humidity is not None:
                # Display reading
                time_str = datetime.now().strftime("%H:%M:%S")
                print(f"[{time_str}] Temp: {temperature}°C, Humidity: {humidity}%")
                
                # Send live data
                if update_live_data(temperature, humidity):
                    print("  ✓ Live data sent")
                else:
                    print("  ✗ Live data failed")
                
                # Update system status
                update_system_status(camera_available=camera_is_open)
                
                # Save history every 5 minutes
                if current_time - last_history_save >= HISTORY_SAVE_INTERVAL:
                    if save_history_data(temperature, humidity):
                        print("  ✓ History saved")
                    last_history_save = current_time
            
            print()  # Empty line for readability
            time.sleep(LIVE_UPDATE_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        
        # Close camera
        close_camera()
        print("  Camera closed")
        
        # Update system status
        if firebase_db:
            try:
                firebase_db.child("system").update({
                    "pi_online": False,
                    "last_update": datetime.now().isoformat()
                })
                print("  Firebase status updated")
            except:
                pass
        
        print(f"  Total captures this session: {capture_count}")
        print("Goodbye! 🐔")


# ============ ENTRY POINT ============
if __name__ == "__main__":
    main()
