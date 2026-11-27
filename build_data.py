#!/usr/bin/env python3
"""
수집된 CSV들을 합쳐 site/data.json을 재생성하는 스크립트.

입력 (output/ 폴더, 모두 fetch_*.py / aggregate_nonbenefit.py 산출물):
  - seoul_all_fixed.csv              : 기관목록+입소인원(빈자리) — fetch_longterm_care.py
  - seoul_all_nonbenefit_fixed.csv   : 비급여 원본(중복제거 전 등록일 포함) — fetch_longterm_care.py
  - facility_nonbenefit_monthly.csv  : 비급여 월 최저~최고 범위 — aggregate_nonbenefit.py
  - general_status.csv               : 주소·전화번호 — fetch_general_status.py

출력:
  - site/data.json : generate_site.py가 바로 읽는 최종 포맷
      [{sym,name,region,type,cap,now,vac,nbMin,nbMax,addr,tel,nbDate}, ...]

대상 범위는 입소형·주야간보호형(A03/A04/B03)만 — 방문요양 등 재가서비스는 "정원" 개념이
없어 빈자리 로직이 성립하지 않으므로 처음부터 제외한다 (2026-11-26 조사로 확정된 범위).
"""
import csv
import json
from pathlib import Path

BASE = Path(__file__).parent
OUT = BASE / "output"
TARGET_TYPES = {"A03", "A04", "B03"}


def read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def first_existing(*candidates):
    """후보 경로 중 실제 존재하는 첫 파일을 반환 (fetch 스크립트가 바로 만든 seoul_all.csv와,
    과거 세션에서 지역필터 버그를 고치고 수동으로 남겨둔 seoul_all_fixed.csv 둘 다 호환)."""
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(f"None of these exist: {candidates}")


def build():
    facilities_path = first_existing(OUT / "seoul_all_fixed.csv", OUT / "seoul_all.csv")
    facilities = read_csv(facilities_path)
    nonbenefit_summary = {r["longTermAdminSym"]: r for r in read_csv(OUT / "facility_nonbenefit_monthly.csv")}

    general_status_path = OUT / "general_status.csv"
    general_status = {r["longTermAdminSym"]: r for r in read_csv(general_status_path)} if general_status_path.exists() else {}

    # 기관별 비급여 최신 등록일(uptDt) — YYYYMMDD 중 최댓값을 "YYYY.MM"으로
    nb_dates = {}
    nb_raw_path = first_existing(OUT / "seoul_all_nonbenefit_fixed.csv", OUT / "seoul_all_nonbenefit.csv")
    if nb_raw_path.exists():
        for r in read_csv(nb_raw_path):
            sym = r["longTermAdminSym"]
            upt = r.get("uptDt", "")
            if upt and (sym not in nb_dates or upt > nb_dates[sym]):
                nb_dates[sym] = upt

    result = []
    skipped_no_vacancy_data = 0
    for row in facilities:
        if row["adminPttnCd"] not in TARGET_TYPES:
            continue
        sym = row["longTermAdminSym"]

        if row.get("vacancy_meaningful") != "Y":
            skipped_no_vacancy_data += 1
            # 정원 데이터가 없어도 기관 자체는 목록에 포함 (빈자리 0/모름으로 표기)

        nb = nonbenefit_summary.get(sym)
        nb_min = int(nb["nonbenefit_monthly_min"]) if nb and nb.get("nonbenefit_monthly_min") else 0
        nb_max = int(nb["nonbenefit_monthly_max"]) if nb and nb.get("nonbenefit_monthly_max") else 0

        gs = general_status.get(sym)
        addr = gs["adminAddr"] if gs and gs.get("adminAddr") else ""
        tel = gs["tel"] if gs and gs.get("tel") else ""

        raw_date = nb_dates.get(sym, "")
        nb_date = f"{raw_date[:4]}.{raw_date[4:6]}" if len(raw_date) >= 6 else ""

        try:
            cap = int(row["totPer"])
        except (ValueError, KeyError):
            cap = 0
        try:
            now = int(row["nowPerSum"])
        except (ValueError, KeyError):
            now = 0
        try:
            vac = int(row["vacancy"])
        except (ValueError, KeyError):
            vac = 0

        result.append({
            "sym": sym,
            "name": row["adminNm"],
            "region": row["regionName"],
            "type": row["adminPttnCd"],
            "cap": cap,
            "now": now,
            "vac": vac,
            "nbMin": nb_min,
            "nbMax": nb_max,
            "addr": addr,
            "tel": tel,
            "nbDate": nb_date,
        })

    site_dir = BASE / "site"
    site_dir.mkdir(exist_ok=True)
    (site_dir / "data.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

    print(f"site/data.json 생성 완료: {len(result)}곳 (정원 데이터 없음 {skipped_no_vacancy_data}곳 포함)")
    with_addr = sum(1 for d in result if d["addr"])
    with_nb = sum(1 for d in result if d["nbMin"] or d["nbMax"])
    print(f"  주소·전화 보유: {with_addr}/{len(result)} ({with_addr*100//len(result)}%)")
    print(f"  비급여 데이터 보유: {with_nb}/{len(result)} ({with_nb*100//len(result)}%)")


if __name__ == "__main__":
    build()
