import cv2
import time
from ultralytics import YOLO


def main():
    print("=" * 50)
    print("       AI VISION X")
    print("  Object Detection and Tracking")
    print("=" * 50)

    # Load pretrained YOLO model
    print("\nLoading YOLO model...")
    model = YOLO("yolo11n.pt")

    # Open webcam
    print("Opening webcam...")
    camera = cv2.VideoCapture(0)

    if not camera.isOpened():
        print("ERROR: Cannot access webcam.")
        return

    # Set camera resolution
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    print("\nAI VISION X is running!")
    print("Press Q to quit.")

    previous_time = time.time()

    try:
        while True:
            success, frame = camera.read()

            if not success:
                print("Unable to capture frame.")
                break

            # Detect and track objects
            results = model.track(
                source=frame,
                persist=True,
                tracker="bytetrack.yaml",
                conf=0.35,
                verbose=False
            )

            result = results[0]

            # Draw boxes, labels and tracking IDs
            output = result.plot()

            # Count detected objects
            object_count = len(result.boxes)

            # Calculate approximate FPS
            current_time = time.time()
            elapsed = current_time - previous_time
            fps = 1 / elapsed if elapsed > 0 else 0
            previous_time = current_time

            # Add project title
            cv2.putText(
                output,
                "AI VISION X",
                (15, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2
            )

            # Display object count
            cv2.putText(
                output,
                f"Objects Detected: {object_count}",
                (15, 65),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 255, 0),
                2
            )

            # Display FPS
            cv2.putText(
                output,
                f"FPS: {fps:.1f}",
                (15, 100),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 255, 0),
                2
            )

            # Show the AI output
            cv2.imshow(
                "AI VISION X - Detection and Tracking",
                output
            )

            # Press Q to quit
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        camera.release()
        cv2.destroyAllWindows()

    print("AI VISION X stopped.")


if __name__ == "__main__":
    main()