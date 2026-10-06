# Copyright 2024 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

#
# [수정] LeKiwi 모바일 베이스 전용 설정
# - top 카메라 제거 (front 1대만 사용)
# - fps 15 → 30 수정
# - connection_time_s 24시간으로 확장
# [2026-07-12 수정] 싱글 카메라(front, index=0, fps=30) 설정
# [2026-10-06 수정] 카메라 완전 제거
#   - 저화질 카메라(LB-3M)의 Corrupt JPEG → ZMQ _cams 디코딩 에러 원인
#   - 카메라는 camera_check.py (포트 8080) 로 별도 운영
#   - lekiwi_host는 모터 제어만 담당
#

from dataclasses import dataclass, field

from lerobot.cameras.configs import CameraConfig

from ..config import RobotConfig


@RobotConfig.register_subclass("lekiwi")
@dataclass
class LeKiwiConfig(RobotConfig):
    port: str = "/dev/ttyACM0"

    disable_torque_on_disconnect: bool = True

    max_relative_target: float | dict[str, float] | None = None

    # [2026-10-06 수정] 카메라 제거 → _cams ZMQ 에러 해결
    # 카메라 영상은 camera_check.py --port 8080 으로 별도 확인
    cameras: dict[str, CameraConfig] = field(default_factory=dict)

    use_degrees: bool = False


@dataclass
class LeKiwiHostConfig:
    port_zmq_cmd: int = 5555
    port_zmq_observations: int = 5556

    connection_time_s: int = 86400
    watchdog_timeout_ms: int = 5000
    max_loop_freq_hz: int = 30


@RobotConfig.register_subclass("lekiwi_client")
@dataclass
class LeKiwiClientConfig(RobotConfig):
    remote_ip: str
    port_zmq_cmd: int = 5555
    port_zmq_observations: int = 5556

    teleop_keys: dict[str, str] = field(
        default_factory=lambda: {
            "forward": "w",
            "backward": "s",
            "left": "a",
            "right": "d",
            "rotate_left": "z",
            "rotate_right": "x",
            "speed_up": "r",
            "speed_down": "f",
            "quit": "q",
        }
    )

    # [2026-10-06 수정] 클라이언트도 카메라 제거
    cameras: dict[str, CameraConfig] = field(default_factory=dict)

    polling_timeout_ms: int = 15
    connect_timeout_s: int = 5
