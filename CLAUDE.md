# care-compare 프로젝트 컨텍스트

## 무엇을 만드는가
서울시 25개 구의 **장기요양기관(요양원/주야간보호센터) 비교 사이트**.
data.go.kr 공공데이터(서비스 B550928, 국민건강보험공단_장기요양기관 검색 서비스)로 시설 목록·정원/현원(빈자리)·비급여 비용을 수집해 정적 사이트로 배포.
목적은 직장 소득과 별개의 블로그/사이트 수익화 — SEO 트래픽이 핵심이라 "진짜 쓸모 있는 도구"로 승부해야 함(애드센스 등 수익화는 추후).

## 라이선스 확인 완료
B550928의 공공데이터포털 "이용허락범위"는 **"제한 없음"** (상업적 이용·2차 저작물 작성 모두 허용). 재확인 불필요.

## 파이프라인 구조
```
fetch_longterm_care.py   → output/seoul_all.csv, seoul_all_nonbenefit.csv (전체 재수집, API 호출)
fetch_general_status.py  → output/general_status.csv (주소/전화, 증분 수집)
aggregate_nonbenefit.py  → output/facility_nonbenefit_monthly.csv (월별 비급여 비용 집계)
build_data.py            → site/data.json (위 CSV들을 사이트 스키마로 병합)
generate_site.py         → dist/ (실제 배포되는 정적 HTML 전체)
```
`refresh-data.yml`(GitHub Actions, 매일 UTC 20:00=KST 05:00)이 위 5단계를 순서대로 돌리고 변경사항을 커밋·푸시 → 그 푸시가 `deploy.yml`을 트리거해서 GitHub Pages 자동 배포.

**중요**: `fetch_longterm_care.py`는 `seoul_all.csv`/`seoul_all_nonbenefit.csv`(접미사 없음)로 저장하지만, `build_data.py`/`aggregate_nonbenefit.py`는 `_fixed` 접미사 파일을 우선 찾음(과거 버그 수정 흔적). `refresh-data.yml`이 매번 rename 처리하므로 로컬에서 수동 실행할 땐 이 차이를 기억할 것. 두 스크립트 모두 접미사 없는 파일로 폴백하도록 이미 처리돼 있음.

## 꼭 지켜야 할 설계 결정 (이유 포함)

1. **구별 페이지는 반드시 실제 통계를 포함해야 함** (`district_stats()`). 블로그/브런치류 사이트가 "지역명만 바꾼 템플릿 양산"으로 검색엔진 제재를 받은 선례가 있어 조사됨 — 25개 구 페이지가 복붙처럼 보이면 SEO에 치명적. 기관 수·빈자리 수·유형 분포·비용 범위 등 구마다 다른 실제 숫자를 인트로에 반드시 넣을 것.

2. **GitHub Pages는 프로젝트 사이트**(`https://jewonshin.github.io/care-compare/`, 도메인 루트 아님). `href="/..."` 절대경로는 깨짐 — 반드시 상대경로(`href="gu/..."`, `href="../../"`) 사용. 과거 이 버그로 실제 배포 후 링크가 깨진 적 있음.

3. **HTML 이스케이프 필수**. 기관명에 `&` 같은 특수문자가 실제로 존재함(예: "숲속데이케어&재가복지센터"). Python SSR(`html.escape`)과 클라이언트 JS(`esc()` 헬퍼) 양쪽 다 적용돼 있어야 함.

4. **행정구역-실주소 불일치는 제외가 아니라 경고 배지로 표시**. 전체 1,020개 중 6개(0.6%)가 행정상 서울 소속이지만 실제 주소는 타 시/도(주로 "서울시립" 시설이 경기/강원에 물리적으로 위치). 원본 API(`siGunGuCd`) 자체가 그렇게 등록돼 있어 우리 쪽 필터링 버그가 아님 — 서울 거주자 자격요건상 유효할 수 있어 제외하지 않고 `region_mismatch` 경고만 표시.

5. **데이터 신선도**: `stpRptDt`(현황보고일자) 필드는 "현원이 마지막으로 갱신된 날짜"가 아니라 정원 변경 신고일로 보임(1986~2026 넓게 분포) — 현원(빈자리) 자체의 갱신 시점을 보장하는 필드가 아님. 각 기관이 공단 시스템에 입소/퇴소를 직접 입력하는 구조라 완전한 실시간은 아니므로, 매일 자동 재수집으로 지연을 최소화하는 전략을 취함. 오퍼레이션별 하루 10,000건 한도 대비 전체 재수집은 기관당 2회(입소인원+비급여) × 약 6,090건 ≈ 60% 수준이라 매일 돌려도 여유 있음.

## GitHub/배포 관련 트러블슈팅 메모
- 저장소는 Public(GitHub Pages가 개인 계정 Private 저장소에서 유료 플랜 없이 비활성화되는 제약 때문). 코드에 시크릿 없음, API 키는 Actions secrets(`DATA_GO_KR_API_KEY`)에만 있음 — 공개해도 안전.
- 워크플로 파일(`.github/workflows/*.yml`)을 push하려면 PAT에 `workflow` scope 필요(`repo`만으로는 거부됨).
- Settings → Actions → General → Actions permissions가 "Disable actions"로 돼 있으면 어떤 워크플로도 안 돌아감 — "Allow all actions and reusable workflows"로 설정+저장 필요.

## 아직 미정/보류
- 커스텀 도메인 미정 — 현재 `generate_site.py`의 `SITE_URL`은 GitHub Pages 주소(`https://jewonshin.github.io/care-compare`). 도메인 정하면 바꾸고 재배포(sitemap/canonical 갱신).
- `refresh-data.yml`의 첫 실제 스케줄 실행(과거엔 주1회였고 방금 매일로 변경) 모니터링 필요.
