# LeKiwi 키보드 제어 + 카메라 뷰어 통합 도구
# [2026-07-12 생성]
# - NUC에서 키보드로 LeKiwi 베이스 제어
# - 브라우저에서 카메라 영상 동시 확인
# - 카메라: 라즈베리파이의 camera_check.py에서 MJPEG 스트림 수신
#
# 실행 순서:
#   [Pi]  python -m lerobot.robots.lekiwi.lekiwi_host --robot.id=my_lekiwi ...
#   [Pi]  python camera_check.py --front 0  (포트 5555)
#   [NUC] python teleoperate_with_camera.py --pi-ip 192.168.0.41
#
# 브라우저: http://localhost:8765
"""
LeKiwi 키보드 제어 + 카메라 뷰어
==================================
W/A/S/D     : 전진 / 좌이동 / 후진 / 우이동
Z/X         : 좌회전 / 우회전
R/F         : 속도 증가 / 감소
Ctrl+C      : 종료

브라우저: http://localhost:8765
"""

import argparse
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

from lerobot.robots.lekiwi import LeKiwiClient, LeKiwiClientConfig
from lerobot.teleoperators.keyboard.teleop_keyboard import (
    KeyboardTeleop,
    KeyboardTeleopConfig,
)

# ── 전역 상태 ─────────────────────────────────────────────
robot_state = {
    "connected": False,
    "action":    {},
    "speed":     "보통",
    "error":     "",
}
state_lock = threading.Lock()


# ── HTML 대시보드 ─────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🤖 LeKiwi 제어 대시보드</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Noto Sans KR', sans-serif;
    background: #0F172A; color: #E2E8F0;
    display: flex; flex-direction: column; align-items: center;
    min-height: 100vh; padding: 1.5rem; gap: 1rem;
  }
  h1 { font-size: 1.4rem; font-weight: 800; }
  .grid { display: flex; gap: 1rem; flex-wrap: wrap; justify-content: center; width: 100%; max-width: 1100px; }

  /* 카메라 */
  .cam-box { flex: 1; min-width: 300px; max-width: 640px; }
  .cam-label {
    background: #1E293B; border-radius: 10px 10px 0 0;
    padding: .6rem 1rem; font-weight: 700; font-size: .9rem;
    display: flex; justify-content: space-between; align-items: center;
  }
  .tag { background: #2563EB; padding: .15rem .6rem; border-radius: 999px; font-size: .75rem; }
  .cam-inner { background: #1E293B; border-radius: 0 0 10px 10px; padding: 4px; padding-top: 0; }
  .cam-stream { display: block; width: 100%; height: auto; border-radius: 0 0 8px 8px; }

  /* 제어 패널 */
  .ctrl-panel {
    flex: 0 0 280px; background: #1E293B; border-radius: 12px;
    padding: 1.25rem; display: flex; flex-direction: column; gap: 1rem;
  }
  .ctrl-title { font-weight: 700; font-size: 1rem; border-bottom: 1px solid #334155; padding-bottom: .5rem; }

  /* 방향 패드 */
  .dpad { display: grid; grid-template-columns: repeat(3, 52px); gap: 6px; margin: 0 auto; }
  .dpad-btn {
    width: 52px; height: 52px; background: #334155; border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.3rem; font-weight: 700; border: 2px solid #475569;
    transition: all .1s;
  }
  .dpad-btn.active { background: #2563EB; border-color: #60A5FA; transform: scale(.95); }
  .dpad-btn.empty  { background: transparent; border: none; }

  /* 상태 */
  .status-row { display: flex; justify-content: space-between; font-size: .85rem; padding: .3rem 0; border-bottom: 1px solid #1E293B; }
  .label { color: #94A3B8; }
  .value { color: #38BDF8; font-weight: 700; font-family: monospace; }
  .ok  { color: #4ADE80; }
  .err { color: #F87171; }

  /* 키 가이드 */
  .key-guide { font-size: .8rem; color: #64748B; line-height: 1.8; }
  kbd {
    background: #334155; border: 1px solid #475569; border-radius: 4px;
    padding: .1rem .4rem; font-size: .78rem; color: #E2E8F0;
  }
</style>
</head>
<body>
  <h1>🤖 LeKiwi 제어 대시보드</h1>

  <div class="grid">
    <!-- 카메라 -->
    <div class="cam-box">
      <div class="cam-label">
        <span>Front Camera</span>
        <span class="tag" id="cam-tag">연결 중...</span>
      </div>
      <div class="cam-inner">
        <img id="cam-stream" class="cam-stream"
             src="CAM_STREAM_URL"
             width="640" height="480"
             onerror="this.src='CAM_STREAM_URL?' + Date.now()">
      </div>
    </div>

    <!-- 제어 패널 -->
    <div class="ctrl-panel">
      <div class="ctrl-title">🎮 제어 상태</div>

      <!-- 방향 패드 -->
      <div class="dpad">
        <div class="dpad-btn empty"></div>
        <div class="dpad-btn" id="btn-w">▲</div>
        <div class="dpad-btn empty"></div>
        <div class="dpad-btn" id="btn-a">◀</div>
        <div class="dpad-btn" id="btn-s">▼</div>
        <div class="dpad-btn" id="btn-d">▶</div>
        <div class="dpad-btn" id="btn-z">↺</div>
        <div class="dpad-btn empty"></div>
        <div class="dpad-btn" id="btn-x">↻</div>
      </div>

      <!-- 상태 정보 -->
      <div>
        <div class="status-row">
          <span class="label">로봇 연결</span>
          <span class="value" id="st-robot">확인 중...</span>
        </div>
        <div class="status-row">
          <span class="label">속도</span>
          <span class="value" id="st-speed">-</span>
        </div>
        <div class="status-row">
          <span class="label">x.vel</span>
          <span class="value" id="st-xvel">0.00</span>
        </div>
        <div class="status-row">
          <span class="label">y.vel</span>
          <span class="value" id="st-yvel">0.00</span>
        </div>
        <div class="status-row">
          <span class="label">θ.vel</span>
          <span class="value" id="st-tvel">0.00</span>
        </div>
      </div>

      <!-- 키 가이드 -->
      <div class="key-guide">
        <kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd> 이동<br>
        <kbd>Z</kbd><kbd>X</kbd> 좌/우 회전<br>
        <kbd>R</kbd><kbd>F</kbd> 속도 ▲▼<br>
        <kbd>Ctrl+C</kbd> 종료
      </div>
    </div>
  </div>

  <script>
    const KEY_BTN = { w:'btn-w', a:'btn-a', s:'btn-s', d:'btn-d', z:'btn-z', x:'btn-x' };

    // 방향 패드 키 이벤트
    document.addEventListener('keydown', e => {
      const id = KEY_BTN[e.key.toLowerCase()];
      if (id) document.getElementById(id)?.classList.add('active');
    });
    document.addEventListener('keyup', e => {
      const id = KEY_BTN[e.key.toLowerCase()];
      if (id) document.getElementById(id)?.classList.remove('active');
    });

    // 카메라 오류 재연결
    const cam = document.getElementById('cam-stream');
    cam.addEventListener('error', () => {
      document.getElementById('cam-tag').textContent = '재연결 중...';
      setTimeout(() => { cam.src = cam.src.split('?')[0] + '?' + Date.now(); }, 3000);
    });
    cam.addEventListener('load', () => {
      document.getElementById('cam-tag').textContent = '🟢 수신 중';
    });

    // 상태 폴링
    setInterval(async () => {
      try {
        const res = await fetch('/state');
        const d = await res.json();
        document.getElementById('st-robot').innerHTML =
          d.connected ? '<span class="ok">✅ 연결됨</span>'
                      : '<span class="err">❌ 미연결</span>';
        document.getElementById('st-speed').textContent = d.speed || '-';
        document.getElementById('st-xvel').textContent =
          (d.action?.['x.vel'] ?? 0).toFixed(3);
        document.getElementById('st-yvel').textContent =
          (d.action?.['y.vel'] ?? 0).toFixed(3);
        document.getElementById('st-tvel').textContent =
          (d.action?.['theta.vel'] ?? 0).toFixed(3);
      } catch (e) {}
    }, 300);
  </script>
</body>
</html>"""


# ── HTTP 서버 ─────────────────────────────────────────────
class DashboardHandler(BaseHTTPRequestHandler):

    def __init__(self, *args, pi_ip="localhost", cam_port=8080, **kwargs):
        self.pi_ip   = pi_ip
        self.cam_port = cam_port
        super().__init__(*args, **kwargs)

    def do_GET(self):
        if self.path == '/':
            self._serve_html()
        elif self.path == '/state':
            self._serve_state()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_html(self):
        cam_url = f"http://{self.pi_ip}:{self.cam_port}/stream/front"
        page = HTML.replace("CAM_STREAM_URL", cam_url)

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(page.encode())

    def _serve_state(self):
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            with state_lock:
                self.wfile.write(json.dumps(robot_state).encode())
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt, *args):
        pass  # 로그 억제


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def make_handler(pi_ip, cam_port):
    def handler(*args, **kwargs):
        DashboardHandler(*args, pi_ip=pi_ip, cam_port=cam_port, **kwargs)
    return handler


# ── 키보드 제어 루프 ──────────────────────────────────────
def teleop_loop(robot, teleop_keyboard, dash_port):
    print(f"\n{'='*55}")
    print(f"  🤖 LeKiwi 키보드 제어 시작!")
    print(f"  👉 브라우저: http://localhost:{dash_port}")
    print(f"  종료: Ctrl+C")
    print(f"{'='*55}\n")

    with state_lock:
        robot_state["connected"] = True

    try:
        while True:
            # [2026-10-06 수정] get_observation() 제거
            # - 키보드 제어에 observation 불필요
            # - _cams 로깅 에러의 직접 원인이었음

            # 키보드 → 액션 변환
            keyboard_keys = teleop_keyboard.get_action()
            base_action   = robot._from_keyboard_to_base_action(keyboard_keys)

            # 로봇에 전송
            robot.send_action(base_action)

            # 대시보드 상태 업데이트
            with state_lock:
                robot_state["action"] = {
                    k: float(v) for k, v in base_action.items()
                    if k in ("x.vel", "y.vel", "theta.vel")
                }

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n🛑 사용자 종료")
    finally:
        with state_lock:
            robot_state["connected"] = False


# ── 메인 ─────────────────────────────────────────────────
def main():
    # [2026-10-06 수정] _cams 관련 에러 로그 완전 억제
    logging.getLogger().setLevel(logging.CRITICAL)

    parser = argparse.ArgumentParser(description="LeKiwi 키보드 제어 + 카메라 뷰어")
    parser.add_argument("--pi-ip",   type=str, default="192.168.0.41",
                        help="라즈베리파이 IP (기본: 192.168.0.41)")
    parser.add_argument("--cam-port",type=int, default=8080,
                        help="camera_check.py 포트 (기본: 8080) ※ 5555는 ZMQ와 충돌!")
    parser.add_argument("--robot-id",type=str, default="my_lekiwi",
                        help="로봇 ID (기본: my_lekiwi)")
    parser.add_argument("--dash-port",type=int, default=8765,
                        help="대시보드 포트 (기본: 8765)")
    args = parser.parse_args()

    # ── 로봇 연결 ──
    robot_config = LeKiwiClientConfig(
        remote_ip=args.pi_ip,
        id=args.robot_id,
        connect_timeout_s=30,
    )
    keyboard_config = KeyboardTeleopConfig(id="my_keyboard")

    robot    = LeKiwiClient(robot_config)
    teleop   = KeyboardTeleop(keyboard_config)

    print(f"⏳ {args.pi_ip} 연결 중...")
    robot.connect()
    teleop.connect()
    print("✅ 로봇 연결 성공!")

    # ── HTTP 대시보드 서버 (백그라운드) ──
    server = ThreadingHTTPServer(
        ('0.0.0.0', args.dash_port),
        make_handler(args.pi_ip, args.cam_port)
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"🌐 대시보드: http://localhost:{args.dash_port}")
    print(f"📷 카메라:   http://{args.pi_ip}:{args.cam_port}")

    # ── 제어 루프 ──
    try:
        teleop_loop(robot, teleop, args.dash_port)
    finally:
        teleop.disconnect()
        robot.disconnect()
        server.shutdown()
        print("🔌 종료 완료")


if __name__ == "__main__":
    main()
