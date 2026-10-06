#!/usr/bin/env python3
# USB 카메라 1대 확인 도구 (라즈베리파이 호환, 자동 재연결)
# [2026-07-12 수정] 듀얼 → 싱글 카메라로 단순화 (front /dev/video0 전용)
#                   어두운 화면 수정: FOURCC 강제 제거 → 카메라 기본 포맷 사용
#                   자동 노출 + 밝기 보정 추가
"""
USB 카메라 확인 도구 (싱글)
============================
브라우저에서 카메라 영상을 실시간 확인합니다.
SSH 환경에서도 사용 가능!

사용법:
  python camera_check.py                    # 자동 감지
  python camera_check.py --front 0          # 번호로 지정
  python camera_check.py --front /dev/video0 --port 8080

브라우저에서 http://<IP>:5555 접속
"""

import argparse
import json
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

try:
    import cv2
except ImportError:
    print("❌ opencv-python이 설치되어 있지 않습니다.")
    print("   pip install opencv-python")
    sys.exit(1)


# ── 전역 상태 ────────────────────────────────────────────
frames        = {}
frame_lock    = threading.Lock()
camera_info   = {}
byte_counters = {'front': 0}
byte_rates    = {'front': 0}
cam_args      = None


# ── HTML 페이지 (싱글 카메라) ──────────────────────────────
HTML_PAGE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>📷 LeKiwi 카메라 확인</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, 'Noto Sans KR', sans-serif;
    background: #0F172A; color: #E2E8F0;
    display: flex; flex-direction: column; align-items: center;
    min-height: 100vh; padding: 1.5rem;
  }
  h1 { font-size: 1.5rem; margin-bottom: 1rem; }
  .cam-container { width: 100%%; max-width: 800px; }
  .cam-label {
    background: #1E293B; border-radius: 10px 10px 0 0;
    padding: 0.6rem 1rem; display: flex; justify-content: space-between;
    align-items: center; font-weight: 700; font-size: 0.9rem;
  }
  .tag {
    background: #2563EB; padding: 0.15rem 0.6rem;
    border-radius: 999px; font-size: 0.75rem;
  }
  .camera-box {
    background: #1E293B; border-radius: 0 0 10px 10px;
    padding: 4px; padding-top: 0;
  }
  .cam-stream {
    display: block; border-radius: 0 0 8px 8px;
    width: 100%%; height: auto;
  }
  .info {
    background: #1E293B; border-radius: 10px; padding: 1rem 1.25rem;
    font-size: 0.85rem; line-height: 1.8;
    width: 100%%; max-width: 800px; margin-top: 0.75rem;
  }
  .info-title { font-weight: 700; margin-bottom: 0.5rem; }
  .info-row {
    display: flex; justify-content: space-between;
    border-bottom: 1px solid #334155; padding: 0.2rem 0;
  }
  .info-row:last-child { border: none; }
  .label { color: #94A3B8; }
  .value { color: #38BDF8; font-weight: 700; font-family: monospace; }
  .status-ok  { color: #4ADE80; }
  .status-err { color: #F87171; }
  .controls {
    display: flex; gap: 0.75rem; margin: 1rem 0;
    flex-wrap: wrap; justify-content: center;
  }
  .btn {
    background: #334155; color: #E2E8F0; border: 1px solid #475569;
    border-radius: 8px; padding: 0.5rem 1.25rem; cursor: pointer;
    font-size: 0.85rem; font-weight: 600; transition: all 0.15s;
  }
  .btn:hover { background: #475569; }
  .btn-blue { background: #2563EB; border-color: #3B82F6; }
  .btn-blue:hover { background: #1D4ED8; }
  .bandwidth {
    font-size: 0.8rem; color: #94A3B8; text-align: center; margin-top: 0.5rem;
  }
</style>
</head>
<body>
  <h1>📷 LeKiwi 카메라 확인</h1>

  <div class="cam-container">
    <div class="cam-label">
      <span>Front Camera</span>
      <span class="tag">FRONT_DEVICE</span>
    </div>
    <div class="camera-box">
      <img id="stream-front" class="cam-stream" src="/stream/front" width="640" height="480">
    </div>
  </div>

  <div class="controls">
    <button class="btn btn-blue" onclick="snapshot()">📸 스냅샷</button>
    <button class="btn" onclick="toggleRotation()">🔄 180° 회전</button>
    <button class="btn" onclick="location.reload()">🔃 새로고침</button>
  </div>
  <div class="bandwidth" id="bw">대역폭 측정 중...</div>

  <div class="info">
    <div class="info-title">📷 Front Camera</div>
    <div class="info-row">
      <span class="label">상태</span>
      <span class="value" id="st-front">연결 중...</span>
    </div>
    FRONT_INFO
  </div>

  <script>
    let rotated = false;

    function toggleRotation() {
      rotated = !rotated;
      document.getElementById('stream-front').style.transform =
        rotated ? 'rotate(180deg)' : 'none';
    }

    function snapshot() {
      const img = document.getElementById('stream-front');
      const canvas = document.createElement('canvas');
      canvas.width = img.naturalWidth; canvas.height = img.naturalHeight;
      const ctx = canvas.getContext('2d');
      if (rotated) { ctx.translate(canvas.width, canvas.height); ctx.rotate(Math.PI); }
      ctx.drawImage(img, 0, 0);
      const link = document.createElement('a');
      link.download = 'lekiwi_front_' + Date.now() + '.jpg';
      link.href = canvas.toDataURL('image/jpeg', 0.95);
      link.click();
    }

    const img = document.getElementById('stream-front');
    img.onload = () => {
      document.getElementById('st-front').innerHTML =
        '<span class="status-ok">✅ 수신 중</span>';
    };
    img.onerror = () => {
      document.getElementById('st-front').innerHTML =
        '<span class="status-err">❌ 끊김 — 재연결 중...</span>';
      setTimeout(() => { img.src = '/stream/front?' + Date.now(); }, 2000);
    };

    setInterval(async () => {
      try {
        const res = await fetch('/stats');
        const d   = await res.json();
        document.getElementById('bw').textContent =
          'Front: ' + d.front_kbps + ' KB/s (' +
          (d.front_kbps * 8 / 1000).toFixed(1) + ' Mbps)';
      } catch (e) {}
    }, 2000);
  </script>
</body>
</html>"""


# ── HTTP 핸들러 ──────────────────────────────────────────
class StreamHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == '/':
            self._serve_index()
        elif self.path.startswith('/stream/front'):
            self._serve_stream('front')
        elif self.path == '/stats':
            self._serve_stats()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_index(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()

        page = HTML_PAGE
        page = page.replace('FRONT_DEVICE', cam_args.front)

        info_html = ""
        if 'front' in camera_info:
            for k, v in camera_info['front'].items():
                info_html += (
                    f'<div class="info-row">'
                    f'<span class="label">{k}</span>'
                    f'<span class="value">{v}</span>'
                    f'</div>\n'
                )
        page = page.replace('FRONT_INFO', info_html)
        self.wfile.write(page.encode())

    def _serve_stream(self, cam_name):
        self.send_response(200)
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
        self.end_headers()

        while True:
            try:
                with frame_lock:
                    data = frames.get(cam_name)
                if data is None:
                    time.sleep(0.03)
                    continue

                self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\n\r\n')
                self.wfile.write(data)
                self.wfile.write(b'\r\n')

                with frame_lock:
                    byte_counters[cam_name] += len(data)

                time.sleep(0.033)
            except (BrokenPipeError, ConnectionResetError):
                break

    def _serve_stats(self):
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            with frame_lock:
                stats = {'front_kbps': round(byte_rates.get('front', 0) / 1024)}
            self.wfile.write(json.dumps(stats).encode())
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format, *args):
        pass


# ── 대역폭 추적 ───────────────────────────────────────────
def bandwidth_tracker():
    while True:
        time.sleep(1)
        with frame_lock:
            byte_rates['front']    = byte_counters['front']
            byte_counters['front'] = 0


# ── 카메라 캡처 스레드 ────────────────────────────────────
def camera_thread(device_path: str) -> None:
    """front 카메라에서 프레임을 읽어 전역 frames에 저장한다.

    [2026-07-12 수정] 싱글 카메라 전용으로 단순화
                      FOURCC 강제 설정 제거 → 어두운 화면 수정
                      자동 노출 ON 설정 추가
    """
    RECONNECT_WAIT = 3.0
    MAX_FAIL       = 30

    while True:
        print(f"⏳ front: {device_path} 연결 시도 중...")

        cap = cv2.VideoCapture(device_path, cv2.CAP_V4L2)

        if not cap.isOpened():
            print(f"❌ {device_path} 열기 실패 — {RECONNECT_WAIT}초 후 재시도")
            camera_info['front'] = {'상태': '❌ 연결 실패'}
            time.sleep(RECONNECT_WAIT)
            continue

        # [2026-07-12 수정] MJPG 강제 제거 → 카메라 기본 포맷(YUYV) 사용
        # MJPG 강제 설정 시 Pi5 드라이버에서 raw Bayer 패턴으로 잘못 읽혀 어두워짐
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS,          30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)    # 지연 최소화

        # 자동 노출 ON (밝기 자동 조정)
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)   # 3 = 자동 (V4L2 기준)

        w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)

        camera_info['front'] = {
            '디바이스': device_path,
            '해상도':   f'{w} × {h}',
            'FPS':      f'{fps:.0f}',
        }
        print(f"✅ front: {device_path} 연결 ({w}×{h} @ {fps:.0f}fps)")

        consec_fail = 0
        while True:
            ret, frame = cap.read()

            if not ret or frame is None:
                consec_fail += 1
                if consec_fail >= MAX_FAIL:
                    print(f"⚠️  프레임 실패 {consec_fail}회 → 재연결")
                    break
                time.sleep(0.01)
                continue

            consec_fail = 0
            ret_enc, jpeg = cv2.imencode(
                '.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85]
            )
            if ret_enc:
                with frame_lock:
                    frames['front'] = jpeg.tobytes()

        cap.release()
        camera_info['front'] = {'상태': '🔄 재연결 중...'}
        time.sleep(RECONNECT_WAIT)


# ── 카메라 자동 감지 ──────────────────────────────────────
def auto_detect() -> list[str]:
    import subprocess
    try:
        result = subprocess.run(
            ['v4l2-ctl', '--list-devices'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            print("\n📋 감지된 V4L2 장치:")
            print(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    available = []
    for i in range(10):
        path = f'/dev/video{i}'
        cap  = cv2.VideoCapture(path, cv2.CAP_V4L2)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret and frame is not None:
                # 밝기 확인 (10 이하면 가상 장치로 판단)
                mean = frame.mean()
                if mean > 5:
                    h, w = frame.shape[:2]
                    available.append(path)
                    print(f"  ✅ {path}: {w}×{h} (밝기={mean:.1f})")
                else:
                    print(f"  ⚠️  {path}: 밝기={mean:.1f} (가상 장치, 제외)")
            cap.release()
    return available


def to_device_path(value: str) -> str:
    if value.startswith('/dev/'):
        return value
    try:
        return f'/dev/video{int(value)}'
    except ValueError:
        return value


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def main() -> None:
    global cam_args

    parser = argparse.ArgumentParser(description="LeKiwi 카메라 확인 (싱글)")
    parser.add_argument(
        "--front", type=str, default=None,
        help="카메라 번호 또는 경로 (예: 0 또는 /dev/video0)"
    )
    parser.add_argument("--port", type=int, default=5555, help="포트 (기본: 5555)")
    cam_args = parser.parse_args()

    if cam_args.front is not None:
        cam_args.front = to_device_path(cam_args.front)

    print("🔍 카메라 자동 감지 중...")
    available = auto_detect()

    if cam_args.front is None:
        if available:
            cam_args.front = available[0]
            print(f"\n🎯 자동 설정: front={cam_args.front}")
        else:
            print("\n❌ 카메라를 찾을 수 없습니다!")
            sys.exit(1)

    threading.Thread(
        target=camera_thread, args=(cam_args.front,), daemon=True
    ).start()
    threading.Thread(target=bandwidth_tracker, daemon=True).start()

    time.sleep(1.5)

    server = ThreadingHTTPServer(('0.0.0.0', cam_args.port), StreamHandler)

    print(f"\n{'='*50}")
    print(f"  📷 LeKiwi 카메라 확인")
    print(f"  Front: {cam_args.front}")
    print(f"  👉 http://localhost:{cam_args.port}")
    print(f"  👉 http://<라즈베리파이IP>:{cam_args.port}")
    print(f"{'='*50}")
    print(f"  종료: Ctrl+C\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료")
        server.server_close()


if __name__ == "__main__":
    main()
