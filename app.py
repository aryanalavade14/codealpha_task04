"""
AI VISION X - Intelligent Vision Analytics
==========================================
Flask backend for real-time object detection and tracking.

Pipeline (all inside one background thread, so the web server never blocks):

    webcam / video file  ->  OpenCV frame
                         ->  Ultralytics YOLO11n + ByteTrack  (model.track)
                         ->  custom neon overlay (boxes, labels, track IDs, trails)
                         ->  JPEG  ->  MJPEG stream  (/video_feed)

Statistics, detection events and tracks are updated from the same thread and
exposed as JSON through the /api/* endpoints. The dashboard (templates/index.html
+ static/js/script.js) simply polls those endpoints.

Run:   python app.py        then open  http://127.0.0.1:5000
Your original standalone program (main.py) is untouched and still works.
"""

import os
import threading
import time
import webbrowser
import atexit
from collections import Counter, deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import psutil
from flask import Flask, Response, jsonify, render_template, request
from werkzeug.utils import secure_filename

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "yolo11n.pt"          # your existing weights - not retrained
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}
STREAM_WIDTH = 960            # frames are downscaled to this width (keeps CPU use sane)
JPEG_QUALITY = 80
ACTIVE_TRACK_WINDOW = 1.5     # seconds - a track counts as "active" if seen this recently
TRACK_FORGET_AFTER = 120      # seconds - drop stale tracks from memory
MAX_EVENTS = 300
TIMELINE_POINTS = 60          # one point per second

DEFAULTS = {"confidence": 0.35, "imgsz": 640}

# BGR colours used on the video overlay (matched to the dashboard's neon palette)
CATEGORY_COLORS = {
    "person":  (238, 211, 34),    # cyan   #22d3ee
    "vehicle": (36, 191, 251),    # amber  #fbbf24
    "animal":  (153, 211, 52),    # green  #34d399
    "object":  (250, 139, 167),   # violet #a78bfa
}
VEHICLES = {"bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat"}
ANIMALS = {"bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"}


def category_of(name: str) -> str:
    if name == "person":
        return "person"
    if name in VEHICLES:
        return "vehicle"
    if name in ANIMALS:
        return "animal"
    return "object"


# --------------------------------------------------------------------------
# Vision engine - owns the camera, the model and every live statistic
# --------------------------------------------------------------------------
class VisionEngine:
    def __init__(self):
        self.lock = threading.RLock()
        self.frame_cond = threading.Condition()

        # model
        self.model = None
        self.model_status = "loading"        # loading | ready | error
        self.model_error = ""

        # worker thread
        self.thread = None
        self.stop_event = threading.Event()
        self.capture = None

        # public state
        self.status = "standby"              # standby | live | completed | error
        self.message = ""
        self.source = {"type": "webcam", "label": "Webcam 0"}
        self.settings = dict(DEFAULTS)

        # latest frame
        self.jpeg = None
        self.frame_id = 0
        self.placeholder = self._make_placeholder()

        self._reset_session()

    # ---------------------------------------------------------------- model
    def load_model_async(self):
        threading.Thread(target=self._load_model, daemon=True).start()

    def _load_model(self):
        try:
            print("[AI VISION X] Loading YOLO model (first start can take a few seconds)...")
            from ultralytics import YOLO       # imported here so the web server starts instantly

            model = YOLO(str(MODEL_PATH))
            # warm-up so the first live frame is not slow
            model.predict(np.zeros((320, 320, 3), dtype=np.uint8), verbose=False, imgsz=320)
            with self.lock:
                self.model = model
                self.model_status = "ready"
            print("[AI VISION X] Model ready.")
        except Exception as exc:               # noqa: BLE001 - report anything to the UI
            with self.lock:
                self.model_status = "error"
                self.model_error = f"{type(exc).__name__}: {exc}"
            print(f"[AI VISION X] MODEL ERROR: {self.model_error}")

    # -------------------------------------------------------------- session
    def _reset_session(self):
        with self.lock:
            self.session_start = None
            self.frame_count = 0
            self.fps = 0.0
            self.latency_ms = 0.0
            self.raw_detections = 0          # every box on every frame
            self.unique_objects = 0          # number of distinct track IDs
            self.class_distribution = Counter()   # unique objects per class
            self.frame_counts = {}
            self.current = []
            self.events = deque(maxlen=MAX_EVENTS)
            self.event_seq = 0
            self.tracks = {}                 # id -> info
            self.trails = {}                 # id -> deque of centre points
            self.timeline = deque(maxlen=TIMELINE_POINTS)
            self._last_timeline_tick = 0.0

    # ---------------------------------------------------------------- start
    def start(self, source_type, camera_index=0, video_name=None):
        """Open the source and start the worker thread. Returns (ok, message)."""
        with self.lock:
            if self.model_status == "loading":
                return False, "The AI model is still loading. Please wait a few seconds and try again."
            if self.model_status == "error":
                return False, f"The AI model failed to load: {self.model_error}"

        self.stop()                          # restart cleanly if already running

        if source_type == "video":
            if not video_name:
                return False, "Please upload or choose a video file first."
            path = UPLOAD_DIR / secure_filename(video_name)
            if not path.is_file():
                return False, "That video file was not found. Upload it again."
            capture = cv2.VideoCapture(str(path))
            label = f"Video: {path.name}"
            is_file = True
        else:
            capture = self._open_webcam(int(camera_index))
            label = f"Webcam {int(camera_index)}"
            is_file = False

        if capture is None or not capture.isOpened():
            if capture is not None:
                capture.release()
            if is_file:
                return False, "OpenCV could not open that video file (unsupported codec?)."
            return False, ("Could not open the webcam. Close other apps that use the camera "
                           "(Zoom, Teams, Camera app), check Windows camera privacy settings, "
                           "or try another camera index in Cameras.")

        self._reset_session()
        with self.lock:
            self.capture = capture
            self.source = {"type": source_type, "label": label}
            self.status = "live"
            self.message = ""
            self.session_start = time.time()
            self.stop_event = threading.Event()
            self.thread = threading.Thread(
                target=self._run, args=(capture, is_file, self.stop_event), daemon=True
            )
            self.thread.start()
        return True, "Monitoring started."

    @staticmethod
    def _open_webcam(index):
        cap = None
        if os.name == "nt":                  # DirectShow opens webcams much faster on Windows
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap.release()
                cap = None
        if cap is None:
            cap = cv2.VideoCapture(index)
        if cap is not None and cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    # ----------------------------------------------------------------- stop
    def stop(self):
        with self.lock:
            thread, stop_event = self.thread, self.stop_event
        if thread is not None and thread.is_alive():
            stop_event.set()
            thread.join(timeout=5)
        with self.lock:
            if self.capture is not None:
                self.capture.release()
                self.capture = None
            self.thread = None
            self.status = "standby"
            self.message = ""
            self.jpeg = None
        self._publish(None)

    # ------------------------------------------------------------ main loop
    def _run(self, capture, is_file, stop_event):
        model = self.model
        first_frame = True
        read_failures = 0
        source_fps = capture.get(cv2.CAP_PROP_FPS) if is_file else 0
        frame_interval = 1.0 / source_fps if source_fps and source_fps > 1 else 0
        fps_ema = 0.0

        try:
            while not stop_event.is_set():
                loop_start = time.perf_counter()
                ok, frame = capture.read()

                if not ok:
                    if is_file:
                        with self.lock:
                            self.status = "completed"
                            self.message = "Video finished."
                        break
                    read_failures += 1
                    if read_failures > 40:
                        with self.lock:
                            self.status = "error"
                            self.message = "Camera stopped delivering frames."
                        break
                    time.sleep(0.05)
                    continue
                read_failures = 0

                h, w = frame.shape[:2]
                if w > STREAM_WIDTH:
                    frame = cv2.resize(frame, (STREAM_WIDTH, int(h * STREAM_WIDTH / w)),
                                       interpolation=cv2.INTER_AREA)

                with self.lock:
                    conf = self.settings["confidence"]
                    imgsz = self.settings["imgsz"]

                # --- detection + ByteTrack tracking (your existing pipeline) ---
                t0 = time.perf_counter()
                if first_frame:
                    # persist=False on the first frame gives a fresh tracker (IDs restart at 1)
                    try:
                        model.predictor = None
                    except Exception:      # noqa: BLE001
                        pass
                result = model.track(
                    frame, persist=not first_frame, tracker="bytetrack.yaml",
                    conf=conf, imgsz=imgsz, verbose=False,
                )[0]
                first_frame = False
                latency = (time.perf_counter() - t0) * 1000

                detections = self._parse(result, model.names)
                self._update_stats(detections, time.time())
                annotated = self._draw(frame, detections)

                ok_enc, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                if ok_enc:
                    self._publish(buf.tobytes())

                elapsed = time.perf_counter() - loop_start
                inst_fps = 1.0 / elapsed if elapsed > 0 else 0.0
                fps_ema = inst_fps if fps_ema == 0 else 0.85 * fps_ema + 0.15 * inst_fps
                with self.lock:
                    self.fps = fps_ema
                    self.latency_ms = latency
                    self.frame_count += 1

                # play video files back at their natural speed
                if frame_interval:
                    spare = frame_interval - (time.perf_counter() - loop_start)
                    if spare > 0:
                        time.sleep(spare)

        except Exception as exc:               # noqa: BLE001
            with self.lock:
                self.status = "error"
                self.message = f"{type(exc).__name__}: {exc}"
            print(f"[AI VISION X] Processing error: {self.message}")
        finally:
            capture.release()
            with self.lock:
                if self.status == "live":
                    self.status = "standby"
                if self.capture is capture:
                    self.capture = None
                # nothing is live any more: zero the "right now" values (session totals are kept)
                self.current = []
                self.frame_counts = {}
                self.fps = 0.0
                self.latency_ms = 0.0
                self.jpeg = None
            self._publish(None)

    # ---------------------------------------------------------- parse / draw
    @staticmethod
    def _parse(result, names):
        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return []
        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        classes = boxes.cls.cpu().numpy().astype(int)
        ids = boxes.id.cpu().numpy().astype(int) if boxes.id is not None else [None] * len(xyxy)
        out = []
        for box, c, k, tid in zip(xyxy, confs, classes, ids):
            name = names[int(k)]
            out.append({
                "box": [int(v) for v in box],
                "conf": float(c),
                "name": name,
                "category": category_of(name),
                "id": int(tid) if tid is not None else None,
            })
        return out

    def _update_stats(self, detections, now):
        stamp = datetime.fromtimestamp(now).strftime("%H:%M:%S")
        with self.lock:
            self.raw_detections += len(detections)
            self.frame_counts = dict(Counter(d["name"] for d in detections))
            self.current = [
                {"class": d["name"], "confidence": round(d["conf"], 3),
                 "id": d["id"], "category": d["category"]}
                for d in sorted(detections, key=lambda d: -d["conf"])
            ]

            for d in detections:
                tid = d["id"]
                if tid is None:
                    continue
                x1, y1, x2, y2 = d["box"]
                self.trails.setdefault(tid, deque(maxlen=28)).append(((x1 + x2) // 2, y2))
                info = self.tracks.get(tid)
                if info is None:
                    # first time we see this ID -> a new object entered the scene
                    self.tracks[tid] = {
                        "id": tid, "class": d["name"], "category": d["category"],
                        "confidence": d["conf"], "first_seen": now, "last_seen": now, "frames": 1,
                    }
                    self.unique_objects += 1
                    self.class_distribution[d["name"]] += 1
                    self.event_seq += 1
                    self.events.append({
                        "event_id": self.event_seq, "time": stamp, "class": d["name"],
                        "category": d["category"], "confidence": round(d["conf"], 3), "track_id": tid,
                        "source": self.source["label"],
                    })
                else:
                    info.update(confidence=d["conf"], last_seen=now)
                    info["frames"] += 1

            # forget tracks that disappeared long ago (bounded memory)
            stale = [t for t, i in self.tracks.items() if now - i["last_seen"] > TRACK_FORGET_AFTER]
            for t in stale:
                self.tracks.pop(t, None)
                self.trails.pop(t, None)

            if now - self._last_timeline_tick >= 1.0:
                self._last_timeline_tick = now
                self.timeline.append({"t": stamp, "objects": len(detections)})

    def _draw(self, frame, detections):
        out = frame.copy()
        with self.lock:
            trails = {k: list(v) for k, v in self.trails.items()}
        for d in detections:
            color = CATEGORY_COLORS[d["category"]]
            x1, y1, x2, y2 = d["box"]

            # movement trail (bottom-centre of the box over the last frames)
            pts = trails.get(d["id"], [])
            for a, b in zip(pts, pts[1:]):
                cv2.line(out, a, b, color, 2, cv2.LINE_AA)

            cv2.rectangle(out, (x1, y1), (x2, y2), color, 1, cv2.LINE_AA)
            L = max(10, min(26, (x2 - x1) // 4, (y2 - y1) // 4))     # corner brackets
            for (px, py, dx, dy) in ((x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1)):
                cv2.line(out, (px, py), (px + dx * L, py), color, 3, cv2.LINE_AA)
                cv2.line(out, (px, py), (px, py + dy * L), color, 3, cv2.LINE_AA)

            tag = f"{d['name']} {d['conf']:.2f}"
            if d["id"] is not None:
                tag = f"{d['name']} #{d['id']}  {d['conf']:.2f}"
            (tw, th), base = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            ty = y1 - 6 if y1 - th - base - 8 > 0 else y1 + th + base + 4
            cv2.rectangle(out, (x1, ty - th - base - 2), (x1 + tw + 10, ty + base - 1), color, -1)
            cv2.putText(out, tag, (x1 + 5, ty - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (18, 14, 10), 1, cv2.LINE_AA)
        return out

    # ------------------------------------------------------------ streaming
    def _publish(self, jpeg_bytes):
        with self.frame_cond:
            self.jpeg = jpeg_bytes
            self.frame_id += 1
            self.frame_cond.notify_all()

    @staticmethod
    def _make_placeholder():
        img = np.full((540, 960, 3), (26, 14, 8), dtype=np.uint8)
        for x in range(0, 960, 48):
            cv2.line(img, (x, 0), (x, 540), (44, 28, 16), 1)
        for y in range(0, 540, 48):
            cv2.line(img, (0, y), (960, y), (44, 28, 16), 1)
        cv2.circle(img, (480, 225), 54, (251, 211, 34), 2, cv2.LINE_AA)
        cv2.circle(img, (480, 225), 16, (251, 211, 34), -1, cv2.LINE_AA)
        for text, y, scale, col in (("AI VISION X", 340, 1.3, (255, 255, 255)),
                                    ("CAMERA STANDBY", 385, 0.75, (251, 211, 34)),
                                    ("Press START MONITORING to begin real-time detection", 425, 0.55, (180, 160, 140))):
            (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2 if scale > 1 else 1)
            cv2.putText(img, text, ((960 - tw) // 2, y), cv2.FONT_HERSHEY_SIMPLEX, scale, col,
                        2 if scale > 1 else 1, cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes()

    def mjpeg(self):
        last_id = -1
        while True:
            with self.frame_cond:
                self.frame_cond.wait_for(lambda: self.frame_id != last_id, timeout=1.0)
                last_id, jpeg = self.frame_id, self.jpeg
            if jpeg is None:
                jpeg = self.placeholder
                time.sleep(0.25)             # idle: send the standby picture slowly
            yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                   + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")

    # ------------------------------------------------------------ snapshots
    def snapshot(self):
        now = time.time()
        with self.lock:
            active = sum(1 for i in self.tracks.values() if now - i["last_seen"] <= ACTIVE_TRACK_WINDOW)
            return {
                "status": self.status,
                "running": self.status == "live",
                "message": self.message,
                "model_status": self.model_status,
                "model_error": self.model_error,
                "model_name": "YOLO11 Nano",
                "model_file": MODEL_PATH.name,
                "tracker": "ByteTrack",
                "source": self.source,
                "settings": dict(self.settings),
                "fps": round(self.fps, 1),
                "latency_ms": round(self.latency_ms, 1),
                "frames_processed": self.frame_count,
                "uptime_s": int(now - self.session_start) if self.session_start and self.status == "live" else 0,
                "total_detections": self.unique_objects,
                "raw_detections": self.raw_detections,
                "objects_in_frame": len(self.current),
                "active_tracks": active,
                "class_distribution": dict(self.class_distribution.most_common()),
                "frame_counts": dict(self.frame_counts),
                "current": list(self.current),
                "timeline": list(self.timeline),
            }

    def alerts(self, limit):
        with self.lock:
            return list(reversed(list(self.events)))[:limit]

    def active_tracks(self):
        now = time.time()
        with self.lock:
            rows = [
                {"id": i["id"], "class": i["class"], "category": i["category"],
                 "confidence": round(i["confidence"], 3), "frames": i["frames"],
                 "duration_s": round(i["last_seen"] - i["first_seen"], 1),
                 "first_seen": datetime.fromtimestamp(i["first_seen"]).strftime("%H:%M:%S")}
                for i in self.tracks.values() if now - i["last_seen"] <= ACTIVE_TRACK_WINDOW
            ]
        return sorted(rows, key=lambda r: r["id"])

    def update_settings(self, confidence=None, imgsz=None):
        with self.lock:
            if confidence is not None:
                self.settings["confidence"] = round(min(max(float(confidence), 0.05), 0.95), 2)
            if imgsz is not None and int(imgsz) in (320, 480, 640, 960):
                self.settings["imgsz"] = int(imgsz)
            return dict(self.settings)


engine = VisionEngine()
atexit.register(engine.stop)


# --------------------------------------------------------------------------
# System metrics (psutil) - real values, nothing simulated
# --------------------------------------------------------------------------
_net_lock = threading.Lock()
_net_prev = {"t": time.time(), "io": psutil.net_io_counters()}
_net_peak = {"mbps": 0.0}
psutil.cpu_percent(interval=None)            # prime the counter (first call always returns 0)


def system_metrics():
    global _net_prev
    vm = psutil.virtual_memory()
    try:
        disk = psutil.disk_usage(str(BASE_DIR.anchor or "/"))
    except Exception:                        # noqa: BLE001
        disk = psutil.disk_usage("/")

    with _net_lock:
        now, io = time.time(), psutil.net_io_counters()
        dt = max(now - _net_prev["t"], 1e-3)
        down = (io.bytes_recv - _net_prev["io"].bytes_recv) * 8 / dt / 1e6
        up = (io.bytes_sent - _net_prev["io"].bytes_sent) * 8 / dt / 1e6
        _net_prev = {"t": now, "io": io}
        _net_peak["mbps"] = max(_net_peak["mbps"], down + up)

    try:
        link = max((s.speed for s in psutil.net_if_stats().values() if s.isup and s.speed), default=0)
    except Exception:                        # noqa: BLE001
        link = 0

    gb = 1024 ** 3
    return {
        "cpu_percent": round(psutil.cpu_percent(interval=None), 1),
        "cpu_cores": psutil.cpu_count(logical=True),
        "memory_percent": round(vm.percent, 1),
        "memory_used_gb": round(vm.used / gb, 1),
        "memory_total_gb": round(vm.total / gb, 1),
        "disk_percent": round(disk.percent, 1),
        "disk_used_gb": round(disk.used / gb, 1),
        "disk_total_gb": round(disk.total / gb, 1),
        "net_down_mbps": round(down, 2),
        "net_up_mbps": round(up, 2),
        "net_total_mbps": round(down + up, 2),
        "net_link_mbps": link,
        "net_peak_mbps": round(_net_peak["mbps"], 2),
    }


# --------------------------------------------------------------------------
# Flask app + routes
# --------------------------------------------------------------------------
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024      # 1 GB upload limit


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/video_feed")
def video_feed():
    return Response(engine.mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/stats")
def api_stats():
    return jsonify(engine.snapshot())


@app.get("/api/alerts")
def api_alerts():
    limit = min(max(request.args.get("limit", default=40, type=int), 1), MAX_EVENTS)
    return jsonify({"alerts": engine.alerts(limit)})


@app.get("/api/tracks")
def api_tracks():
    return jsonify({"tracks": engine.active_tracks()})


@app.get("/api/system")
def api_system():
    return jsonify(system_metrics())


@app.get("/api/videos")
def api_videos():
    files = sorted(p.name for p in UPLOAD_DIR.iterdir() if p.suffix.lower() in ALLOWED_VIDEO_EXT)
    return jsonify({"videos": files})


@app.post("/api/control/start")
def api_start():
    data = request.get_json(silent=True) or {}
    ok, message = engine.start(
        source_type="video" if data.get("source") == "video" else "webcam",
        camera_index=data.get("camera_index", 0),
        video_name=data.get("video"),
    )
    if "confidence" in data or "imgsz" in data:
        engine.update_settings(data.get("confidence"), data.get("imgsz"))
    return jsonify({"ok": ok, "message": message}), (200 if ok else 400)


@app.post("/api/control/stop")
def api_stop():
    engine.stop()
    return jsonify({"ok": True, "message": "Monitoring stopped."})


@app.post("/api/settings")
def api_settings():
    data = request.get_json(silent=True) or {}
    try:
        settings = engine.update_settings(data.get("confidence"), data.get("imgsz"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Invalid settings value."}), 400
    return jsonify({"ok": True, "settings": settings})


@app.post("/api/upload")
def api_upload():
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"ok": False, "message": "No file received."}), 400
    name = secure_filename(file.filename)
    if Path(name).suffix.lower() not in ALLOWED_VIDEO_EXT:
        return jsonify({"ok": False,
                        "message": "Unsupported file type. Use " + ", ".join(sorted(ALLOWED_VIDEO_EXT))}), 400
    file.save(UPLOAD_DIR / name)
    return jsonify({"ok": True, "filename": name})


@app.errorhandler(413)
def too_large(_):
    return jsonify({"ok": False, "message": "File is too large (limit 1 GB)."}), 413


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    print("=" * 56)
    print("   AI VISION X  -  Intelligent Vision Analytics")
    print("   See Beyond the Ordinary")
    print("=" * 56)
    print(f"   Dashboard:  http://{host}:{port}")
    print("   Press CTRL+C to quit.\n")

    engine.load_model_async()
    if not os.environ.get("AI_VISION_NO_BROWSER"):
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{host}:{port}")).start()

    # use_reloader=False is important: the reloader would start a second process
    # that loads the model and grabs the webcam twice.
    app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)
