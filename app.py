import json
import threading
import time
import random
import os
from datetime import datetime
from typing import Optional, TypedDict

import paho.mqtt.client as mqtt
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO


# ──────────────────────────────────────────────────────────
# Store Type
# ──────────────────────────────────────────────────────────
class Store(TypedDict):
    latest: Optional[dict]
    history: list
    count: int
    connected: bool
    behaviours: dict[str, int]


# ──────────────────────────────────────────────────────────
# Flask App Setup
# ──────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["SECRET_KEY"] = "gps-group2"

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading"
)


# ──────────────────────────────────────────────────────────
# MQTT Config
# ──────────────────────────────────────────────────────────
MQTT_HOST = "f47cbb24e9c84181992612bf50d5d0fe.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_TOPIC = "V2/Vehicle/Telemetry"
MQTT_USER = "gps_device"
MQTT_PASS = "Gps12345"

TEST_MODE =False


# ──────────────────────────────────────────────────────────
# Data Store
# ──────────────────────────────────────────────────────────
store: Store = {
    "latest": None,
    "history": [],
    "count": 0,
    "connected": False,
    "behaviours": {
        "NORMAL": 0,
        "HARSH_BRAKING": 0,
        "RAPID_ACCEL": 0,
        "SHARP_TURN": 0,
    },
}

BEH_COLOR = {
    "NORMAL": "#50c878",
    "HARSH_BRAKING": "#e25555",
    "RAPID_ACCEL": "#f5a623",
    "SHARP_TURN": "#9b59b6",
}


# ──────────────────────────────────────────────────────────
# Behaviour Detection
# ──────────────────────────────────────────────────────────
def detect_behaviour(ax, ay, az):
    if az < 9.30:
        return "HARSH_BRAKING"
    elif az > 10.30:
        return "RAPID_ACCEL"
    elif abs(ay) > 0.25:
        return "SHARP_TURN"

    return "NORMAL"


# ──────────────────────────────────────────────────────────
# Emit Record
# (NO Kalman here — ESP32 already filtered)
# ──────────────────────────────────────────────────────────
def emit_record(
    raw_lat,
    raw_lon,
    raw_spd,
    alt,
    ax,
    ay,
    az,
    device_id,
    kalman_gain=0,
    uncertainty=0,
    behaviour=None,
):
    f_lat = round(raw_lat, 6)
    f_lon = round(raw_lon, 6)
    f_spd = round(raw_spd, 1)

    beh = behaviour or detect_behaviour(ax, ay, az)

    rec = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "device_id": device_id,

        "lat": f_lat,
        "lon": f_lon,

        "lat_raw": round(raw_lat, 6),
        "lon_raw": round(raw_lon, 6),

        "speed": f_spd,
        "altitude": alt,

        "behaviour": beh,
        "beh_color": BEH_COLOR[beh],

        "accel_x": round(ax, 3),
        "accel_y": round(ay, 3),
        "accel_z": round(az, 3),

        # Kalman values
        "kalman_gain": round(kalman_gain, 3),
        "uncertainty": round(uncertainty, 3),

        "msg_count": store["count"] + 1,
    }

    store["latest"] = rec
    store["count"] += 1
    store["behaviours"][beh] += 1

    store["history"].append(rec)

    if len(store["history"]) > 80:
        store["history"].pop(0)

    socketio.emit(
        "gps_update",
        {
            "data": rec,
            "history": store["history"],
            "behaviours": store["behaviours"],
        },
    )

    print(
        f"[{rec['time']}] "
        f"{f_lat}, {f_lon} | "
        f"{f_spd} km/h | "
        f"K={kalman_gain:.3f} | "
        f"P={uncertainty:.3f} | "
        f"{beh}"
    )


# ──────────────────────────────────────────────────────────
# MQTT Processing
# ──────────────────────────────────────────────────────────
def emit_record(
    raw_lat,
    raw_lon,
    raw_spd,
    alt,
    ax,
    ay,
    az,
    device_id,
    kalman_gain=0,
    uncertainty=0,
    behaviour=None,
):
    f_lat = round(raw_lat, 6)
    f_lon = round(raw_lon, 6)
    f_spd = round(raw_spd, 1)

    beh = behaviour or detect_behaviour(ax, ay, az)

    rec = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "device_id": device_id,

        "lat": f_lat,
        "lon": f_lon,

        "lat_raw": round(raw_lat, 6),
        "lon_raw": round(raw_lon, 6),

        "speed": f_spd,
        "altitude": alt,

        "behaviour": beh,
        "beh_color": BEH_COLOR[beh],

        "accel_x": round(ax, 3),
        "accel_y": round(ay, 3),
        "accel_z": round(az, 3),

        # Kalman values
        "kalman_gain": round(kalman_gain, 3),
        "uncertainty": round(uncertainty, 3),

        "msg_count": store["count"] + 1,
    }

    store["latest"] = rec
    store["count"] += 1
    store["behaviours"][beh] += 1

    store["history"].append(rec)

    if len(store["history"]) > 80:
        store["history"].pop(0)

    socketio.emit(
        "gps_update",
        {
            "data": rec,
            "history": store["history"],
            "behaviours": store["behaviours"],
        },
    )

    print(
        f"[{rec['time']}] "
        f"{f_lat}, {f_lon} | "
        f"{f_spd} km/h | "
        f"K={kalman_gain:.3f} | "
        f"P={uncertainty:.3f} | "
        f"{beh}"
    )

# ──────────────────────────────────────────────────────────
# TEST MODE
# ──────────────────────────────────────────────────────────
def test_mode_loop():
    print("TEST MODE ENABLED")

    lat = 6.3553
    lon = 80.5236

    while True:
        lat += random.uniform(0.00001, 0.00005)
        lon += random.uniform(0.00001, 0.00005)

        emit_record(
            raw_lat=lat,
            raw_lon=lon,
            raw_spd=random.randint(30, 80),
            alt=12,
            ax=0.02,
            ay=random.uniform(-0.4, 0.4),
            az=random.uniform(9.1, 10.6),
            device_id="TEST_DEVICE",
        )

        time.sleep(2)


# ──────────────────────────────────────────────────────────
# MQTT Callbacks
# ──────────────────────────────────────────────────────────
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        store["connected"] = True
        print("MQTT Connected")

        client.subscribe(MQTT_TOPIC)
        print("Subscribed:", MQTT_TOPIC)
    else:
        print("MQTT Failed:", rc)

def process_message(payload):
    try:
        data = json.loads(payload)
        gps  = data.get("gps", {})
        imu  = data.get("imu", {})
        emit_record(
            raw_lat   = float(gps.get("lat_raw", gps.get("lat", 6.3553))),
            raw_lon   = float(gps.get("lon_raw", gps.get("lon", 80.5236))),
            raw_spd   = float(gps.get("speed", 0)),
            alt       = float(gps.get("altitude", 12.0)),
            ax        = float(imu.get("accel_x", 0.01)),
            ay        = float(imu.get("accel_y", -0.01)),
            az        = float(imu.get("accel_z", 9.81)),
            device_id = data.get("device_id", "GROUP2_VEHICLE_01"),
            behaviour = data.get("behaviour"),
        )
    except Exception as e:
        print(f"Message error: {e}")

def on_message(client, userdata, msg):
    process_message(msg.payload.decode("utf-8"))

def on_message(client, userdata, msg):
    process_message(msg.payload.decode())


def on_disconnect(client, userdata, rc):
    store["connected"] = False
    print("MQTT Disconnected")


# ──────────────────────────────────────────────────────────
# Start MQTT
# ──────────────────────────────────────────────────────────
def start_mqtt():
    try:
        client = mqtt.Client()

        client.username_pw_set(
            MQTT_USER,
            MQTT_PASS
        )

        client.tls_set()

        client.on_connect = on_connect
        client.on_message = on_message
        client.on_disconnect = on_disconnect

        client.connect(
            MQTT_HOST,
            MQTT_PORT,
            60
        )

        client.loop_forever()

    except Exception as e:
        print("MQTT Error:", e)


# ──────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────
@app.route("/")
def home():
    return render_template("dashboard.html")


@app.route("/api/latest")
def latest():
    return jsonify(store["latest"] or {})


@app.route("/api/history")
def history():
    return jsonify(store["history"])


@app.route("/api/stats")
def stats():
    return jsonify({
        "count": store["count"],
        "connected": store["connected"],
        "test_mode": TEST_MODE,
        "behaviours": store["behaviours"],
    })


@socketio.on("connect")
def socket_connected():
    print("Dashboard Connected")


# ──────────────────────────────────────────────────────────
# Background Thread
# ──────────────────────────────────────────────────────────
def start_background():
    if TEST_MODE:
        thread = threading.Thread(
            target=test_mode_loop,
            daemon=True
        )
    else:
        thread = threading.Thread(
            target=start_mqtt,
            daemon=True
        )

    thread.start()


start_background()


# ──────────────────────────────────────────────────────────
# Run App (Railway Compatible)
# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))

    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=False
    )

