import cv2
import time
import psutil
import streamlit as st
import pandas as pd

from collections import Counter
from datetime import datetime
from ultralytics import YOLO


# =====================================================
# PAGE CONFIGURATION
# =====================================================

st.set_page_config(
    page_title="AI VISION X | Command Center",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)


# =====================================================
# PROFESSIONAL DARK THEME
# =====================================================

st.markdown("""
<style>
.stApp {
    background: #0B1220;
    color: #E8EEF9;
}

[data-testid="stSidebar"] {
    background: #172334;
    border-right: 1px solid #2B3B52;
}

[data-testid="stSidebar"] * {
    color: #E8EEF9;
}

.block-container {
    padding-top: 1.3rem;
    padding-bottom: 2rem;
    max-width: 1800px;
}

h1, h2, h3 {
    color: #F3F6FC;
}

p, label {
    color: #BAC7D9;
}

div[data-testid="stMetric"] {
    background: #192638;
    border: 1px solid #2B3C53;
    padding: 18px;
    border-radius: 12px;
}

div[data-testid="stMetricLabel"] {
    color: #AABBD0;
}

div[data-testid="stMetricValue"] {
    color: #FFFFFF;
}

div[data-testid="stImage"] {
    border-radius: 12px;
    overflow: hidden;
}

div.stButton > button {
    border-radius: 7px;
    min-height: 40px;
    font-weight: 600;
}

.card {
    background: #192638;
    border: 1px solid #2B3C53;
    border-radius: 12px;
    padding: 17px;
    margin-bottom: 12px;
}

.card-title {
    color: #AABBD0;
    font-size: 13px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.card-value {
    color: #FFFFFF;
    font-size: 29px;
    font-weight: 750;
    margin-top: 8px;
}

.section-heading {
    color: #EAF0FA;
    font-size: 17px;
    font-weight: 700;
    margin-bottom: 12px;
}

.status-dot {
    color: #43D9A3;
    font-weight: bold;
}

.small-text {
    font-size: 12px;
    color: #94A6BF;
}

.alert-item {
    background: #111C2B;
    border-left: 4px solid #42D39A;
    border-radius: 5px;
    padding: 11px;
    margin-bottom: 9px;
}

.alert-warning {
    border-left-color: #F5BC48;
}

.alert-danger {
    border-left-color: #EF6464;
}

div[data-testid="stProgress"] > div > div {
    background-color: #43D9A3;
}
</style>
""", unsafe_allow_html=True)


# =====================================================
# LOAD YOLO MODEL
# =====================================================

@st.cache_resource
def load_model():
    return YOLO("yolo11n.pt")


# =====================================================
# SESSION STATE
# =====================================================

defaults = {
    "camera_running": False,
    "camera": None,
    "total_frames": 0,
    "total_detections": 0,
    "event_log": [],
    "last_objects": [],
    "last_fps": 0.0,
    "last_counts": {},
    "last_frame_time": time.time(),
    "tracked_ids": set(),
    "session_start": None,
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# =====================================================
# SIDEBAR NAVIGATION
# =====================================================

with st.sidebar:

    st.markdown("""
    <div style="text-align:center;padding:15px 0 22px;">
        <div style="font-size:44px;">🎯</div>
        <div style="font-size:24px;font-weight:800;">
            AI VISION X
        </div>
        <div style="font-size:12px;color:#9FB1C9;">
            INTELLIGENT VISION PLATFORM
        </div>
        <div style="font-size:11px;color:#7E91AA;">
            YOLO · OpenCV · ByteTrack
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    page = st.radio(
        "NAVIGATION",
        [
            "Dashboard",
            "Cameras",
            "Detections",
            "Alerts",
            "Live Stream",
            "Settings"
        ],
        label_visibility="collapsed"
    )

    st.divider()

    st.markdown("### ⚙️ Detection Settings")

    confidence = st.slider(
        "Confidence Threshold",
        min_value=0.10,
        max_value=0.90,
        value=0.35,
        step=0.05
    )

    st.caption(
        "Increase the threshold to filter out less-confident detections."
    )

    camera_index = st.selectbox(
        "Camera Source",
        [0, 1, 2],
        format_func=lambda x: f"Camera {x}"
    )

    st.divider()

    st.markdown("### 🧠 AI Engine")

    st.success("YOLO11 Nano")

    st.markdown("### 🆔 Tracking Engine")

    st.info("ByteTrack")


# =====================================================
# HEADER
# =====================================================

header_left, header_right = st.columns([3, 2])

with header_left:
    st.markdown(
        "# AI VISION X"
    )
    st.caption(
        "INTELLIGENT OBJECT DETECTION & TRACKING COMMAND CENTER"
    )

with header_right:

    h1, h2 = st.columns([1, 1])

    with h1:
        if st.session_state.camera_running:
            st.success("● System Online")
        else:
            st.warning("● Standby")

    with h2:
        st.caption(
            datetime.now().strftime("%d %b %Y · %H:%M:%S")
        )

st.divider()


# =====================================================
# CAMERA CONTROLS
# =====================================================

control1, control2, control3 = st.columns([1, 1, 4])

with control1:

    if st.button(
        "▶ Start Monitoring",
        use_container_width=True,
        type="primary"
    ):

        if not st.session_state.camera_running:

            camera = cv2.VideoCapture(camera_index)

            if camera.isOpened():

                camera.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
                camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)

                st.session_state.camera = camera
                st.session_state.camera_running = True
                st.session_state.session_start = time.time()
                st.rerun()

            else:
                camera.release()
                st.error(
                    "Unable to open camera. Check camera permissions "
                    "or close other applications using the webcam."
                )

with control2:

    if st.button(
        "■ Stop Monitoring",
        use_container_width=True
    ):

        st.session_state.camera_running = False

        if st.session_state.camera is not None:
            st.session_state.camera.release()
            st.session_state.camera = None

        st.rerun()

with control3:

    if st.session_state.camera_running:
        st.success("LIVE MONITORING ACTIVE")
    else:
        st.info("Monitoring is stopped. Start the camera to begin.")

st.divider()


# =====================================================
# LIVE CAMERA PROCESSING
# =====================================================

@st.fragment(run_every=0.2)
def live_camera_panel():

    if not st.session_state.camera_running:

        st.info(
            "Camera feed is offline. Click Start Monitoring to begin."
        )

        return

    camera = st.session_state.camera

    if camera is None or not camera.isOpened():

        st.error("Camera connection lost.")

        return

    success, frame = camera.read()

    if not success:

        st.warning("Unable to capture a camera frame.")

        return

    start_time = time.perf_counter()

    model = load_model()

    results = model.track(
        source=frame,
        persist=True,
        tracker="bytetrack.yaml",
        conf=confidence,
        verbose=False
    )

    result = results[0]

    annotated_frame = result.plot()

    counts = Counter()
    current_objects = []
    current_ids = set()

    if result.boxes is not None:

        for box in result.boxes:

            class_id = int(box.cls[0])
            name = model.names[class_id]
            score = float(box.conf[0])

            counts[name] += 1

            track_id = None

            if box.id is not None:
                track_id = int(box.id[0])
                current_ids.add(track_id)

            current_objects.append({
                "Object": name,
                "Confidence": round(score, 3),
                "Tracking ID": (
                    track_id if track_id is not None else "Pending"
                )
            })

    elapsed = time.perf_counter() - start_time

    fps = 1 / elapsed if elapsed > 0 else 0

    st.session_state.total_frames += 1
    st.session_state.last_fps = fps
    st.session_state.last_counts = dict(counts)
    st.session_state.last_objects = current_objects
    st.session_state.tracked_ids.update(current_ids)

    st.session_state.total_detections += len(current_objects)

    # Record new object categories in a small event log.
    now = datetime.now().strftime("%H:%M:%S")

    for name, count in counts.items():

        event = {
            "Time": now,
            "Event": f"{name.title()} detected",
            "Count": count,
        }

        log = st.session_state.event_log

        if not log or (
            log[-1]["Event"] != event["Event"]
            or log[-1]["Time"] != event["Time"]
        ):
            log.append(event)

    st.session_state.event_log = (
        st.session_state.event_log[-30:]
    )

    # Add application title to the video.
    cv2.putText(
        annotated_frame,
        "AI VISION X | LIVE",
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (67, 217, 163),
        2
    )

    # Convert OpenCV BGR image to RGB.
    rgb_frame = cv2.cvtColor(
        annotated_frame,
        cv2.COLOR_BGR2RGB
    )

    # Dashboard layout.
    video_col, right_col = st.columns(
        [1.85, 1],
        gap="medium"
    )

    with video_col:

        st.markdown(
            '<div class="section-heading">'
            '📹 LIVE CAMERA STREAM — CAM 1'
            '</div>',
            unsafe_allow_html=True
        )

        st.image(
            rgb_frame,
            use_container_width=True
        )

        st.caption(
            "Live webcam feed · Detection boxes · Tracking IDs"
        )

    with right_col:

        st.markdown(
            '<div class="section-heading">'
            '📊 LIVE ANALYTICS'
            '</div>',
            unsafe_allow_html=True
        )

        m1, m2 = st.columns(2)

        m1.metric(
            "Objects in Frame",
            len(current_objects)
        )

        m2.metric(
            "Categories",
            len(counts)
        )

        m3, m4 = st.columns(2)

        m3.metric(
            "Inference FPS",
            f"{fps:.1f}"
        )

        m4.metric(
            "Tracked IDs in Frame",
            len(current_ids)
        )

        st.markdown(
            '<div class="section-heading">'
            '📦 OBJECT CATEGORIES'
            '</div>',
            unsafe_allow_html=True
        )

        if counts:

            chart_data = pd.DataFrame(
                list(counts.items()),
                columns=["Object", "Count"]
            ).set_index("Object")

            st.bar_chart(
                chart_data,
                height=180
            )

        else:

            st.caption("No objects detected in this frame.")

        st.markdown(
            '<div class="section-heading">'
            '🔍 DETECTION DETAILS'
            '</div>',
            unsafe_allow_html=True
        )

        if current_objects:

            st.dataframe(
                pd.DataFrame(current_objects),
                use_container_width=True,
                hide_index=True,
                height=200
            )

        else:

            st.caption("No detection details available.")


# =====================================================
# DASHBOARD PAGE
# =====================================================

if page == "Dashboard":

    live_camera_panel()

    st.divider()

    st.markdown("## 🖥️ System Status")

    cpu_col, memory_col, detection_col = st.columns(3)

    cpu_usage = psutil.cpu_percent(interval=None)
    memory_usage = psutil.virtual_memory()

    with cpu_col:

        st.metric(
            "CPU Usage",
            f"{cpu_usage:.1f}%"
        )

        st.progress(
            min(cpu_usage / 100, 1.0)
        )

    with memory_col:

        st.metric(
            "Memory Usage",
            f"{memory_usage.percent:.1f}%"
        )

        st.progress(
            min(memory_usage.percent / 100, 1.0)
        )

    with detection_col:

        st.metric(
            "Frames Processed",
            st.session_state.total_frames
        )

        st.caption(
            "Frames processed during this application session."
        )


# =====================================================
# OTHER NAVIGATION PAGES
# =====================================================

elif page == "Cameras":

    st.title("📹 Camera Management")

    st.info(
        "This prototype uses your local webcam. "
        "Additional camera sources can be integrated later."
    )

    st.write("Selected camera:", camera_index)

    st.write(
        "Camera status:",
        "Online" if st.session_state.camera_running else "Offline"
    )


elif page == "Detections":

    st.title("🔍 Detection History")

    st.metric(
        "Total Frames Processed",
        st.session_state.total_frames
    )

    st.metric(
        "Total Frame Detections",
        st.session_state.total_detections
    )

    if st.session_state.last_objects:

        st.dataframe(
            pd.DataFrame(st.session_state.last_objects),
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info(
            "Start monitoring to collect detection information."
        )


elif page == "Alerts":

    st.title("🚨 Detection Event Log")

    st.caption(
        "These are object-detection events, not verified security incidents."
    )

    if st.session_state.event_log:

        st.dataframe(
            pd.DataFrame(
                list(reversed(st.session_state.event_log))
            ),
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info(
            "No detection events recorded yet."
        )


elif page == "Live Stream":

    st.title("📡 Live Stream")

    live_camera_panel()


elif page == "Settings":

    st.title("⚙️ Application Settings")

    st.write(
        "Model: YOLO11 Nano"
    )

    st.write(
        "Tracking algorithm: ByteTrack"
    )

    st.write(
        "Camera index:", camera_index
    )

    st.write(
        "Detection confidence:", confidence
    )

    st.info(
        "Changes to the confidence threshold apply to subsequent frames."
    )


# =====================================================
# FOOTER
# =====================================================

st.divider()

st.caption(
    "AI VISION X · Intelligent Computer Vision · "
    "YOLO + OpenCV + ByteTrack"
)