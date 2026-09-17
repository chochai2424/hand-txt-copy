"""Enumerate and preview cameras to find the right index for config/default.yaml.

Usage (from the repo root, with the venv active):
    python scripts/check_camera.py            # probe indices 0..4, print which open
    python scripts/check_camera.py --preview 0  # live preview of index 0 (press Q to quit)
"""

from __future__ import annotations

import argparse

import cv2


def probe(max_index: int = 5) -> None:
    print("Probing camera indices...")
    for i in range(max_index):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        ok = cap.isOpened()
        if ok:
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            print(f"  index {i}: OPEN ({w}x{h})")
        else:
            print(f"  index {i}: not available")
        cap.release()


def preview(index: int) -> None:
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"could not open camera index {index}")
        return
    print("Press Q to close the preview window.")
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        cv2.imshow(f"camera {index}", cv2.flip(frame, 1))
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    cap.release()
    cv2.destroyAllWindows()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", type=int, metavar="INDEX", help="live-preview this index")
    parser.add_argument("--max", type=int, default=5, help="highest index to probe (default 5)")
    args = parser.parse_args()
    if args.preview is not None:
        preview(args.preview)
    else:
        probe(args.max)


if __name__ == "__main__":
    main()
