#!/usr/bin/env python3
"""수집 진입점 — 실제 수집은 같은 폴더의 fetch_espn.py가 한다.

예전에는 네이버 스포츠 API(api-gw.sports.naver.com)를 직접 불렀는데,
해외 데이터센터 IP를 막아 GitHub Actions에서 매번 Read timeout(약 264초)으로
끝났고 data/도 갱신되지 않았다. 그래서 수집기를 ESPN 공개 API 기반
fetch_espn.py로 바꾸고, 워크플로(.github/workflows/update-sports.yml)는
그대로 `python3 scripts/fetch_sports.py`를 부르도록 이 파일만 얇게 남긴다.

옛 네이버 구현은 scripts/fetch_naver.py에 그대로 남겨 두었다(참고·복구용).
"""
from __future__ import annotations

import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "fetch_espn.py")

if __name__ == "__main__":
    sys.argv[0] = TARGET
    runpy.run_path(TARGET, run_name="__main__")
