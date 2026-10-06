#!/usr/bin/env python3
# identify_wheels.py - LeKiwi 바퀴 모터 ID ↔ 실제 바퀴 위치(좌전/후/우전) 매칭 도구
# 2026-09-21 최초 작성: lekiwi.py(베이스 전용)가 참조하는 누락 스크립트 보완
#
# 왜 필요한가?
#   lerobot-setup-motors 로 ID(7,8,9)를 넣어도, 어느 ID가 어느 바퀴에 붙었는지는
#   조립한 사람만 압니다. 이 스크립트는 ID를 하나씩 천천히 돌려 보고,
#   "지금 돈 바퀴가 어디냐"를 물어서 lekiwi.py 상단 상수를 자동으로 만들어 줍니다.
#
# 사용법 (라즈베리파이5, 로봇 바퀴를 받침 위에 띄운 상태):
#   conda activate lerobot
#   python3 identify_wheels.py              # 기본: ID 1~12 스캔
#   python3 identify_wheels.py --ids 7 8 9  # 특정 ID만 확인
#   python3 identify_wheels.py --port /dev/ttyACM0
#
# 주의:
#   - lekiwi_host 가 실행 중이면 포트를 점유하므로 먼저 Ctrl+C 로 종료하세요.
#   - 저속(raw 300) 1.5초만 회전합니다. 그래도 바퀴는 반드시 띄워 두세요.

import argparse
import os
import sys
import time

DEFAULT_PORT = "/dev/ttyACM0"
SPIN_RAW = 300          # 저속 회전값 (check_wheels.py 의 SPIN_SPEED 보다 약간 느리게)
SPIN_SEC = 1.5          # 회전 시간(초)

POSITIONS = {
    "1": ("WHEEL_ID_LEFT", "좌전(왼쪽 앞) 바퀴"),
    "2": ("WHEEL_ID_BACK", "후방(뒤) 바퀴"),
    "3": ("WHEEL_ID_RIGHT", "우전(오른쪽 앞) 바퀴"),
}


def header(title):
    print("\n" + "=" * 55)
    print(f"  {title}")
    print("=" * 55)


def open_bus(port, candidate_ids):
    try:
        from lerobot.motors import Motor, MotorNormMode
        from lerobot.motors.feetech import FeetechMotorsBus
    except ImportError as e:
        print(f"❌ LeRobot import 실패: {e}\n   → conda activate lerobot 후 다시 실행하세요.")
        sys.exit(1)

    motors = {f"m{i}": Motor(i, "sts3215", MotorNormMode.RANGE_M100_100) for i in candidate_ids}
    bus = FeetechMotorsBus(port=port, motors=motors)
    try:
        # 일부 ID가 없어도 연결되도록 handshake 생략 (버전에 따라 인자 미지원 시 기본 연결)
        bus.connect(handshake=False)
    except TypeError:
        bus.connect()
    return bus


def scan(bus, candidate_ids):
    header("1단계: 모터 ID 스캔")
    found = []
    for i in candidate_ids:
        try:
            if bus.ping(i) is not None:
                found.append(i)
                print(f"  ✅ ID {i} 응답")
        except Exception:
            pass
    if not found:
        print("  ❌ 응답하는 모터가 없습니다.")
        print("     ① 12V 전원  ② USB 케이블  ③ 데이지체인 케이블  ④ 다른 프로그램의 포트 점유 확인")
    return found


def spin(bus, mid, raw):
    key = f"m{mid}"
    bus.write("Torque_Enable", key, 0)
    bus.write("Operating_Mode", key, 1)   # 1 = 속도(바퀴) 모드
    bus.write("Torque_Enable", key, 1)
    bus.write("Goal_Velocity", key, raw)
    time.sleep(SPIN_SEC)
    bus.write("Goal_Velocity", key, 0)
    bus.write("Torque_Enable", key, 0)


def main():
    ap = argparse.ArgumentParser(description="LeKiwi 바퀴 ID ↔ 위치 매칭")
    ap.add_argument("--port", default=DEFAULT_PORT)
    ap.add_argument("--ids", type=int, nargs="+", default=list(range(1, 13)))
    args = ap.parse_args()

    if not os.path.exists(args.port):
        print(f"❌ 포트 없음: {args.port}  → lerobot-find-port 로 포트를 먼저 확인하세요.")
        sys.exit(1)

    bus = open_bus(args.port, args.ids)
    result = {}
    try:
        found = scan(bus, args.ids)
        if not found:
            sys.exit(1)

        header("2단계: 바퀴 하나씩 돌려보기")
        print("  ⚠️  바퀴를 받침 위에 띄웠는지 확인하세요.")
        for mid in found:
            while True:
                input(f"\n  ▶ ID {mid} 를 {SPIN_SEC}초 돌립니다. Enter...")
                spin(bus, mid, SPIN_RAW)
                ans = input("  방금 돈 바퀴는? [1] 좌전  [2] 후방  [3] 우전  [r] 다시  [s] 건너뛰기 : ").strip().lower()
                if ans == "r":
                    continue
                if ans in POSITIONS:
                    name, desc = POSITIONS[ans]
                    if name in result:
                        print(f"  ⚠️  {desc} 는 이미 ID {result[name]} 로 지정됨 → 덮어씁니다.")
                    result[name] = mid
                break
    finally:
        try:
            bus.disconnect()
        except Exception:
            pass

    header("3단계: 결과 — lekiwi.py 상단에 붙여넣기")
    for name, _ in POSITIONS.values():
        print(f"  {name:<15}= {result.get(name, '???')}")
    missing = [d for n, d in POSITIONS.values() if n not in result]
    if missing:
        print(f"\n  ❌ 아직 매칭 안 된 바퀴: {', '.join(missing)}")
    else:
        print("\n  ✅ 3개 바퀴 매칭 완료! lekiwi.py 의 WHEEL_ID_* 값을 위와 같게 맞추세요.")
        print("     다음 단계: python3 check_wheels.py --move  (전후좌우 방향 확인)")


if __name__ == "__main__":
    main()
