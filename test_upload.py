#!/usr/bin/env python3
"""Direct test of camera capture and Firebase upload"""

import cv2
import base64
import os
import time
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, db

print("=" * 50)
print("  DIRECT CAMERA + UPLOAD TEST")
print("=" * 50)

# Step 1: Connect to Firebase
print("\n[1] Connecting to Firebase...")
try:
    cred = credentials.Certificate('firebase_credentials.json')
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://smart-coop-6cdfa-default-rtdb.asia-southeast1.firebasedatabase.app/'
    })
    firebase_db = db.reference('smart_coop')
    print("    OK!")
except Exception as e:
    print(f"    FAILED: {e}")
    exit(1)

# Step 2: Open camera
print("\n[2] Opening camera...")
try:
    camera = cv2.VideoCapture(0, cv2.CAP_V4L2)
    if not camera.isOpened():
        print("    FAILED: Camera won't open")
        exit(1)
    print("    OK!")
except Exception as e:
    print(f"    FAILED: {e}")
    exit(1)

# Step 3: Warm up
print("\n[3] Warming up camera...")
for i in range(10):
    camera.read()
    time.sleep(0.1)
print("    OK!")

# Step 4: Capture
print("\n[4] Capturing image...")
try:
    ret, frame = camera.read()
    camera.release()
   
    if not ret or frame is None:
        print("    FAILED: Could not read frame")
        exit(1)
   
    os.makedirs('captures', exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"captures/test_{timestamp}.jpg"
    cv2.imwrite(filepath, frame)
   
    size = os.path.getsize(filepath)
    print(f"    OK! Saved: {filepath} ({size/1024:.1f} KB)")
except Exception as e:
    print(f"    FAILED: {e}")
    exit(1)

# Step 5: Convert to base64
print("\n[5] Converting to base64...")
try:
    with open(filepath, 'rb') as f:
        image_data = f.read()
   
    base64_image = base64.b64encode(image_data).decode('utf-8')
    print(f"    OK! Base64 size: {len(base64_image)/1024:.1f} KB")
except Exception as e:
    print(f"    FAILED: {e}")
    exit(1)

# Step 6: Upload to Firebase
print("\n[6] Uploading to Firebase...")
try:
    snapshot_id = f"snap_{timestamp}"
   
    snapshot_data = {
        'id': snapshot_id,
        'image_base64': base64_image,
        'image_url': '',
        'timestamp': datetime.now().isoformat(),
        'is_auto_capture': False,
    }
   
    firebase_db.child('camera_snapshots').child(snapshot_id).set(snapshot_data)
    print(f"    OK! Uploaded: {snapshot_id}")
except Exception as e:
    print(f"    FAILED: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

# Step 7: Update camera node
print("\n[7] Updating camera reference...")
try:
    firebase_db.child('camera').update({
        'latest_snapshot_id': snapshot_id,
        'latest_timestamp': datetime.now().isoformat(),
    })
    print("    OK!")
except Exception as e:
    print(f"    FAILED: {e}")

print("\n" + "=" * 50)
print("  SUCCESS! Check Firebase Console:")
print("  smart_coop -> camera_snapshots")
print("=" * 50)