#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2단계: 기관별 비급여(식재료비 등) 월 추정액 집계

[중요] 같은 항목(예: 상급침실사용료)이 한 기관에 여러 줄 나오는 경우가 흔한데,
이는 중복이 아니라 "선택지"인 경우가 대부부분임 — 예: 1인실 40,000원/일,
2인실 20,000원/일, 다인실 10,000원/일처럼 방 등급별 요금을 전부 공시해 둔 것.
입소자는 그중 하나만 선택하므로, 같은 항목을 전부 더하면 비용이 터무니없이
부풀려진다(실제 발견 사례: 한 기관이 40,000+20,000+10,000+65,000=135,000원/일로
계산될 뻔함 — 실제로는 방 종류에 따라 10,000~65,000원 중 하나만 냄).

그래서 항목별로 "합산"이 아니라 "최저~최고" 범위로 집계한다.
식재료비처럼 기관이 식단 등급(예: 1,000원 2식 vs 4,000원 3식)을 복수 공시한 경우도
동일하게 범위로 처리한다.

API가 주는 nonpayTgtAmt(금액)의 "단위"가 항목 종류마다 다르다는 것도 확인함
(prodBase=산출근거 필드로 교차검증):
  - 식재료비:        금액 = "1식당" 단가. prodBase 예) "1식 4000원 X 3식/일" → 끼니 수(3)를 곱해야 1일 금액.
  - 간식비:           식재료비와 같은 방식일 가능성이 높음(미관측, 추정 처리) → 동일 로직 적용.
  - 상급침실사용료:   금액 = "1일" 정액. prodBase 예) "20000원 (일)" → 그대로 1일 금액.
  - 상급침실사용료(2인실): 위와 동일하게 처리.
  - 경관영양유동식비: 상급침실료처럼 1일 정액일 가능성이 높음(미관측, 추정 처리).
  - 이미용비:         금액 = "1회당" 단가, prodBase 예) "회당 10000원 X 1회/월" → 월 횟수를 곱하면 월 금액.
  - 기타:             단위를 알 수 없음 → 월 1회성 비용으로 가정(보수적으로 가장 단순 처리).

출력: output/facility_nonbenefit_monthly.csv
  longTermAdminSym,
  nonbenefit_monthly_min(원), nonbenefit_monthly_max(원),
  nonbenefit_detail (항목별 '최저~최고' 월 금액 요약 문자열)
"""

import csv
import re
from collections import defaultdict
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"

DAYS_PER_MONTH = 30

DAILY_BASIS_KINDS = {"상급침실사용료", "상급침실사용료(2인실)", "경관영양유동식비"}
MEAL_BASIS_KINDS = {"식재료비", "간식비"}
MONTHLY_COUNT_KINDS = {"이미용비"}


def parse_meals_per_day(prod_base: str, default: int = 3) -> int:
    m = re.search(r"[Xx×]\s*(\d+)\s*식\s*/\s*일", prod_base)
    return int(m.group(1)) if m else default


def parse_count_per_month(prod_base: str, default: int = 1) -> int:
    m = re.search(r"[Xx×]\s*(\d+)\s*회\s*/\s*월", prod_base)
    return int(m.group(1)) if m else default


def monthly_amount(kind_name: str, amount: int, prod_base: str) -> int:
    if kind_name in DAILY_BASIS_KINDS:
        return amount * DAYS_PER_MONTH
    if kind_name in MEAL_BASIS_KINDS:
        meals = parse_meals_per_day(prod_base)
        return amount * meals * DAYS_PER_MONTH
    if kind_name in MONTHLY_COUNT_KINDS:
        count = parse_count_per_month(prod_base)
        return amount * count
    # 기타/미분류: 조회된 금액을 그대로 월 비용으로 취급(보수적 추정)
    return amount


def main():
    nb_path = OUTPUT_DIR / "seoul_all_nonbenefit_fixed.csv"
    if not nb_path.exists():
        nb_path = OUTPUT_DIR / "seoul_all_nonbenefit.csv"  # fetch_longterm_care.py의 기본 출력 파일명
    with open(nb_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    by_facility = defaultdict(list)
    for r in rows:
        by_facility[r["longTermAdminSym"]].append(r)

    out_rows = []
    for sym, items in by_facility.items():
        # 항목 종류별로 월 환산 금액 목록을 모은다 (같은 종류 = 선택지들)
        by_kind_amounts = defaultdict(list)
        for r in items:
            amt_raw = r.get("nonpayTgtAmt", "")
            if not amt_raw.isdigit():
                continue
            amt = int(amt_raw)
            kind = r.get("nonpayKindName", "") or "기타"
            by_kind_amounts[kind].append(monthly_amount(kind, amt, r.get("prodBase", "")))

        total_min = 0
        total_max = 0
        detail_parts = []
        for kind, amounts in sorted(by_kind_amounts.items(), key=lambda x: -max(x[1])):
            lo, hi = min(amounts), max(amounts)
            total_min += lo
            total_max += hi
            if lo == hi:
                detail_parts.append(f"{kind}:{lo:,}원")
            else:
                detail_parts.append(f"{kind}:{lo:,}~{hi:,}원")

        out_rows.append({
            "longTermAdminSym": sym,
            "nonbenefit_monthly_min": total_min,
            "nonbenefit_monthly_max": total_max,
            "nonbenefit_detail": " / ".join(detail_parts),
        })

    fieldnames = ["longTermAdminSym", "nonbenefit_monthly_min", "nonbenefit_monthly_max", "nonbenefit_detail"]
    out_path = OUTPUT_DIR / "facility_nonbenefit_monthly.csv"
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    print(f"기관 {len(out_rows)}곳의 비급여 월 추정액(최저~최고) 계산 완료 -> {out_path}")

    shown = 0
    for r in out_rows:
        if r["longTermAdminSym"] == "11111000135" or (shown < 5 and "상급침실사용료" in r["nonbenefit_detail"]):
            lo, hi = r["nonbenefit_monthly_min"], r["nonbenefit_monthly_max"]
            print(f"  [{r['longTermAdminSym']}] 월 비급여 {lo:,}~{hi:,}원 — {r['nonbenefit_detail']}")
            shown += 1


if __name__ == "__main__":
    main()
