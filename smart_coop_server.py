#!/usr/bin/env python3
"""
Smart Chicken Coop - Complete Integrated Server
Version: 2.0 (Phase 2 - Live Streaming)

Features:
- MJPEG Live Streaming (Port 8080)
- DHT22/DHT11 Sensor Monitoring
- Firebase Real-time Sync
- Camera Snapshot on Command
- Buffer flush for fresh captures

Author: Smart Coop FYP Project
"""

import time
import base64
import os
import threading
from datetime import datetime
from io import BytesIO

# ============ CONFIGURATION ============
# Network
STREAM_HOST = '0.0.0.0'  # Listen on all interfaces
STREAM_PORT = 8080

# Hardware
DHT_PIN = 4
DHT_SENSOR_TYPE = 11  # 11 for DHT11, 22 for DHT22
CAMERA_DEVICE = 0
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 360

# Firebase
FIREBASE_CREDENTIALS_PATH = "firebase_credentials.json"
FIREBASE_DATABASE_URL = "https://smart-coop-6cdfa-default-rtdb.asia-southeast1.firebasedatabase.app/"
FIREBASE_BASE_PATH = "smart_coop"

# Timing
LIVE_UPDATE_INTERVAL = 5  # Seconds between sensor updates
HISTORY_SAVE_INTERVAL = 300  # Seconds between history saves (5 min)
STREAM_FPS = 15  # Target FPS for live stream
BUFFER_FLUSH_COUNT = 5  # Frames to flush before snapshot

# Directories
CAPTURE_DIR = "captures"

# Debug
DEBUG_MODE = True

# ============ IMPORTS ============
print("=" * 60)
print("  🐔 Smart Chicken Coop - Integrated Server v2.0")
print("  📡 Live Streaming + Sensors + Firebase")
print("=" * 60)

# Flask for streaming
try:
    from flask import Flask, Response, jsonify
    print("[OK] Flask loaded")
    FLASK_AVAILABLE = True
except ImportError:
    print("[XX] Flask not found! Run: pip3 install flask --break-system-packages")
    FLASK_AVAILABLE = False

# OpenCV for camera
try:
    import cv2
    print("[OK] OpenCV loaded")
    CV2_AVAILABLE = True
except ImportError:
    print("[XX] OpenCV not found!")
    CV2_AVAILABLE = False

# Firebase
try:
    import firebase_admin
    from firebase_admin import credentials, db
    print("[OK] Firebase library loaded")
    FIREBASE_AVAILABLE = True
except ImportError:
    print("[XX] Firebase library not found!")
    FIREBASE_AVAILABLE = False

# DHT Sensor
try:
    import Adafruit_DHT
    print("[OK] Adafruit_DHT loaded")
    DHT_SENSOR = Adafruit_DHT.DHT11 if DHT_SENSOR_TYPE == 11 else Adafruit_DHT.DHT22
    DHT_AVAILABLE = True
except ImportError:
    print("[!!] Adafruit_DHT not found - using simulated data")
    DHT_AVAILABLE = False
    DHT_SENSOR = None

print("=" * 60)

# ============ GLOBAL VARIABLES ============
firebase_db = None
camera = None
camera_lock = threading.Lock()  # Thread-safe camera access
camera_is_open = False
last_command_time = 0
capture_count = 0
stream_active = True

# Flask app
app = Flask(__name__)


# ============ HELPER FUNCTIONS ============
def debug_log(message, level="INFO"):
    """Print debug message with timestamp."""
    if DEBUG_MODE:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [{level}] {message}")


def get_local_ip():
    """Get the Pi's local IP address."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "192.168.0.101"  # Fallback


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
        
        # Clear any existing command on startup
        clear_camera_command_on_startup()
        
        # Update stream URL in Firebase
        local_ip = get_local_ip()
        stream_url = f"http://{local_ip}:{STREAM_PORT}/video_feed"
        firebase_db.child('camera').update({
            'stream_url': stream_url,
            'stream_available': True
        })
        print(f"[OK] Stream URL saved to Firebase: {stream_url}")
        
        return True
    except Exception as e:
        print(f"[XX] Firebase connection failed: {e}")
        return False


def clear_camera_command_on_startup():
    """Clear any existing camera command on startup."""
    global firebase_db
    
    if firebase_db is None:
        return
    
    try:
        command_ref = firebase_db.child('camera').child('command')
        existing = command_ref.get()
        
        if existing is not None:
            print(f"[!!] Found existing command on startup: '{existing}' - clearing...")
            command_ref.delete()
            time.sleep(0.5)
            print("[OK] Startup command cleared")
    except Exception as e:
        print(f"[!!] Error clearing startup command: {e}")


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
        debug_log(f"Live data error: {e}", "ERROR")
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
        debug_log(f"History save error: {e}", "ERROR")
        return False


def update_system_status(camera_available=False, streaming=False):
    """Update system status in Firebase."""
    if firebase_db is None:
        return
    
    try:
        firebase_db.child("system").update({
            "pi_online": True,
            "last_update": datetime.now().isoformat(),
            "camera_available": camera_available,
            "streaming_active": streaming
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
        debug_log(f"Reading image: {image_path}")
        with open(image_path, 'rb') as f:
            image_data = f.read()
        
        original_size = len(image_data)
        debug_log(f"Original size: {original_size/1024:.1f} KB")
        
        # Compress if too large
        if original_size > 400000 and CV2_AVAILABLE:
            debug_log("Compressing image...")
            img = cv2.imread(image_path)
            if img is not None:
                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 50]
                _, compressed = cv2.imencode('.jpg', img, encode_param)
                image_data = compressed.tobytes()
                debug_log(f"Compressed to: {len(image_data)/1024:.1f} KB")
        
        # Convert to base64
        base64_image = base64.b64encode(image_data).decode('utf-8')
        
        # Create unique snapshot ID
        timestamp = datetime.now()
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
        debug_log(f"Upload complete! Snapshot: {snapshot_id}")
        return snapshot_id
        
    except Exception as e:
        debug_log(f"Upload error: {e}", "ERROR")
        return None


# ============ CAMERA FUNCTIONS ============
def init_camera():
    """Initialize the USB webcam."""
    global camera, camera_is_open
    
    if not CV2_AVAILABLE:
        print("[XX] OpenCV not available - camera disabled")
        return False
    
    try:
        with camera_lock:
            debug_log("Opening camera...")
            camera = cv2.VideoCapture(CAMERA_DEVICE, cv2.CAP_V4L2)
            
            if not camera.isOpened():
                # Try without V4L2
                camera = cv2.VideoCapture(CAMERA_DEVICE)
                
            if not camera.isOpened():
                print("[XX] Camera failed to open")
                camera = None
                camera_is_open = False
                return False
            
            # Set resolution
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
            camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            # Warm up camera
            debug_log("Warming up camera...")
            for _ in range(10):
                camera.read()
                time.sleep(0.05)
            
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


def get_frame():
    """Get a single frame from camera (thread-safe)."""
    global camera, camera_is_open
    
    if camera is None or not camera_is_open:
        return None
    
    with camera_lock:
        ret, frame = camera.read()
        if ret:
            return frame
    return None


def flush_camera_buffer():
    """Flush camera buffer to get fresh frames."""
    global camera
    
    if camera is None:
        return False
    
    debug_log(f"Flushing camera buffer ({BUFFER_FLUSH_COUNT} frames)...")
    
    with camera_lock:
        for i in range(BUFFER_FLUSH_COUNT):
            camera.read()
            time.sleep(0.03)
    
    debug_log("Buffer flush complete")
    return True


def capture_snapshot():
    """Capture a single snapshot image."""
    global camera, camera_is_open
    
    if camera is None or not camera_is_open:
        debug_log("Camera not available", "ERROR")
        return None
    
    try:
        # Flush buffer for fresh image
        flush_camera_buffer()
        time.sleep(0.1)
        
        # Capture fresh frame
        debug_log("Capturing fresh frame...")
        frame = get_frame()
        
        if frame is None:
            debug_log("Failed to capture frame", "ERROR")
            return None
        
        # Generate unique filename
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
    
    with camera_lock:
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
        except Exception as e:
            debug_log(f"Sensor error: {e}", "WARN")
    
    # Fallback to simulated data
    import random
    return round(25 + random.uniform(-2, 2), 1), round(60 + random.uniform(-5, 5), 1)


# ============ CAMERA COMMAND HANDLER ============
def check_camera_command():
    """Check for camera capture command from Firebase."""
    global firebase_db, last_command_time
    
    if firebase_db is None:
        return
    
    current_time = time.time()
    
    # Cooldown: 5 seconds between commands
    if current_time - last_command_time < 5:
        return
    
    try:
        command_ref = firebase_db.child('camera').child('command')
        command = command_ref.get()
        
        if command == 'capture':
            print("\n" + "=" * 50)
            print("📷 CAMERA CAPTURE COMMAND RECEIVED!")
            print("=" * 50)
            
            last_command_time = current_time
            
            # Delete command first
            debug_log("Deleting command from Firebase...")
            command_ref.delete()
            time.sleep(0.5)
            
            # Verify deletion
            verify = command_ref.get()
            if verify is not None:
                debug_log("Command still exists, retrying delete...", "WARN")
                command_ref.delete()
                time.sleep(0.3)
            
            # Capture image
            debug_log("Capturing image...")
            image_path = capture_snapshot()
            
            if image_path is None:
                debug_log("Image capture failed", "ERROR")
                return
            
            # Upload to Firebase
            debug_log("Uploading to Firebase...")
            snapshot_id = upload_snapshot(image_path, is_auto_capture=False)
            
            if snapshot_id:
                print("=" * 50)
                print(f"✅ SUCCESS! Snapshot: {snapshot_id}")
                print("=" * 50 + "\n")
            else:
                debug_log("Upload failed", "ERROR")
        
        elif command is not None and command != '':
            debug_log(f"Unknown command: '{command}' - clearing", "WARN")
            command_ref.delete()
                
    except Exception as e:
        debug_log(f"Command check error: {e}", "ERROR")


# ============ MJPEG STREAMING ============
def generate_frames():
    """Generate MJPEG frames for streaming."""
    global stream_active
    
    frame_delay = 1.0 / STREAM_FPS
    
    while stream_active:
        frame = get_frame()
        
        if frame is None:
            # Send placeholder if no camera
            time.sleep(0.1)
            continue
        
        # Add timestamp overlay
        timestamp_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, timestamp_text, (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        # Add "LIVE" indicator
        cv2.putText(frame, "LIVE", (CAMERA_WIDTH - 70, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        
        # Encode frame as JPEG
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        
        if not ret:
            continue
        
        frame_bytes = buffer.tobytes()
        
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        
        time.sleep(frame_delay)


# ============ FLASK ROUTES ============
@app.route('/')
def index():
    """Root endpoint - shows status."""
    local_ip = get_local_ip()
    return f"""
    <html>
    <head><title>Smart Coop Camera</title></head>
    <body style="font-family: Arial; text-align: center; padding: 20px;">
        <h1>🐔 Smart Chicken Coop Camera</h1>
        <h2>Live Stream</h2>
        <img src="/video_feed" style="max-width: 100%; border: 2px solid #333;">
        <p>Stream URL: <code>http://{local_ip}:{STREAM_PORT}/video_feed</code></p>
        <p>Status: <a href="/status">/status</a></p>
    </body>
    </html>
    """


@app.route('/video_feed')
def video_feed():
    """MJPEG video stream endpoint."""
    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@app.route('/status')
def status():
    """Status endpoint."""
    return jsonify({
        'status': 'running',
        'camera_available': camera_is_open,
        'stream_active': stream_active,
        'capture_count': capture_count,
        'timestamp': datetime.now().isoformat()
    })


@app.route('/snapshot')
def take_snapshot_api():
    """API endpoint to take a snapshot."""
    image_path = capture_snapshot()
    if image_path:
        snapshot_id = upload_snapshot(image_path)
        return jsonify({'success': True, 'snapshot_id': snapshot_id})
    return jsonify({'success': False, 'error': 'Capture failed'}), 500


# ============ BACKGROUND THREADS ============
def sensor_loop():
    """Background thread for sensor monitoring and Firebase sync."""
    last_history_save = 0
    
    while True:
        try:
            current_time = time.time()
            
            # Check for camera command from app
            check_camera_command()
            
            # Read sensor
            temperature, humidity = read_sensor()
            
            if temperature is not None and humidity is not None:
                time_str = datetime.now().strftime("%H:%M:%S")
                print(f"[{time_str}] Temp: {temperature}°C | Humidity: {humidity}%")
                
                # Send live data
                if update_live_data(temperature, humidity):
                    print("  ✓ Firebase updated")
                
                # Update system status
                update_system_status(camera_available=camera_is_open, streaming=stream_active)
                
                # Save history periodically
                if current_time - last_history_save >= HISTORY_SAVE_INTERVAL:
                    if save_history_data(temperature, humidity):
                        print("  ✓ History saved")
                    last_history_save = current_time
            
            time.sleep(LIVE_UPDATE_INTERVAL)
            
        except Exception as e:
            debug_log(f"Sensor loop error: {e}", "ERROR")
            time.sleep(5)


def run_flask():
    """Run Flask server."""
    print(f"\n[OK] Starting MJPEG stream server on port {STREAM_PORT}...")
    # Disable Flask's default logging for cleaner output
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    app.run(host=STREAM_HOST, port=STREAM_PORT, threaded=True)


# ============ MAIN ============
def main():
    """Main entry point."""
    global stream_active
    
    print("\n")
    
    # Check required libraries
    if not FLASK_AVAILABLE:
        print("[XX] Flask is required! Install with:")
        print("     pip3 install flask --break-system-packages")
        return
    
    if not CV2_AVAILABLE:
        print("[XX] OpenCV is required! Install with:")
        print("     pip3 install opencv-python --break-system-packages")
        return
    
    # Initialize Firebase
    firebase_ok = init_firebase()
    if not firebase_ok:
        print("[XX] Cannot continue without Firebase!")
        return
    
    # Initialize Camera
    camera_ok = init_camera()
    if not camera_ok:
        print("[!!] Camera not available - streaming disabled")
    
    # Get local IP
    local_ip = get_local_ip()
    
    # Print status
    print("\n" + "=" * 60)
    print("  🐔 SMART COOP SERVER READY")
    print("=" * 60)
    print(f"  📍 Pi IP Address: {local_ip}")
    print(f"  📹 Stream URL: http://{local_ip}:{STREAM_PORT}/video_feed")
    print(f"  🌡️  Sensor: DHT{DHT_SENSOR_TYPE} on GPIO {DHT_PIN}")
    print(f"  🔥 Firebase: Connected")
    print(f"  📷 Camera: {'Ready' if camera_ok else 'Not available'}")
    print("=" * 60)
    print("  Open the stream URL in browser to test!")
    print("  Press Ctrl+C to stop")
    print("=" * 60 + "\n")
    
    try:
        # Start sensor monitoring thread
        sensor_thread = threading.Thread(target=sensor_loop, daemon=True)
        sensor_thread.start()
        print("[OK] Sensor monitoring started")
        
        # Run Flask server (blocks)
        run_flask()
        
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        stream_active = False
        
        # Close camera
        close_camera()
        
        # Update Firebase status
        if firebase_db:
            try:
                firebase_db.child("system").update({
                    "pi_online": False,
                    "streaming_active": False,
                    "last_update": datetime.now().isoformat()
                })
                firebase_db.child("camera").update({
                    "stream_available": False
                })
            except:
                pass
        
        print(f"Total captures this session: {capture_count}")
        print("Goodbye! 🐔")


if __name__ == "__main__":
    main()
