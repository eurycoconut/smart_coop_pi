#!/usr/bin/env python3
"""
Smart Coop - Send Camera Capture Command
Sends a one-time capture command to Firebase
"""

import os
import sys
import time

# Configuration - MUST match your main script
FIREBASE_CREDENTIALS_PATH = "firebase_credentials.json"
FIREBASE_DATABASE_URL = "https://smart-coop-6cdfa-default-rtdb.asia-southeast1.firebasedatabase.app/"
FIREBASE_BASE_PATH = "smart_coop"

print("=" * 40)
print("  Send Camera Capture Command")
print("=" * 40)

# Check credentials file exists
if not os.path.exists(FIREBASE_CREDENTIALS_PATH):
    print(f"[XX] Error: {FIREBASE_CREDENTIALS_PATH} not found!")
    print("     Make sure you're in the right directory: ~/smart_coop")
    sys.exit(1)

try:
    import firebase_admin
    from firebase_admin import credentials, db
except ImportError:
    print("[XX] Error: firebase_admin not installed!")
    print("     Run: pip3 install firebase-admin")
    sys.exit(1)

# Initialize Firebase (only if not already initialized)
try:
    if not firebase_admin._apps:
        print("Connecting to Firebase...")
        cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
        firebase_admin.initialize_app(cred, {
            'databaseURL': FIREBASE_DATABASE_URL
        })
        print("[OK] Firebase connected")
    else:
        print("[OK] Firebase already initialized")
except Exception as e:
    print(f"[XX] Firebase connection failed: {e}")
    sys.exit(1)

# Get reference to command node
command_ref = db.reference(f'{FIREBASE_BASE_PATH}/camera/command')

# Step 1: Check current command status
print("\nChecking current command status...")
current_command = command_ref.get()

if current_command is not None:
    print(f"[!!] Warning: Existing command found: '{current_command}'")
    print("     This might mean the Pi hasn't processed the last command yet.")
    print("     Clearing it first...")
    command_ref.delete()
    time.sleep(0.5)

# Step 2: Send the capture command
print("\nSending 'capture' command...")
try:
    command_ref.set('capture')
    print("[OK] Command sent!")
except Exception as e:
    print(f"[XX] Failed to send command: {e}")
    sys.exit(1)

# Step 3: Verify command was written
time.sleep(0.3)
verify = command_ref.get()
if verify == 'capture':
    print("[OK] Command verified in Firebase")
else:
    print(f"[!!] Warning: Command verification got: {verify}")

print("\n" + "=" * 40)
print("Done! Check the main script terminal for:")
print("  📷 CAMERA CAPTURE COMMAND RECEIVED!")
print("=" * 40)

# Optional: Wait and check if command was processed
print("\nWaiting 5 seconds to see if Pi processes it...")
time.sleep(5)

final_check = command_ref.get()
if final_check is None:
    print("[OK] Command was processed (deleted by Pi)")
elif final_check == 'capture':
    print("[!!] Command still exists - Pi might not be running or didn't process it")
    print("     Check if dht_firebase_with_camera.py is running")
else:
    print(f"[??] Unexpected value: {final_check}")
