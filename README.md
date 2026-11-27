# 서울 요양원·주야간보호 비교 사이트

공공데이터포털(국민건강보험공단 B550928) 데이터를 기반으로 서울 25개 구의 노인요양시설·
노인요양공동생활가정·주야간보호센터의 실시간 빈자리와 등급·본인부담 유형별 예상 월 비용을
자동으로 계산해 보여주는 정적 사이트.

## 파이프라인

```
fetch_longterm_care.py   # 기관목록 + 입소인원(빈자리) + 비급여 원본 수집 (API)
      ↓ output/seoul_all_fixed.csv, output/seoul_all_nonbenefit_fixed.csv
fetch_general_status.py  # 주소·전화번호 수집 (API, 증분)
      ↓ output/general_status.csv
aggregate_nonbenefit.py  # 비급여 항목을 "최저~최고" 월 범위로 집계
      ↓ output/facility_nonbenefit_monthly.csv
build_data.py             # 위 CSV들을 합쳐 site/data.json 생성
      ↓ site/data.json
generate_site.py          # 구별 정적 페이지 25개 + 홈 + sitemap.xml 생성
      ↓ dist/  (배포 대상)
```

`ltc_rates.py`는 급여 본인부담금(국가 고시 정률표) 계산 로직이며, 같은 로직이
`generate_site.py`에 JS로도 내장되어 있어(클라이언트에서 등급/부담유형을 바꿔도 재계산됨)
둘을 수정할 때는 함께 맞춰야 한다.

## 로컬에서 전체 재생성

```bash
export DATA_GO_KR_API_KEY="발급받은 인증키(Decoding)"
python3 fetch_longterm_care.py      # 전체 재수집 (하루 트래픽 한도 걸리면 자동 중단, 다음날 이어서 가능)
python3 fetch_general_status.py
python3 aggregate_nonbenefit.py
python3 build_data.py
python3 generate_site.py
# dist/ 를 로컬에서 바로 열어보려면: python3 -m http.server --directory dist 8000
```

## 배포 (GitHub Pages + GitHub Actions)

1. 이 디렉토리를 GitHub 저장소로 push.
2. 저장소 **Settings → Secrets and variables → Actions**에서
   `DATA_GO_KR_API_KEY` 시크릿 추가 (공공데이터포털 마이페이지의 일반 인증키/Decoding).
3. **Settings → Pages → Build and deployment → Source**를 **GitHub Actions**로 설정.
4. `main` 브랜치에 push하면 `.github/workflows/deploy.yml`이 `dist/`를 빌드해서 자동 배포.
5. `.github/workflows/refresh-data.yml`이 매주 월요일(UTC) 자동으로 전체 데이터를 재수집하고,
   변경이 있으면 커밋·push → 그 push가 다시 `deploy.yml`을 트리거해서 사이트가 자동 갱신됨.
6. 커스텀 도메인을 쓰려면 Pages 설정에서 도메인 연결 후, `generate_site.py` 상단의
   `SITE_URL` 상수를 실제 도메인으로 바꾸고 재배포(sitemap·canonical URL에 반영됨).

## 법적·데이터 신뢰성 메모

- 데이터 라이선스(B550928): "이용허락범위 제한 없음" 확인됨 (2026-11-27, 마이페이지 직접 확인) — 상업적 이용·2차 저작물 작성 자유, 출처표시만 유지.
- 노인장기요양보험법 제35조제6항(소개·알선·유인 금지)에 따라, 이 사이트는 어떤 기관으로부터도
  소개 수수료를 받지 않는다 (사이트 푸터에 명시). 광고(애드센스 등 정액/성과무관)는 허용 범위.
- 급여비용은 보건복지부고시(2025-247호) 기준 "표준 배치비율·대표 이용시간" 가정값이며,
  배치비율 미달 기관·주야간보호 실제 이용시간에 따라 실제 금액과 다를 수 있음(사이트에 안내 문구 포함).
- 자세한 조사 경과는 Claude 프로젝트 문서(`돌봄데이터_조사와결정.md`) 참고.
