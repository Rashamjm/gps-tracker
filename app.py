import json, math, threading, time, random
from datetime import datetime
from typing import Optional, TypedDict
import paho.mqtt.client as mqtt
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO


class Store(TypedDict):
    latest: Optional[dict]
    history: list
    count: int
    connected: bool
    behaviours: dict[str, int]


# ── App setup ─────────────────────────────────────────────
app = Flask(__name__)
@app.route("/")
def home():
    return "Hello"
app.config["SECRET_KEY"] = "gps-group2"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ── HiveMQ credentials ── CHANGE YOUR_HOST BELOW ──────────
MQTT_HOST = "f47cbb24e9c84181992612bf50d5d0fe.s1.eu.hivemq.cloud"  # ← change this
MQTT_PORT = 8883
MQTT_TOPIC = "V2/Vehicle/Telemetry"
MQTT_USER = "gps_device"
MQTT_PASS = "Gps12345"

# ── SET THIS TO True TO TEST WITHOUT WOKWI ────────────────
TEST_MODE = True  # ← change to True to simulate without Wokwi


# ── Kalman Filter ──────────────────────────────────────────
class KalmanFilter:
    def __init__(self, Q=0.01, R=0.5, X=0.0, P=1.0):
        self.Q = Q
        self.R = R
        self.X = X
        self.P = P
        self.K = 0

    def update(self, Z):
        self.P = self.P + self.Q
        self.K = self.P / (self.P + self.R)
        self.X = self.X + self.K * (Z - self.X)
        self.P = (1 - self.K) * self.P
        return self.X


kf_lat = KalmanFilter(Q=0.01, R=0.5)
kf_lon = KalmanFilter(Q=0.01, R=0.5)
kf_speed = KalmanFilter(Q=0.1, R=2.0)
inited = False

# ── Data store ─────────────────────────────────────────────
store: Store = {
    "latest": None,
    "history": [],
    "count": 0,
    "connected": False,
    "behaviours": {"NORMAL": 0, "HARSH_BRAKING": 0, "RAPID_ACCEL": 0, "SHARP_TURN": 0},
}

BEH_COLOR = {
    "NORMAL": "#50c878",
    "HARSH_BRAKING": "#e25555",
    "RAPID_ACCEL": "#f5a623",
    "SHARP_TURN": "#9b59b6",
}


def detect_behaviour(ax, ay, az):
    if az < 9.30:
        return "HARSH_BRAKING"
    elif az > 10.30:
        return "RAPID_ACCEL"
    elif abs(ay) > 0.25:
        return "SHARP_TURN"
    else:
        return "NORMAL"


# ── Build and emit one data record ────────────────────────
def emit_record(raw_lat, raw_lon, raw_spd, alt, ax, ay, az, device_id, behaviour=None):
    global inited, kf_lat, kf_lon, kf_speed

    if not inited:
        kf_lat.X = raw_lat
        kf_lon.X = raw_lon
        kf_speed.X = raw_spd
        inited = True

    f_lat = round(kf_lat.update(raw_lat), 6)
    f_lon = round(kf_lon.update(raw_lon), 6)
    f_spd = round(kf_speed.update(raw_spd), 1)
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
        "beh_color": BEH_COLOR.get(beh, "#50c878"),
        "accel_x": round(ax, 3),
        "accel_y": round(ay, 3),
        "accel_z": round(az, 3),
        "kalman_gain": round(kf_lat.K, 4),
        "uncertainty": round(kf_lat.P, 6),
        "msg_count": store["count"] + 1,
    }

    store["latest"] = rec
    store["count"] += 1
    store["behaviours"][beh] = store["behaviours"].get(beh, 0) + 1
    store["history"].append(
        {
            "lat": rec["lat"],
            "lon": rec["lon"],
            "lat_raw": rec["lat_raw"],
            "lon_raw": rec["lon_raw"],
            "speed": rec["speed"],
            "behaviour": beh,
            "beh_color": rec["beh_color"],
            "time": rec["time"],
        }
    )
    if len(store["history"]) > 80:
        store["history"].pop(0)

    socketio.emit(
        "gps_update",
        {"data": rec, "history": store["history"], "behaviours": store["behaviours"]},
    )
    print(
        f"[{rec['time']}] #{rec['msg_count']} | "
        f"{f_lat:.5f},{f_lon:.5f} | "
        f"{f_spd}km/h | {beh}"
    )


# ── Process real MQTT message ──────────────────────────────
def process_message(payload):
    try:
        data = json.loads(payload)
        gps = data.get("gps", {})
        imu = data.get("imu", {})
        emit_record(
            raw_lat=float(gps.get("lat_raw", gps.get("lat", 6.3553))),
            raw_lon=float(gps.get("lon_raw", gps.get("lon", 80.5236))),
            raw_spd=float(gps.get("speed", 0)),
            alt=float(gps.get("altitude", 12.0)),
            ax=float(imu.get("accel_x", 0.01)),
            ay=float(imu.get("accel_y", -0.01)),
            az=float(imu.get("accel_z", 9.81)),
            device_id=data.get("device_id", "GROUP2_VEHICLE_01"),
            behaviour=data.get("behaviour"),
        )
    except Exception as e:
        print(f"Message error: {e}")


# ── TEST MODE — fake GPS data (no Wokwi needed) ────────────
def test_mode_loop():
    print("=" * 45)
    print("  TEST MODE ON — fake GPS data running")
    print("  Set TEST_MODE=False when Wokwi is ready")
    print("=" * 45)
    lat, lon = 6.3553, 80.5236
    behs = ["NORMAL", "NORMAL", "NORMAL", "HARSH_BRAKING", "RAPID_ACCEL", "SHARP_TURN"]
    i = 0
    while True:
        lat += 0.00008 + random.uniform(-0.00002, 0.00002)
        lon += 0.00005 + random.uniform(-0.00002, 0.00002)
        spd = 40 + random.uniform(-15, 25)
        az_map = {
            "NORMAL": 9.81,
            "HARSH_BRAKING": 9.1,
            "RAPID_ACCEL": 10.5,
            "SHARP_TURN": 9.81,
        }
        ay_map = {
            "NORMAL": 0.0,
            "HARSH_BRAKING": 0.0,
            "RAPID_ACCEL": 0.0,
            "SHARP_TURN": 0.35,
        }
        beh = behs[i % len(behs)]
        emit_record(
            raw_lat=lat + random.uniform(-0.00004, 0.00004),
            raw_lon=lon + random.uniform(-0.00004, 0.00004),
            raw_spd=spd,
            alt=12.0,
            ax=random.uniform(-0.05, 0.05),
            ay=ay_map[beh] + random.uniform(-0.05, 0.05),
            az=az_map[beh] + random.uniform(-0.1, 0.1),
            device_id="GROUP2_TEST_MODE",
            behaviour=beh,
        )
        i += 1
        time.sleep(2)


# ── MQTT callbacks ─────────────────────────────────────────
def on_connect(client, userdata, flags, rc):
    rc_msg = {
        0: "OK",
        1: "Bad protocol",
        2: "Client ID rejected",
        3: "Server unavailable",
        4: "Bad credentials",
        5: "Not authorised",
    }
    if rc == 0:
        store["connected"] = True
        print("✓ MQTT connected to HiveMQ!")
        client.subscribe(MQTT_TOPIC)
        print(f"✓ Subscribed: {MQTT_TOPIC}")
    else:
        print(f"✗ MQTT failed — code {rc}: {rc_msg.get(rc, 'Unknown')}")
        print("  Check: hostname, username, password")


def on_message(client, userdata, msg):
    process_message(msg.payload.decode("utf-8"))


def on_disconnect(client, userdata, rc):
    store["connected"] = False
    print(f"MQTT disconnected (rc={rc}) — will retry")


# ── MQTT thread ────────────────────────────────────────────
def start_mqtt():
    try:
        # Works with paho-mqtt 1.x and 2.x
        try:
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION1,
                client_id="replit_gps_" + str(random.randint(1000, 9999)),
            )
        except AttributeError:
            client = mqtt.Client(
                client_id="replit_gps_" + str(random.randint(1000, 9999))
            )

        client.username_pw_set(MQTT_USER, MQTT_PASS)
        client.tls_set()
        client.on_connect = on_connect
        client.on_message = on_message
        client.on_disconnect = on_disconnect

        print(f"Connecting MQTT → {MQTT_HOST}:{MQTT_PORT}")
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        client.loop_forever()
    except Exception as e:
        print(f"✗ MQTT error: {e}")


# ── Flask routes ───────────────────────────────────────────
@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/latest")
def api_latest():
    return jsonify(store.get("latest") or {})


@app.route("/api/history")
def api_history():
    return jsonify(store["history"])


@app.route("/api/stats")
def api_stats():
    return jsonify(
        {
            "count": store["count"],
            "behaviours": store["behaviours"],
            "connected": store["connected"],
            "test_mode": TEST_MODE,
        }
    )


@socketio.on("connect")
def on_ws_connect():
    print("Dashboard browser connected")
    if store["latest"]:
        socketio.emit(
            "gps_update",
            {
                "data": store["latest"],
                "history": store["history"],
                "behaviours": store["behaviours"],
            },
        )


# ── Start everything ───────────────────────────────────────
def start_background():
    if TEST_MODE:
        t = threading.Thread(target=test_mode_loop, daemon=True)
    else:
        t = threading.Thread(target=start_mqtt, daemon=True)
    t.start()

start_background()

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8080))

    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )
