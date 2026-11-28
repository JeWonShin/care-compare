#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
서울 25개 구 장기요양기관 데이터 수집 스크립트 (1단계: 데이터 수집 자동화)

- 공공데이터포털 "국민건강보험공단_장기요양기관 검색 서비스" (B550928) 사용
- 기관목록(검색) → 입소인원 상세조회(정원/현원/빈자리) → 비급여현황 상세조회(식재료비 등)
- 결과를 지역별 CSV 2종(기관 정보 / 비급여 항목) + 통합 CSV로 저장

실행 전 꼭 채워야 할 것:
  SERVICE_KEY: 공공데이터포털 마이페이지 > 활용신청 현황에서 발급받은 "일반 인증키(Decoding)"
  (환경변수 DATA_GO_KR_API_KEY로 넣거나, 아래 SERVICE_KEY에 직접 넣어도 됨)

엔드포인트/파라미터는 사용자가 직접 올려준 "장기요양기관 시설별 상세조회 서비스 활용가이드.docx"로
검증 완료:
  - 검색(기관목록): B550928/searchLtcInsttService02/getLtcInsttSeachList02
    (이 API 자체는 활용가이드에 명세가 없어 siDoCd/siGunGuCd 파라미터명은 추정치 — 틀리면 PARAMS만 수정)
  - 상세조회 계열(B550928/getLtcInsttDetailInfoService02/...): 공통으로
    longTermAdminSym(장기요양기관코드) + adminPttnCd(기관유형코드) 두 개가 필수 파라미터.
    단, 비급여(getNonBenefitSttusDetailInfoList02)는 longTermAdminSym + pageNo + numOfRows만 필요(adminPttnCd 불필요).
"""

import csv
import os
import time
import urllib.request
import urllib.parse
import urllib.error
import http.client
import xml.etree.ElementTree as ET
from pathlib import Path

SERVICE_KEY = os.environ.get("DATA_GO_KR_API_KEY", "")  # 공공데이터포털 인증키

LIST_API_URL = "https://apis.data.go.kr/B550928/searchLtcInsttService02/getLtcInsttSeachList02"
OCCUPANCY_API_URL = "https://apis.data.go.kr/B550928/getLtcInsttDetailInfoService02/getAceptncNmprDetailInfoItem02"
NONBENEFIT_API_URL = "https://apis.data.go.kr/B550928/getLtcInsttDetailInfoService02/getNonBenefitSttusDetailInfoList02"

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# 서울 25개 자치구 시군구코드(법정동코드 앞 5자리, 시도코드 2 + 시군구코드 3)
SEOUL_DISTRICTS = {
    "종로구": "11110",
    "중구": "11140",
    "용산구": "11170",
    "성동구": "11200",
    "광진구": "11215",
    "동대문구": "11230",
    "중랑구": "11260",
    "성북구": "11290",
    "강북구": "11305",
    "도봉구": "11320",
    "노원구": "11350",
    "은평구": "11380",
    "서대문구": "11410",
    "마포구": "11440",
    "양천구": "11470",
    "강서구": "11500",
    "구로구": "11530",
    "금천구": "11545",
    "영등포구": "11560",
    "동작구": "11590",
    "관악구": "11620",
    "서초구": "11650",
    "강남구": "11680",
    "송파구": "11710",
    "강동구": "11740",
}

# 빈자리(vacancy) 계산이 의미 있는 시설 유형 (입소형·주야간보호형)
# A03=노인요양시설, A04=노인요양공동생활가정, B03=주야간보호
CAPACITY_RELEVANT_CODES = {"A03", "A04", "B03"}

# 비급여항목 종류 코드 정의 (활용가이드 "공통항목" 참조)
NONPAY_KIND_NAMES = {
    "1": "식재료비",
    "2": "상급침실사용료",
    "3": "이미용비",
    "4": "경관영양유동식비",
    "5": "간식비",
    "6": "상급침실사용료(2인실)",
    "7": "기타",
}

REQUEST_INTERVAL_SEC = 0.3  # API 호출 간 최소 간격 (과도한 트래픽 방지)


class TrafficExceededError(Exception):
    """해당 오퍼레이션의 일일 트래픽(10,000건) 한도를 초과했을 때 발생."""



# 공공데이터포털 게이트웨이는 가끔 TLS 핸드셰이크 타임아웃·연결 끊김·5xx를 낸다.
# 매일 6천 건 넘게 호출하는 전체 재수집이 일시적 오류 한 번에 통째로 실패하지 않도록,
# 네트워크성 오류와 5xx만 지수 백오프로 재시도한다(4xx·트래픽 초과는 재시도하지 않음).
RETRY_ATTEMPTS = 5
RETRY_BASE_SEC = 2
REQUEST_TIMEOUT_SEC = 30


def _urlopen_with_retry(req):
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == RETRY_ATTEMPTS:
                raise
            reason = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as e:
            if attempt == RETRY_ATTEMPTS:
                raise
            reason = repr(e)
        wait = RETRY_BASE_SEC * 2 ** (attempt - 1)
        print(f"  [재시도 {attempt}/{RETRY_ATTEMPTS - 1}] {reason} — {wait}초 후 다시 시도", flush=True)
        time.sleep(wait)

def call_api(base_url: str, params: dict) -> ET.Element:
    """공공데이터포털 표준 REST API 호출 (XML 응답).

    data.go.kr 게이트웨이는 User-Agent 헤더가 없는 요청(파이썬 기본 urllib 등)을
    403 Forbidden으로 차단하는 경우가 있어, 브라우저처럼 보이는 User-Agent를 넣어 호출한다.
    """
    query = urllib.parse.urlencode(params, safe=",")
    url = f"{base_url}?{query}"
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
        body = _urlopen_with_retry(req)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        if "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR" in err_body:
            raise TrafficExceededError(err_body) from e
        print(f"  [API 에러 응답 본문]\n{err_body}\n")
        raise
    return ET.fromstring(body)


def fetch_region_list(region_cd: str, page_no: int = 1, rows: int = 100):
    """기관목록(검색) API 1페이지 호출.

    region_cd는 5자리(예: 11320 도봉구)를 받아서 siDoCd(앞 2자리)와
    siGunGuCd(뒤 3자리)로 쪼갠다. (활용가이드의 법정동코드 설명: 시도(2)+시군구(3)+...)
    이 검색 API 자체의 요청 파라미터 명세는 활용가이드에 없어 추정치이니,
    여전히 지역 필터가 안 먹으면 이 함수의 params만 고치면 된다.
    """
    si_do_cd = region_cd[:2]
    si_gun_gu_cd = region_cd[2:]
    params = {
        "serviceKey": SERVICE_KEY,
        "pageNo": page_no,
        "numOfRows": rows,
        "siDoCd": si_do_cd,
        "siGunGuCd": si_gun_gu_cd,
    }
    root = call_api(LIST_API_URL, params)
    items = root.findall(".//item")
    total_count = root.findtext(".//totalCount", default="0")
    return items, int(total_count)


def fetch_occupancy(long_term_admin_sym: str, admin_pttn_cd: str):
    """입소인원 상세조회(정원/현원/빈자리). longTermAdminSym + adminPttnCd 둘 다 필수."""
    params = {
        "serviceKey": SERVICE_KEY,
        "longTermAdminSym": long_term_admin_sym,
        "adminPttnCd": admin_pttn_cd,
    }
    root = call_api(OCCUPANCY_API_URL, params)
    items = root.findall(".//item")
    return items[0] if items else None


def fetch_nonbenefit(long_term_admin_sym: str) -> list:
    """비급여현황 상세조회(식재료비 등). 기관당 0~n건의 항목이 올 수 있음."""
    params = {
        "serviceKey": SERVICE_KEY,
        "longTermAdminSym": long_term_admin_sym,
        "pageNo": 1,
        "numOfRows": 20,
    }
    root = call_api(NONBENEFIT_API_URL, params)
    items = root.findall(".//item")
    rows = []
    seen = set()
    for item in items:
        d = xml_item_to_dict(item)
        d["nonpayKindName"] = NONPAY_KIND_NAMES.get(d.get("nonpayKind", ""), "")
        # 같은 기관이 (항목종류, 금액, 산출근거, 등록일)이 완전히 같은 행을
        # 병실/입소자 수만큼 중복 등록해두는 경우가 흔해 (한 사례는 180건 중 실제로는 2종류뿐이었음),
        # 비용 계산기에서 중복 합산되지 않도록 여기서 중복 제거한다.
        key = (d.get("nonpayKind"), d.get("nonpayTgtAmt"), d.get("prodBase"), d.get("uptDt"))
        if key in seen:
            continue
        seen.add(key)
        rows.append(d)
    return rows


def xml_item_to_dict(item: ET.Element) -> dict:
    return {child.tag: (child.text or "").strip() for child in item}


def _to_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def classify_vacancy(row: dict) -> dict:
    """정원/현원 필드로 실제 빈자리 수를 계산하고, 빈자리 로직 적용 가능 여부를 덧붙인다.

    입소인원 조회 API(getAceptncNmprDetailInfoItem02)는 totPer(정원)·maNowPer(현원_남)·
    fmNowPer(현원_여)만 주고 '빈자리'를 직접 주지 않으므로, 여기서 직접 계산한다.
    """
    code = row.get("adminPttnCd", "")
    tot_per_i = _to_int(row.get("totPer"))
    now_sum = _to_int(row.get("maNowPer")) + _to_int(row.get("fmNowPer"))

    row["nowPerSum"] = now_sum
    row["vacancy"] = tot_per_i - now_sum

    if code in CAPACITY_RELEVANT_CODES and tot_per_i > 0:
        row["vacancy_meaningful"] = "Y"
    else:
        # 재가형(방문요양 등)은 정원 개념이 없으므로 빈자리 필터 대상에서 제외
        row["vacancy_meaningful"] = "N"
    return row


def collect_region(region_name: str, region_cd: str, limit: int = None):
    """기관 정보(빈자리 포함) + 비급여 항목, 두 개의 리스트를 반환한다."""
    print(f"[{region_name}({region_cd})] 기관목록 수집 중...", flush=True)
    facility_rows = []
    nonbenefit_rows = []
    page_no = 1
    while True:
        items, total_count = fetch_region_list(region_cd, page_no=page_no)
        if not items:
            break
        print(f"  {page_no}페이지: {len(items)}건 (전체 {total_count}건 중)", flush=True)
        for item in items:
            if limit is not None and len(facility_rows) >= limit:
                print(f"  (테스트 제한 {limit}건 도달 — 중단)", flush=True)
                return facility_rows, nonbenefit_rows
            base = xml_item_to_dict(item)
            sym = base.get("longTermAdminSym")
            pttn_cd = base.get("adminPttnCd")
            name = base.get("adminNm", "")
            print(f"  [{len(facility_rows) + 1}] {name} ({pttn_cd}) 상세조회 중...", flush=True)

            occ = {}
            if sym and pttn_cd:
                time.sleep(REQUEST_INTERVAL_SEC)
                occ_item = fetch_occupancy(sym, pttn_cd)
                if occ_item is not None:
                    occ = xml_item_to_dict(occ_item)

            merged = {**base, **occ}
            merged["regionName"] = region_name
            merged = classify_vacancy(merged)
            facility_rows.append(merged)

            if sym:
                time.sleep(REQUEST_INTERVAL_SEC)
                nb_items = fetch_nonbenefit(sym)
                for nb in nb_items:
                    nb["adminNm"] = name
                    nb["regionName"] = region_name
                    nonbenefit_rows.append(nb)

        if page_no * 100 >= total_count:
            break
        page_no += 1
        time.sleep(REQUEST_INTERVAL_SEC)
    print(f"  -> 기관 {len(facility_rows)}건, 비급여 항목 {len(nonbenefit_rows)}건 수집 완료")
    return facility_rows, nonbenefit_rows


def save_csv(rows: list, path: Path):
    if not rows:
        return
    fieldnames = sorted({k for row in rows for k in row.keys()})
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_csv(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def merge_saved_region_files(suffix: str = "") -> list:
    """이미 디스크에 저장된 구별 CSV들을 전부 읽어 합친다.

    suffix="" 면 기관 CSV(11320_도봉구.csv)들을, suffix="_nonbenefit" 면
    비급여 CSV(11320_도봉구_nonbenefit.csv)들을 모은다.
    """
    merged = []
    for region_name, region_cd in SEOUL_DISTRICTS.items():
        path = OUTPUT_DIR / f"{region_cd}_{region_name}{suffix}.csv"
        merged.extend(load_csv(path))
    return merged


def main():
    import sys

    if not SERVICE_KEY:
        print(
            "SERVICE_KEY가 비어 있습니다.\n"
            "DATA_GO_KR_API_KEY 환경변수로 넣거나 파일 상단 SERVICE_KEY에 직접 넣고 다시 실행해 주세요."
        )
        return

    # 테스트 모드: python fetch_longterm_care.py --test
    # 도봉구 10건만 호출해서, API가 정상 동작하는지(지역 필터·비급여 포함) 빠르게 확인
    # 전체 검증이 필요하면: python fetch_longterm_care.py --test --full
    if "--test" in sys.argv:
        test_limit = None if "--full" in sys.argv else 10
        facility_rows, nonbenefit_rows = collect_region(
            "도봉구", SEOUL_DISTRICTS["도봉구"], limit=test_limit
        )
        save_csv(facility_rows, OUTPUT_DIR / "test_dobong.csv")
        save_csv(nonbenefit_rows, OUTPUT_DIR / "test_dobong_nonbenefit.csv")
        print(f"\n테스트 완료: 기관 {len(facility_rows)}건 -> {OUTPUT_DIR / 'test_dobong.csv'}")
        print(f"            비급여 {len(nonbenefit_rows)}건 -> {OUTPUT_DIR / 'test_dobong_nonbenefit.csv'}")
        print("이 파일을 기존에 가지고 계신 dobong.csv / dobong_detail.csv와 건수·값을 비교해 보세요.")
        print("특히 regionName이 전부 '도봉구'로만 나오는지 확인 — 다른 구 이름이 섞여 있으면 지역 필터가 아직 안 먹는 것.")
        return

    # 이미 완료된 구는 건너뛴다 (중간에 트래픽 한도로 중단됐다가 다음날 재실행하는 경우 대비)
    for region_name, region_cd in SEOUL_DISTRICTS.items():
        facility_path = OUTPUT_DIR / f"{region_cd}_{region_name}.csv"
        if facility_path.exists():
            print(f"[{region_name}({region_cd})] 이미 수집된 파일이 있어 건너뜀 -> {facility_path.name}")
            continue
        try:
            facility_rows, nonbenefit_rows = collect_region(region_name, region_cd)
        except TrafficExceededError:
            print(
                f"\n[{region_name}] 처리 중 일일 트래픽 한도(10,000건)를 초과했습니다.\n"
                "여기까지 수집된 구는 이미 디스크에 저장되어 있으니 안전합니다.\n"
                "내일 같은 명령으로 다시 실행하면, 이미 끝난 구는 건너뛰고 이어서 수집합니다."
            )
            break
        save_csv(facility_rows, facility_path)
        save_csv(nonbenefit_rows, OUTPUT_DIR / f"{region_cd}_{region_name}_nonbenefit.csv")

    # 통합 파일은 디스크에 저장된 구별 결과를 다시 읽어 합친다 (중간에 중단됐어도 그때까지 결과로 통합본 생성)
    all_facility_rows = merge_saved_region_files()
    all_nonbenefit_rows = merge_saved_region_files("_nonbenefit")
    save_csv(all_facility_rows, OUTPUT_DIR / "seoul_all.csv")
    save_csv(all_nonbenefit_rows, OUTPUT_DIR / "seoul_all_nonbenefit.csv")
    print(f"\n지금까지 통합 기관 {len(all_facility_rows)}건 -> {OUTPUT_DIR / 'seoul_all.csv'}")
    print(f"지금까지 통합 비급여 {len(all_nonbenefit_rows)}건 -> {OUTPUT_DIR / 'seoul_all_nonbenefit.csv'}")


if __name__ == "__main__":
    main()
