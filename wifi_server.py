import time
import json
import socket
import atexit
import threading
import cv2
import os

from flask import Flask, Response, jsonify
from picamera2 import Picamera2
from picarx import Picarx

app = Flask(__name__)

HOST = "0.0.0.0"
SOCKET_PORT = 65432
CAMERA_PORT = 8081

DEFAULT_SPEED = 50
LEFT_ANGLE = -20
RIGHT_ANGLE = 20
CENTER_ANGLE = 0

px = Picarx()
px.set_cliff_reference([200, 200, 200])

client_connected = False
client_conn = None


picarx_state = {
    "moving": "stop",
    "steer": "center",
    "obstacle_dist_cm": 0.0,
    "cliff_detected": False,
    "cpu_temp": 0.0
}


_picam2 = None
_camera_started = False
_camera_lock = threading.Lock()


def norm_stop():
    try:
        px.stop()
        px.set_dir_servo_angle(CENTER_ANGLE)
    except Exception:
        pass
        
# Crash/Exit Issue Resolution with atexit!
@atexit.register
def cleanup():
    norm_stop()
    

def move_forward():
    px.set_dir_servo_angle(CENTER_ANGLE)
    px.forward(DEFAULT_SPEED)
    picarx_state["moving"] = "forward"
    picarx_state["steer"] = "center"
    
    
def move_backward():
    px.set_dir_servo_angle(CENTER_ANGLE)
    px.backward(DEFAULT_SPEED)
    picarx_state["moving"] = "backward"
    picarx_state["steer"] = "center"
    
    
def stop_car():
    px.stop()
    px.set_dir_servo_angle(CENTER_ANGLE)
    picarx_state["moving"] =  "stop"
    picarx_state["steer"] = "center"
    

def steer_left():
    px.set_dir_servo_angle(LEFT_ANGLE)
    px.forward(DEFAULT_SPEED)
    picarx_state["moving"] = "forward"
    picarx_state["steer"] = "left"
    
def steer_right():
    px.set_dir_servo_angle(RIGHT_ANGLE)
    px.forward(DEFAULT_SPEED)
    picarx_state["moving"] = "forward"
    picarx_state["steer"] = "right"
    
    
# Telemetry / Sensors
def find_obst_dist():
    try:
        distance = px.ultrasonic.read()
        if distance is None or distance <= 0:
            return picarx_state["obstacle_dist_cm"]
        return round(float(distance), 1)
    except Exception:
        return 0.0
        
        
def cliff_detection():
    try:
        vals = px.get_grayscale_data()
        if not vals or len(vals) < 3:
            return False
            
        return bool(px.get_cliff_status(vals))
    except Exception:
        return False
        
              
def get_temp():
    try:
        temp = os.popen("vcgencmd measure_temp").readline()
        return float(temp.replace("temp=", "").replace("'C\n", ""))
    except Exception:
        return 0.0
        
        
def update_telemetry():
    picarx_state["obstacle_dist_cm"] = find_obst_dist()
    picarx_state["cliff_detected"] = cliff_detection()
    picarx_state["cpu_temp"] = get_temp()
    
    if picarx_state["cliff_detected"]:
        print("Cliff detected! Stopping car.", flush=True)
        stop_car()
         
        
def run_command(cmd):
    cmd = cmd.strip().lower()
    print(f"Received: {cmd}", flush=True)
    
    if picarx_state["cliff_detected"] and cmd in {"forward", "left", "right"}:
        stop_car()
        return
            
    if cmd == "forward":
        move_forward()
    elif cmd == "backward":
        move_backward()
    elif cmd == "stop":
        stop_car()
    elif cmd == "left":
        steer_left()
    elif cmd == "right":
        steer_right()
    else:
        print(f"Unknown command: {cmd}", flush=True)
        
    
def telemetry_loop(conn):
    global client_connected
    
    while client_connected:
        try:
            update_telemetry()
            payload = json.dumps(picarx_state) + "\n"
            conn.sendall(payload.encode("utf-8"))
            time.sleep(0.1)
        except Exception as e:
            print("Telemetry loop ended:", e)
            break
            
            
    client_connected = False

def start_socket_server():
    global client_connected, client_conn
    
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, SOCKET_PORT))
    server.listen(1)
    
    print(f"Socket server listening on {HOST}:{SOCKET_PORT}", flush=True)
    
    while True:
        conn, addr = server.accept()
        print(f"Client connected from {addr}", flush=True)
        
        client_conn = conn
        client_connected = True
        
        # Using threading logic
        telemetry_thread = threading.Thread(
            target=telemetry_loop, 
            args=(conn,), 
            daemon=True
        )
            
        telemetry_thread.start()
        
        buffer = ""
        
        try:
            while True:
                data = conn.recv(1024)
                if not data:
                    break
                    
                buffer += data.decode("utf-8")
                
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if not line.strip():
                        continue
                        
                    run_command(line)
                    conn.sendall((f"ACK:{line.strip()}\n").encode("utf-8"))
                    
                    
        except Exception as e:
            print("Connection error:", e)
            
        finally:
            print("Client disconnected", flush=True)
            client_connected = False
            norm_stop()
            conn.close()
            

# PiCamera
def start_camera_internal(width=640, height=480):
    global _picam2, _camera_started

    with _camera_lock:
        if _camera_started and _picam2 is not None:
            return True, "Camera already running"

        try:
            picam2 = Picamera2()

            config = picam2.create_video_configuration(
                main={"size": (width, height), "format": "RGB888"}
            )

            picam2.configure(config)
            picam2.start()

            picam2.set_controls({
                "AeEnable": True,
                "AwbEnable": True,
                "Sharpness": 2.0,
            })

            time.sleep(1)

            _picam2 = picam2
            _camera_started = True

            print("Camera started", flush=True)
            return True, "Camera started"

        except Exception as e:
            print("Camera error:", e, flush=True)
            _picam2 = None
            _camera_started = False
            return False, str(e)


def generate_frames():
    global _picam2, _camera_started

    while True:
        if not _camera_started or _picam2 is None:
            time.sleep(0.1)
            continue

        try:
            frame = _picam2.capture_array()
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            ret, buffer = cv2.imencode(".jpg", frame_bgr)
            if not ret:
                continue

            frame_bytes = buffer.tobytes()

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" +
                frame_bytes +
                b"\r\n"
            )

        except Exception as e:
            print("Frame error:", e, flush=True)
            time.sleep(0.1)


@app.route("/stream")
def stream():
    success, msg = start_camera_internal()
    if not success:
        return jsonify({"success": False, "message": msg}), 500

    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/camera_status")
def camera_status():
    return jsonify({
        "camera_running": _camera_started
    })


def start_camera_server():
    print(f"Camera server running on {HOST}:{CAMERA_PORT}", flush=True)
    app.run(host=HOST, port=CAMERA_PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    camera_thread = threading.Thread(target=start_camera_server, daemon=True)
    camera_thread.start()

    start_socket_server()
