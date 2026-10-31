# AI VISION X — Intelligent Vision Analytics
**Tagline:** *See Beyond the Ordinary*

Real-time **object detection and tracking** with a premium dark dashboard.
Built for **Internship Task 4: Object Detection and Tracking**.

| Task 4 objective | Where it is done |
|---|---|
| 1. Real-time video input (webcam or video file, OpenCV) | `VisionEngine.start()` / `_open_webcam()` in `app.py` |
| 2. Pre-trained model (YOLO) | Ultralytics **YOLO11 Nano** — your existing `yolo11n.pt`, not retrained |
| 3. Process every frame, draw bounding boxes | `model.track(...)` + `_draw()` in `app.py` |
| 4. Tracking algorithm (SORT / Deep SORT / ByteTrack) | **ByteTrack** (`tracker="bytetrack.yaml"`) |
| 5. Output with labels and tracking IDs in real time | Live MJPEG stream on the dashboard: `person #3 0.91` |

---

## 1. Run it (Windows, PowerShell)

Open PowerShell **inside the project folder** (in VS Code: *Terminal → New Terminal*), then:

```powershell
# 1) activate your existing virtual environment
.\.venv\Scripts\Activate.ps1

# 2) (only needed once) make sure every package is installed
pip install -r requirements.txt

# 3) start the dashboard
python app.py
```

Your browser opens automatically at **http://127.0.0.1:5000**. If it doesn't, open that address yourself.
Click **Start**, allow the camera if Windows asks, and you are live. Press **Ctrl + C** in PowerShell to quit.

> If PowerShell says *"running scripts is disabled"* when activating the venv, run this once and try again:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

Your original program still works exactly as before: `python main.py` (press **Q** to quit).

---

## 2. How the new app integrates with your existing code

Your `main.py` already contained the complete AI pipeline:
`cv2.VideoCapture` → `model.track(persist=True, tracker="bytetrack.yaml")` → draw → show.

**`app.py` reuses the same pipeline** (same model file, same ByteTrack tracker, same default confidence 0.35).
The only difference is *where the result goes*: instead of an OpenCV desktop window, each annotated frame is
encoded as JPEG and streamed to the browser.

```
 webcam / video file
        │  OpenCV
        ▼
 background thread ──► YOLO11n + ByteTrack (model.track)
        │                     │
        │                     ├─► boxes, labels, track IDs ──► drawn on frame ──► /video_feed (MJPEG)
        │                     └─► counters, events, tracks ───► /api/stats, /api/alerts, /api/tracks
        ▼
 Flask web server  ◄── browser polls the /api/* endpoints with fetch()  ◄── static/js/script.js
                       and renders cards, charts, gauges
```

Why a background thread? Inference takes tens of milliseconds per frame. Running it in its own thread keeps the
web server responsive, so the buttons, charts and system gauges never freeze.

### What I changed in your project (and why)

| File | Status | Reason |
|---|---|---|
| `main.py` | **Unchanged** | Your working standalone detector. |
| `yolo11n.pt` | **Unchanged** | Pre-trained weights, not retrained. |
| `.venv/` | **Unchanged** | Never touched. |
| `app.py` | **Replaced** | The old `app.py` was a **Streamlit** app. Streamlit is not allowed in this brief, and it re-runs the whole script on every refresh, which makes live video choppy. The new `app.py` is a Flask server. |
| `app_streamlit_backup.py` | **New (backup)** | Your old Streamlit file, kept so nothing is lost. Safe to delete. |
| `templates/index.html`, `static/css/style.css`, `static/js/script.js` | **New** | The dashboard. |
| `requirements.txt`, `README.md` | **New** | Setup and documentation. |
| `uploads/` | **Created at run time** | Where uploaded videos are stored. |

---

## 3. Dashboard tour

* **Sidebar:** Dashboard · Cameras · Detections · Tracking · Alerts · Analytics · Settings
* **Top bar:** title, **LIVE / STANDBY** status, model status, date & time, **Refresh**
* **Stat cards:** Total Detections · Objects in Frame · Active Tracks · Inference FPS
* **Live panel:** annotated video with boxes, class labels, confidence and **tracking IDs**, plus short movement trails.
  Start / Stop buttons, and a **Webcam / Video file** switch (upload a video and process it).
* **Right panel:** *Recent Detection Events* with time, class, track ID, confidence
* **Analytics:** object-distribution chart (Chart.js), objects-in-frame timeline, detection statistics
* **System status:** CPU, memory, disk and network rings (from `psutil`)
* **Settings:** confidence threshold and inference size, applied live

### What the numbers mean (all real, nothing simulated)

| Value | Definition |
|---|---|
| **Total Detections** | Number of *unique objects* tracked this session (each new ByteTrack ID counts once). |
| **Objects in Frame** | Boxes detected in the most recent frame. |
| **Active Tracks** | Track IDs seen within the last 1.5 seconds. |
| **Inference FPS** | Processing speed of the full pipeline (read + detect + track + draw). For video files, playback is paced to the file's own frame rate, so this shows capacity, not playback speed. |
| **Detection events** | Logged the first time a track ID appears. These are object-detection events, **not** verified security incidents. |

Box colours: **cyan** = person, **amber** = vehicle, **green** = animal, **violet** = other objects.

---

## 4. Files

```
AI Object Detection & Tracking System/
├── .venv/                  your virtual environment (untouched)
├── main.py                 your standalone detector (untouched)
├── app.py                  Flask backend  (NEW - replaces the Streamlit file)
├── app_streamlit_backup.py backup of your old Streamlit app.py
├── yolo11n.pt              YOLO11 Nano weights (untouched)
├── requirements.txt
├── README.md
├── templates/index.html    dashboard page
└── static/
    ├── css/style.css       dark navy neon theme
    └── js/script.js        polling, charts, gauges, controls
```

## 5. API endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/` | Dashboard page |
| GET | `/video_feed` | MJPEG stream of the annotated frames |
| GET | `/api/stats` | Detection statistics, current objects, FPS, chart data |
| GET | `/api/alerts?limit=N` | Recent detection events (newest first) |
| GET | `/api/system` | CPU, memory, disk, network |
| POST | `/api/control/start` | Start monitoring. Body: `{"source":"webcam","camera_index":0}` or `{"source":"video","video":"clip.mp4"}` |
| POST | `/api/control/stop` | Stop monitoring |
| GET | `/api/tracks` | Currently active tracks *(extra)* |
| GET | `/api/videos` | Uploaded video list *(extra)* |
| POST | `/api/upload` | Upload a video file *(extra)* |
| POST | `/api/settings` | Change confidence / inference size *(extra)* |

---

## 6. Troubleshooting

| Problem | Fix |
|---|---|
| **"Could not open the webcam"** | Close Zoom / Teams / the Windows Camera app. Check *Settings → Privacy & security → Camera* (allow desktop apps). Try *Camera 1* in the dropdown. |
| **Start button says "Loading the YOLO model…"** | Wait 5–15 s on first start (PyTorch is loading). If it turns into an error, make sure `yolo11n.pt` sits next to `app.py` and `pip install -r requirements.txt` finished. |
| **`ModuleNotFoundError: flask` (or another module)** | The venv is not active. Run `.\.venv\Scripts\Activate.ps1`, then `pip install -r requirements.txt`. |
| **Video is laggy** | *Settings → Inference size → 320 or 480*. Close other heavy apps. YOLO11n on CPU typically reaches roughly 8–25 FPS depending on the laptop. |
| **Port 5000 already in use** | `$env:PORT=5001; python app.py` and open `http://127.0.0.1:5001`. |
| **Charts are blank / "Chart.js" error** | Charts load from a CDN, so the first load needs internet. Offline, the dashboard switches to simple built-in charts automatically. |
| **Tracking IDs jump or objects get new IDs** | Normal when an object is hidden for a while. Raising the confidence threshold a little (0.40–0.50) makes tracking steadier. |
| **Page doesn't open by itself** | Open `http://127.0.0.1:5000` manually. |
| **Uploaded video won't play** | Use `.mp4` (H.264). Some exotic codecs can't be decoded by OpenCV. |

## 7. Screenshots

After your first live run, press **Win + Shift + S**, capture the dashboard while objects are detected,
and save the images into a `docs/` folder. Add them below for your internship report:

```
![Dashboard](docs/dashboard.png)
![Tracking IDs](docs/tracking.png)
```

---
*AI VISION X · YOLO11 + ByteTrack + OpenCV + Flask*
