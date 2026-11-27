#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
추가 수집: 기관 일반현황(주소·전화번호) — getGeneralSttusDetailInfoItem02

이미 받아둔 seoul_all_fixed.csv(또는 seoul_all.csv)에 있는 기관코드(longTermAdminSym)만
가지고 주소·전화번호를 추가로 조회한다. 지역 검색 API를 다시 부르지 않으므로
서울 전체를 재수집할 필요가 없고, 트래픽도 기관당 1콜만 추가로 쓴다.

활용가이드로 확인한 스펙:
  엔드포인트: B550928/getLtcInsttDetailInfoService02/getGeneralSttusDetailInfoItem02
  필수 파라미터: longTermAdminSym + adminPttnCd (입소인원 조회와 동일 패턴)
  응답 필드 중 필요한 것: adminAddr(주소), locTelNo_1/2/3(전화번호, 하이픈으로 조합해야 함)

실행 전 채울 것: fetch_longterm_care.py와 동일하게 DATA_GO_KR_API_KEY 환경변수.

사용법:
  python3 fetch_general_status.py            # 서울 전체 1,020곳(입소형·주야간보호형) 대상, 이어서 수집 가능
  python3 fetch_general_status.py --test     # 10건만 테스트
"""

import csv
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

SERVICE_KEY = os.environ.get("DATA_GO_KR_API_KEY", "")

GENERAL_API_URL = "https://apis.data.go.kr/B550928/getLtcInsttDetailInfoService02/getGeneralSttusDetailInfoItem02"

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

SOURCE_CSV = OUTPUT_DIR / "seoul_all_fixed.csv"   # vacancy 보정판(또는 seoul_all.csv도 가능)
PROGRESS_CSV = OUTPUT_DIR / "general_status.csv"  # 이어서 수집 시 이미 있는 기관은 건너뜀

REQUEST_INTERVAL_SEC = 0.3

# 빈자리 계산이 의미 있는(=이 사이트에서 실제로 쓰는) 시설 유형만 조회 대상으로 삼는다.
CAPACITY_RELEVANT_CODES = {"A03", "A04", "B03"}


class TrafficExceededError(Exception):
    pass


def call_api(params: dict) -> ET.Element:
    query = urllib.parse.urlencode(params, safe=",")
    url = f"{GENERAL_API_URL}?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        if "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR" in err_body:
            raise TrafficExceededError(err_body) from e
        print(f"  [API 에러 응답 본문]\n{err_body}\n")
        raise
    return ET.fromstring(body)


def xml_item_to_dict(item: ET.Element) -> dict:
    return {child.tag: (child.text or "").strip() for child in item}


def fetch_general_status(sym: str, admin_pttn_cd: str):
    params = {
        "serviceKey": SERVICE_KEY,
        "longTermAdminSym": sym,
        "adminPttnCd": admin_pttn_cd,
    }
    root = call_api(params)
    items = root.findall(".//item")
    if not items:
        return None
    d = xml_item_to_dict(items[0])
    tel_parts = [d.get("locTelNo_1", ""), d.get("locTelNo_2", ""), d.get("locTelNo_3", "")]
    tel = "-".join(p for p in tel_parts if p)
    return {
        "longTermAdminSym": sym,
        "adminAddr": d.get("adminAddr", ""),
        "tel": tel,
    }


def load_done_syms():
    if not PROGRESS_CSV.exists():
        return {}
    with open(PROGRESS_CSV, newline="", encoding="utf-8-sig") as f:
        return {row["longTermAdminSym"]: row for row in csv.DictReader(f)}


def save_all(rows_by_sym: dict):
    fieldnames = ["longTermAdminSym", "adminAddr", "tel"]
    with open(PROGRESS_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_by_sym.values())


def main():
    if not SERVICE_KEY:
        print("SERVICE_KEY가 비어 있습니다. DATA_GO_KR_API_KEY 환경변수를 설정하고 다시 실행해 주세요.")
        return

    if not SOURCE_CSV.exists():
        print(f"{SOURCE_CSV} 가 없습니다. 먼저 fetch_longterm_care.py로 기관 목록을 수집해 주세요.")
        return

    with open(SOURCE_CSV, newline="", encoding="utf-8-sig") as f:
        facilities = list(csv.DictReader(f))

    targets = [
        f for f in facilities
        if f.get("adminPttnCd") in CAPACITY_RELEVANT_CODES and f.get("longTermAdminSym")
    ]
    # 같은 기관이 여러 급여유형으로 중복 등록된 경우가 있어 longTermAdminSym 기준으로 중복 제거
    seen_syms = set()
    unique_targets = []
    for f in targets:
        sym = f["longTermAdminSym"]
        if sym in seen_syms:
            continue
        seen_syms.add(sym)
        unique_targets.append(f)

    done = load_done_syms()
    print(f"대상 {len(unique_targets)}곳 중 이미 수집됨 {len(done)}곳 — 나머지 이어서 수집합니다.")

    test_limit = 10 if "--test" in sys.argv else None
    processed = 0
    for f in unique_targets:
        sym = f["longTermAdminSym"]
        if sym in done:
            continue
        if test_limit is not None and processed >= test_limit:
            print(f"(테스트 제한 {test_limit}건 도달 — 중단)")
            break
        name = f.get("adminNm", "")
        print(f"[{processed + 1}] {name} ({sym}) 주소·전화 조회 중...", flush=True)
        try:
            info = fetch_general_status(sym, f["adminPttnCd"])
        except TrafficExceededError:
            print("\n일일 트래픽 한도를 초과했습니다. 지금까지 수집된 내용은 저장되어 있으니, 내일 같은 명령으로 다시 실행하면 이어서 수집합니다.")
            save_all(done)
            return
        if info:
            done[sym] = info
        processed += 1
        time.sleep(REQUEST_INTERVAL_SEC)
        if processed % 50 == 0:
            save_all(done)  # 중간 저장

    save_all(done)
    print(f"\n완료: 총 {len(done)}곳의 주소·전화번호 -> {PROGRESS_CSV}")


if __name__ == "__main__":
    main()
