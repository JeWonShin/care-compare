#!/usr/bin/env python3
"""
서울 장기요양기관 비교 사이트 — 정적 사이트 생성기

site/data.json (1,020개 입소형·주야간보호형 기관) 을 읽어서:
  - dist/index.html            : 메인 진입 페이지 (스무고개 선택기 + 25개 구 링크 디렉토리)
  - dist/data.json             : 전체 데이터(기존 index.html 스무고개 로직이 그대로 사용)
  - dist/gu/{slug}/index.html  : 구별 고정 페이지 (SEO용 — 서버사이드에서 실제 기관 목록을 HTML로
                                   렌더링 + 그 구 데이터만 담은 계산기)
  - dist/gu/{slug}/data.json   : 그 구만의 데이터 슬라이스 (계산기용, 용량 절감)
  - dist/sitemap.xml, dist/robots.txt

왜 구마다 "진짜" 내용이 다른가 (브런치 템플릿 양산 사례 회피):
  - 각 페이지의 소개 문단은 그 구의 실제 집계값(기관 수, 현재 빈자리 있는 곳 수, 유형별 분포,
    일반대상자 1등급 기준 예상 월비용 최저~최고)으로 매번 새로 계산해서 넣는다. 문구를 복붙하고
    구 이름만 바꾸는 게 아니라, 숫자 자체가 구마다 실제로 다르다.
  - 기관 목록도 그 구에 실제로 있는 기관명·주소·전화번호를 그대로 노출한다(크롤러가 보는 그대로
    사람도 봄 — JS 없이도 핵심 정보가 보임).
"""
import html
import json
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta

BASE = Path(__file__).parent
SITE_DATA = BASE / "site" / "data.json"
DIST = BASE / "dist"

SITE_URL = "https://yoyangcompare.com"  # 커스텀 도메인 (끝에 / 붙이지 말 것)

GU_SLUG = {
    "종로구": "jongno-gu", "중구": "jung-gu", "용산구": "yongsan-gu",
    "성동구": "seongdong-gu", "광진구": "gwangjin-gu", "동대문구": "dongdaemun-gu",
    "중랑구": "jungnang-gu", "성북구": "seongbuk-gu", "강북구": "gangbuk-gu",
    "도봉구": "dobong-gu", "노원구": "nowon-gu", "은평구": "eunpyeong-gu",
    "서대문구": "seodaemun-gu", "마포구": "mapo-gu", "양천구": "yangcheon-gu",
    "강서구": "gangseo-gu", "구로구": "guro-gu", "금천구": "geumcheon-gu",
    "영등포구": "yeongdeungpo-gu", "동작구": "dongjak-gu", "관악구": "gwanak-gu",
    "서초구": "seocho-gu", "강남구": "gangnam-gu", "송파구": "songpa-gu",
    "강동구": "gangdong-gu",
}

DAILY_RATE = {
    "A03": {"1": 93070, "2": 86340, "3": 81540, "4": 81540, "5": 81540},
    "A04": {"1": 74590, "2": 69210, "3": 63800, "4": 63800, "5": 63800},
    "B03": {"1": 69730, "2": 64590, "3": 59640, "4": 58010, "5": 56360},
}
BENEFIT_CATEGORY = {"A03": "시설", "A04": "시설", "B03": "재가"}
COPAY_RATE = {
    "일반": {"시설": 0.20, "재가": 0.15},
    "40%감경": {"시설": 0.12, "재가": 0.09},
    "60%감경": {"시설": 0.08, "재가": 0.06},
    "의료급여수급권자": {"시설": 0.0, "재가": 0.0},
}
TYPE_LABEL = {"A03": "노인요양시설", "A04": "노인요양공동생활가정", "B03": "주야간보호"}


def calc_monthly_copay(ftype, grade, burden="일반", days=30):
    daily = DAILY_RATE.get(ftype, {}).get(grade)
    if daily is None:
        return None
    cat = BENEFIT_CATEGORY[ftype]
    rate = COPAY_RATE[burden][cat]
    return round(daily * rate) * days


def fmt_won(n):
    return f"{n:,.0f}원"


def load_data():
    return json.loads(SITE_DATA.read_text(encoding="utf-8"))


def district_stats(items):
    """그 구의 실제 집계값 계산 (페이지마다 진짜 다른 숫자가 들어가도록)."""
    n = len(items)
    with_vac = sum(1 for d in items if d.get("vac", 0) > 0)
    by_type = {}
    for d in items:
        by_type[d["type"]] = by_type.get(d["type"], 0) + 1

    totals = []
    for d in items:
        copay = calc_monthly_copay(d["type"], "1", "일반")
        if copay is None:
            continue
        nb_min = d.get("nbMin") or 0
        nb_max = d.get("nbMax") or 0
        totals.append(copay + nb_min)
        totals.append(copay + nb_max)

    cost_min = min(totals) if totals else None
    cost_max = max(totals) if totals else None

    return {
        "n": n,
        "with_vac": with_vac,
        "by_type": by_type,
        "cost_min": cost_min,
        "cost_max": cost_max,
    }


def render_facility_card(d):
    copay = calc_monthly_copay(d["type"], "1", "일반")
    vac = d.get("vac", 0)
    vac_badge = f'<span class="badge">빈자리 {vac}명</span>' if vac > 0 else '<span class="badge full">빈자리 없음</span>'

    nb_min, nb_max = d.get("nbMin") or 0, d.get("nbMax") or 0
    if copay is None:
        cost_html = '<div class="note">이 시설유형은 1등급 수가 정보가 없어요.</div>'
    else:
        nb_txt = "정보 없음(기관 문의)" if (nb_min == 0 and nb_max == 0) else (
            fmt_won(nb_min) if nb_min == nb_max else f"{fmt_won(nb_min)} ~ {fmt_won(nb_max)}"
        )
        total_min, total_max = copay + nb_min, copay + nb_max
        total_txt = fmt_won(total_min) if total_min == total_max else f"{fmt_won(total_min)} ~ {fmt_won(total_max)}"
        nb_date = f' <span class="note">({d["nbDate"]} 등록 기준)</span>' if d.get("nbDate") else ""
        cost_html = f"""
        <div class="cost-row">
          <div class="item"><span>급여 본인부담(월, 1등급·일반 기준)</span><b>{fmt_won(copay)}</b></div>
          <div class="item"><span>비급여 추정(월)</span><b>{nb_txt}</b>{nb_date}</div>
        </div>
        <div class="total">예상 월 총비용 <b>{total_txt}</b></div>
        """

    name = html.escape(d["name"])
    addr = html.escape(d["addr"]) if d.get("addr") else None
    tel = html.escape(d["tel"]) if d.get("tel") else None

    addr_line = (
        f'<div class="meta">{addr}{" · <span class=\"nw\">" + tel + "</span>" if tel else ""}</div>'
        if addr else '<div class="meta note">주소·전화번호 준비 중 — 기관명으로 검색해 확인해 주세요.</div>'
    )

    # 드물게 행정구역상 등록된 구와 실제 주소의 구가 다른 기관이 있음(예: 땅값 때문에 경기/강원 등
    # 다른 지역에 지어진 "서울시립" 시설). 데이터 오류가 아니라 실제로 그런 기관이 존재하는 것이라,
    # 숨기거나 빼지 않고 눈에 띄는 경고로만 표시한다.
    # 주소 문자열에 구 이름이 "들어있는지"만 보면 부산 중구·인천 중구·부산 강서구처럼
    # 서울과 같은 이름의 구가 있는 타 시/도 주소를 놓친다. 그래서 첫 토큰이 서울이고,
    # 구 이름이 독립된 토큰으로 있을 때만 정상으로 본다. (클라이언트 JS도 같은 규칙)
    tokens = d["addr"].split() if d.get("addr") else []
    region_mismatch = bool(tokens) and not (tokens[0].startswith("서울") and d["region"] in tokens)
    mismatch_note = (
        f'<div class="warnbox" style="margin-top:8px;">⚠ 행정구역상 {d["region"]} 소속으로 등록되어 있지만, 실제 주소는 위와 같이 다른 지역이에요. 거리를 꼭 확인하세요.</div>'
        if region_mismatch else ""
    )

    return f"""
    <div class="card">
      <div class="card-top">
        <div class="card-name">{name}</div>
        {vac_badge}
      </div>
      <div class="meta"><span class="nw">{TYPE_LABEL.get(d["type"], d["type"])}</span> · <span class="nw">{d["region"]}</span> · <span class="nw">정원 {d["cap"]}명 / 현원 {d["now"]}명</span></div>
      {addr_line}
      {mismatch_note}
      {cost_html}
    </div>
    """


SHARED_CSS = """
:root{
  --bg:#f7f7f5; --card:#ffffff; --ink:#1f2328; --muted:#6b7280;
  --accent:#2f6f4f; --accent-soft:#e7f2ec; --border:#e5e7eb; --warn:#b45309; --warn-bg:#fff7ed;
}
*{box-sizing:border-box;}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;background:var(--bg);color:var(--ink);line-height:1.55;word-break:keep-all;overflow-wrap:break-word;}
.nw{white-space:nowrap;}
.wrap{max-width:760px;margin:0 auto;padding:24px 16px 80px;}
h1{font-size:20px;margin:0 0 4px;}
h2.page-h2{font-size:17px;margin:28px 0 10px;}
.sub{color:var(--muted);font-size:14px;margin:0 0 20px;}
.intro{background:var(--accent-soft);border-radius:12px;padding:16px 18px;font-size:14px;margin-bottom:20px;}
.step{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px 20px;margin-bottom:14px;}
.step h2{font-size:15px;margin:0 0 12px;color:var(--ink);}
.qmark{display:inline-block;width:20px;height:20px;border-radius:50%;background:var(--accent);color:#fff;text-align:center;line-height:20px;font-size:12px;margin-right:8px;}
.options{display:flex;flex-wrap:wrap;gap:8px;}
button.opt{border:1px solid var(--border);background:#fff;border-radius:999px;padding:8px 14px;font-size:14px;cursor:pointer;color:var(--ink);}
button.opt:hover{border-color:var(--accent);}
button.opt.active{background:var(--accent);border-color:var(--accent);color:#fff;}
select{border:1px solid var(--border);border-radius:10px;padding:9px 12px;font-size:14px;background:#fff;color:var(--ink);}
.toggle{display:flex;align-items:center;gap:8px;font-size:14px;}
.toggle input{width:18px;height:18px;}
.warnbox{background:var(--warn-bg);border:1px solid #fcd9a8;color:var(--warn);border-radius:10px;padding:12px 14px;font-size:13px;margin-top:10px;}
.result-head{display:flex;justify-content:space-between;align-items:baseline;margin:22px 0 10px;}
.result-head h2{font-size:16px;margin:0;}
.count{color:var(--muted);font-size:13px;}
.card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:16px 18px;margin-bottom:10px;}
.card-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;}
.card-top .badge{flex-shrink:0;margin-top:1px;}
.card-name{font-size:15px;font-weight:600;}
.badge{font-size:11px;padding:3px 8px;border-radius:999px;background:var(--accent-soft);color:var(--accent);white-space:nowrap;}
.badge.full{background:#f3f4f6;color:#9ca3af;}
.meta{color:var(--muted);font-size:13px;margin-top:4px;}
.cost-row{display:flex;gap:18px;margin-top:10px;font-size:13px;flex-wrap:wrap;}
.cost-row .item b{display:block;font-size:15px;color:var(--ink);}
.cost-row .item span{color:var(--muted);font-size:12px;}
.total{margin-top:10px;padding-top:10px;border-top:1px dashed var(--border);font-size:14px;}
.total b{font-size:17px;color:var(--accent);}
.empty{text-align:center;color:var(--muted);padding:40px 0;font-size:14px;}
.note{font-size:12px;color:var(--muted);margin-top:4px;}
footer{color:var(--muted);font-size:12px;text-align:center;margin-top:30px;}
.hospital-guide{background:var(--accent-soft);border-radius:12px;padding:16px 18px;font-size:14px;}
.gulist{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:8px;margin:14px 0 6px;}
.gulist a{display:block;text-align:center;background:#fff;border:1px solid var(--border);border-radius:10px;padding:10px 6px;font-size:13px;color:var(--ink);text-decoration:none;}
.gulist a:hover{border-color:var(--accent);color:var(--accent);}
.backlink{display:inline-block;margin:18px 0 0;font-size:13px;color:var(--accent);text-decoration:none;}
"""

FOOTER_HTML = """
<footer>
  본 저작물은 '국민건강보험공단'에서 작성하여 공공데이터포털에 개방한 '장기요양기관 검색 서비스' 데이터를 이용하였으며, 해당 데이터는 'www.data.go.kr'에서 무료로 내려받을 수 있습니다.<br><br>
  급여비용은 2026년 1월 보건복지부고시(제2025-247호) 기준 추정치이며 실제 청구액과 다를 수 있습니다. 비급여(식재료비 등)는 기관이 공시한 최근 등록값 기준 추정 범위입니다. 정확한 금액과 입소 가능 여부는 반드시 해당 기관 또는 국민건강보험공단(1577-1000)에 다시 확인하세요.<br><br>
  이 사이트는 어떤 장기요양기관으로부터도 소개·알선 대가나 입소 연계 수수료를 받지 않으며, 받을 계획도 없습니다. 노인장기요양보험법 제35조제6항은 영리 목적으로 금전·물품 등을 제공하거나 약속하여 수급자를 특정 기관에 소개·알선·유인하는 행위를 금지하고 있습니다.
</footer>
"""

CALC_JS = """
const DAILY_RATE = {
  A03: {1:93070, 2:86340, 3:81540, 4:81540, 5:81540},
  A04: {1:74590, 2:69210, 3:63800, 4:63800, 5:63800},
  B03: {1:69730, 2:64590, 3:59640, 4:58010, 5:56360},
};
const BENEFIT_CATEGORY = {A03:"시설", A04:"시설", B03:"재가"};
const COPAY_RATE = {
  "일반": {"시설":0.20, "재가":0.15},
  "40%감경": {"시설":0.12, "재가":0.09},
  "60%감경": {"시설":0.08, "재가":0.06},
  "의료급여수급권자": {"시설":0.0, "재가":0.0},
};
const TYPE_LABEL = {A03:"노인요양시설", A04:"노인요양공동생활가정", B03:"주야간보호"};

function calcMonthlyCopay(type, grade, burden, days=30){
  const daily = DAILY_RATE[type]?.[grade];
  if(daily == null) return null;
  const cat = BENEFIT_CATEGORY[type];
  const rate = COPAY_RATE[burden][cat];
  return Math.round(daily * rate) * days;
}
const fmt = n => n.toLocaleString('ko-KR') + '원';
const esc = s => (s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let DATA = [];

function renderCards(list, gradeEl, burdenEl, vacEl, resultsEl, countEl, gradeWarnEl){
  const grade = gradeEl.value, burden = burdenEl.value, vacancyOnly = vacEl.checked;
  if(gradeWarnEl){
    if(['3','4','5'].includes(grade)){
      gradeWarnEl.style.display = 'block';
      gradeWarnEl.textContent = '3~5등급은 원칙적으로 재가급여만 이용 가능하며, 요양원(시설급여) 입소는 등급판정위원회의 예외 심의를 거친 경우에만 가능해요. 아래 요양원 비용은 예외 입소가 인정됐다고 가정한 참고값이에요.';
    } else {
      gradeWarnEl.style.display = 'none';
    }
  }
  let filtered = vacancyOnly ? list.filter(d => d.vac > 0) : list.slice();
  filtered = filtered.map(d => {
    const copay = calcMonthlyCopay(d.type, grade, burden);
    const totalMin = copay != null ? copay + d.nbMin : null;
    const totalMax = copay != null ? copay + d.nbMax : null;
    return {...d, copay, totalMin, totalMax};
  });
  filtered.sort((a,b) => (b.vac - a.vac) || ((a.totalMin ?? 1e15) - (b.totalMin ?? 1e15)));
  countEl.textContent = `${filtered.length}곳`;
  resultsEl.innerHTML = '';
  if(filtered.length === 0){
    resultsEl.innerHTML = '<div class="empty">조건에 맞는 시설이 없어요. 빈자리 조건을 해제해 보세요.</div>';
    return;
  }
  for(const d of filtered){
    const card = document.createElement('div');
    card.className = 'card';
    const vacBadge = d.vac > 0 ? `<span class="badge">빈자리 ${d.vac}명</span>` : `<span class="badge full">빈자리 없음</span>`;
    let costHtml = '';
    if(d.copay == null){
      costHtml = `<div class="note">이 등급은 해당 시설유형에서 수가 정보가 없어요.</div>`;
    } else {
      const nb = d.nbMin === 0 && d.nbMax === 0 ? '정보 없음(기관 문의)' : (d.nbMin === d.nbMax ? fmt(d.nbMin) : `${fmt(d.nbMin)} ~ ${fmt(d.nbMax)}`);
      const nbDateNote = d.nbDate ? ` <span class="note">(${d.nbDate} 등록 기준)</span>` : '';
      const total = d.totalMin === d.totalMax ? fmt(d.totalMin) : `${fmt(d.totalMin)} ~ ${fmt(d.totalMax)}`;
      costHtml = `
        <div class="cost-row">
          <div class="item"><span>급여 본인부담(월)</span><b>${fmt(d.copay)}</b></div>
          <div class="item"><span>비급여 추정(월)</span><b>${nb}</b>${nbDateNote}</div>
        </div>
        <div class="total">예상 월 총비용 <b>${total}</b></div>
      `;
    }
    const addrLine = d.addr ? `<div class="meta">${esc(d.addr)}${d.tel ? ' · <span class="nw">' + esc(d.tel) + '</span>' : ''}</div>` : `<div class="meta note">주소·전화번호 준비 중 — 기관명으로 검색해 확인해 주세요.</div>`;
    const addrTokens = d.addr ? d.addr.trim().split(/\\s+/) : [];
    const mismatchNote = (addrTokens.length && !(addrTokens[0].startsWith('서울') && addrTokens.includes(d.region)))
      ? `<div class="warnbox" style="margin-top:8px;">⚠ 행정구역상 ${esc(d.region)} 소속으로 등록되어 있지만, 실제 주소는 위와 같이 다른 지역이에요. 거리를 꼭 확인하세요.</div>`
      : '';
    card.innerHTML = `
      <div class="card-top">
        <div class="card-name">${esc(d.name)}</div>
        ${vacBadge}
      </div>
      <div class="meta"><span class="nw">${TYPE_LABEL[d.type] || d.type}</span> · <span class="nw">${esc(d.region)}</span> · <span class="nw">정원 ${d.cap}명 / 현원 ${d.now}명</span></div>
      ${addrLine}
      ${mismatchNote}
      ${costHtml}
    `;
    resultsEl.appendChild(card);
  }
}
"""


def render_home(data, generated_at):
    regions = sorted(set(d["region"] for d in data))
    gu_links = "\n".join(
        f'<a href="gu/{GU_SLUG[r]}/">{r}</a>' for r in regions if r in GU_SLUG
    )

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>서울 요양원·주야간보호 비교 — 빈자리·예상 비용 한눈에</title>
<meta name="description" content="서울 25개 구 노인요양시설·주야간보호센터의 실시간 빈자리와 등급·본인부담 유형별 예상 월 비용을 공공데이터 기반으로 바로 계산해 드려요.">
<link rel="canonical" href="{SITE_URL}/">
<style>{SHARED_CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>서울 요양원·주야간보호 비교 (베타)</h1>
  <p class="sub">공공데이터포털(국민건강보험공단) 장기요양기관 데이터 기반. 빈자리·예상 비용을 조건별로 바로 계산해 드려요.</p>

  <h2 class="page-h2">구별로 바로 보기</h2>
  <div class="gulist">
  {gu_links}
  </div>

  <div class="step" id="step0" style="margin-top:20px;">
    <h2><span class="qmark">0</span>매일 의료적 처치(콧줄·흡인·욕창 관리 등)가 필요하신가요?</h2>
    <div class="options">
      <button class="opt" data-step0="yes">예, 매일 처치가 필요해요</button>
      <button class="opt active" data-step0="no">아니요 / 잘 모르겠어요</button>
    </div>
  </div>

  <div id="hospitalGuide" style="display:none" class="step">
    <div class="hospital-guide">
      매일 의료적 처치가 필요하시면 <b>요양병원</b>이 더 맞을 수 있어요. 요양병원은 의사·간호인력이 상주하지만, 이 사이트가 다루는 노인요양시설·주야간보호와는 데이터 출처와 비용 구조가 달라 아직 준비 중이에요. (국민건강보험공단 1577-1000 또는 담당 의료진과 상의해 보세요.)
    </div>
  </div>

  <div id="mainFlow">
    <div class="step">
      <h2><span class="qmark">1</span>어느 구에서 찾으세요?</h2>
      <select id="regionSelect"></select>
    </div>

    <div class="step">
      <h2><span class="qmark">2</span>장기요양등급과 본인부담 유형을 알려주세요</h2>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px;">
        <select id="gradeSelect">
          <option value="1">1등급</option>
          <option value="2">2등급</option>
          <option value="3">3등급</option>
          <option value="4">4등급</option>
          <option value="5">5등급</option>
        </select>
        <select id="burdenSelect">
          <option value="일반">일반대상자</option>
          <option value="40%감경">40% 감경대상자</option>
          <option value="60%감경">60% 감경대상자</option>
          <option value="의료급여수급권자">의료급여수급권자(면제)</option>
        </select>
      </div>
      <div class="note">등급·부담유형에 따라 아래 예상 비용이 자동으로 바뀌어요. 모르면 일단 "일반대상자"로 보시고, 나중에 공단(1577-1000)에 확인해 보세요.</div>
      <div class="note">※ 급여비용은 보건복지부고시(2025-247호, 2026.1.1 시행) 기준 "표준 배치비율·대표 이용시간" 가정값이에요. 요양보호사 배치비율이 기준 미달인 시설은 노인요양시설 기준 1일 최대 4,550원(월 약 13.7만원) 더 낮을 수 있고, 주야간보호는 실제 이용시간(3~13시간+)에 따라 수가가 달라요. 정확한 금액은 반드시 기관에 다시 확인하세요.</div>
      <div id="gradeWarn" class="warnbox" style="display:none"></div>
    </div>

    <div class="step">
      <h2><span class="qmark">3</span>지금 빈자리가 있는 곳만 볼까요?</h2>
      <label class="toggle"><input type="checkbox" id="vacancyOnly" checked> 빈자리 있는 곳만 보기</label>
      <div class="note">빈자리 수치는 공단에 등록된 정원·현원 기준이라 실제 입소 가능 여부는 시설에 다시 확인하는 게 안전해요.</div>
    </div>

    <div class="step">
      <h2><span class="qmark">4</span>참고: 상태(치매·와상 등)</h2>
      <div class="note">현재 API로는 시설별 치매·와상 수용 가능 여부를 구분할 수 없어요. 아래 목록은 빈자리가 넉넉한 곳부터 보여드리지만, 특정 상태(와상·콧줄·치매)를 받아주는지는 반드시 시설에 직접 문의해 주세요.</div>
    </div>

    <div class="result-head">
      <h2>조건에 맞는 시설</h2>
      <span class="count" id="resultCount"></span>
    </div>
    <div id="results"></div>
  </div>

  {FOOTER_HTML}
  <p class="note" style="text-align:center;">데이터 기준: {generated_at}</p>
</div>

<script>
{CALC_JS}

function regionsFromData(data){{
  const set = new Set(data.map(d => d.region));
  return Array.from(set).sort();
}}

function setupStep0(){{
  const buttons = document.querySelectorAll('[data-step0]');
  buttons.forEach(b => b.addEventListener('click', () => {{
    buttons.forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    const isYes = b.dataset.step0 === 'yes';
    document.getElementById('hospitalGuide').style.display = isYes ? 'block' : 'none';
    document.getElementById('mainFlow').style.display = isYes ? 'none' : 'block';
  }}));
}}

fetch('data.json').then(r => r.json()).then(data => {{
  DATA = data;
  const regions = regionsFromData(data);
  const sel = document.getElementById('regionSelect');
  sel.innerHTML = regions.map(r => `<option value="${{r}}">${{r}}</option>`).join('');

  const gradeEl = document.getElementById('gradeSelect');
  const burdenEl = document.getElementById('burdenSelect');
  const vacEl = document.getElementById('vacancyOnly');
  const resultsEl = document.getElementById('results');
  const countEl = document.getElementById('resultCount');
  const gradeWarnEl = document.getElementById('gradeWarn');

  function doRender(){{
    const region = sel.value;
    const list = DATA.filter(d => d.region === region);
    renderCards(list, gradeEl, burdenEl, vacEl, resultsEl, countEl, gradeWarnEl);
  }}

  [sel, gradeEl, burdenEl, vacEl].forEach(el => el.addEventListener('change', doRender));
  setupStep0();
  doRender();
}}).catch(err => {{
  document.getElementById('results').innerHTML = '<div class="empty">데이터를 불러오지 못했어요.</div>';
}});
</script>
</body>
</html>
"""
    return html


def render_district(region, items, generated_at):
    stats = district_stats(items)
    slug = GU_SLUG[region]

    type_desc = ", ".join(f"{TYPE_LABEL[t]} {c}곳" for t, c in sorted(stats["by_type"].items()))
    cost_line = (
        f'1등급·일반대상자 기준 예상 월 총비용은 약 {fmt_won(stats["cost_min"])} ~ {fmt_won(stats["cost_max"])} 사이로 나타나요(시설·등급에 따라 차이 있음).'
        if stats["cost_min"] is not None else "비용 추정에 필요한 데이터가 아직 부족해요."
    )

    intro = f"""
    <div class="intro">
      {region}에는 현재 공공데이터포털(국민건강보험공단)에 등록된 노인요양시설·주야간보호기관이
      <b>{stats['n']}곳</b> 있고({type_desc}), 이 중 <b>{stats['with_vac']}곳</b>에 지금 빈자리가 있어요.
      {cost_line}
    </div>
    """

    cards_html = "\n".join(render_facility_card(d) for d in sorted(items, key=lambda d: (-d.get("vac", 0), d["name"])))

    data_json = json.dumps(items, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{region} 요양원·주야간보호 비교 — 빈자리 {stats['with_vac']}곳, 예상 비용 바로 계산</title>
<meta name="description" content="{region} 노인요양시설·주야간보호센터 {stats['n']}곳의 실시간 빈자리와 등급·본인부담 유형별 예상 월 비용. 공공데이터 기반, 소개 수수료 없음.">
<link rel="canonical" href="{SITE_URL}/gu/{slug}/">
<style>{SHARED_CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>{region} 요양원·주야간보호 비교</h1>
  <p class="sub">공공데이터포털(국민건강보험공단) 장기요양기관 데이터 기반. 등급·본인부담 유형을 바꾸면 예상 비용이 바로 다시 계산돼요.</p>
  {intro}

  <div class="step">
    <h2><span class="qmark">1</span>장기요양등급과 본인부담 유형을 알려주세요</h2>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px;">
      <select id="gradeSelect">
        <option value="1">1등급</option>
        <option value="2">2등급</option>
        <option value="3">3등급</option>
        <option value="4">4등급</option>
        <option value="5">5등급</option>
      </select>
      <select id="burdenSelect">
        <option value="일반">일반대상자</option>
        <option value="40%감경">40% 감경대상자</option>
        <option value="60%감경">60% 감경대상자</option>
        <option value="의료급여수급권자">의료급여수급권자(면제)</option>
      </select>
    </div>
    <div class="note">※ 급여비용은 보건복지부고시(2025-247호, 2026.1.1 시행) 기준 "표준 배치비율·대표 이용시간" 가정값이에요. 정확한 금액은 반드시 기관에 다시 확인하세요.</div>
    <div id="gradeWarn" class="warnbox" style="display:none"></div>
  </div>

  <div class="step">
    <h2><span class="qmark">2</span>지금 빈자리가 있는 곳만 볼까요?</h2>
    <label class="toggle"><input type="checkbox" id="vacancyOnly"> 빈자리 있는 곳만 보기</label>
  </div>

  <div class="result-head">
    <h2>{region} 기관 목록</h2>
    <span class="count" id="resultCount">{stats['n']}곳</span>
  </div>

  <div id="results">{cards_html}</div>

  <a class="backlink" href="../../">← 다른 구 보기 / 전체 비교로 돌아가기</a>

  {FOOTER_HTML}
  <p class="note" style="text-align:center;">데이터 기준: {generated_at}</p>
</div>

<script>
{CALC_JS}
DATA = {data_json};

const gradeEl = document.getElementById('gradeSelect');
const burdenEl = document.getElementById('burdenSelect');
const vacEl = document.getElementById('vacancyOnly');
const resultsEl = document.getElementById('results');
const countEl = document.getElementById('resultCount');
const gradeWarnEl = document.getElementById('gradeWarn');

function doRender(){{
  renderCards(DATA, gradeEl, burdenEl, vacEl, resultsEl, countEl, gradeWarnEl);
}}
[gradeEl, burdenEl, vacEl].forEach(el => el.addEventListener('change', doRender));
doRender();
</script>
</body>
</html>
"""
    return html, data_json


def build():
    data = load_data()
    generated_at = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")

    DIST.mkdir(exist_ok=True)
    (DIST / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (DIST / "index.html").write_text(render_home(data, generated_at), encoding="utf-8")

    by_region = {}
    for d in data:
        by_region.setdefault(d["region"], []).append(d)

    gu_dir = DIST / "gu"
    gu_dir.mkdir(exist_ok=True)

    sitemap_urls = [f"{SITE_URL}/"]
    for region, items in by_region.items():
        if region not in GU_SLUG:
            print(f"  [경고] 슬러그 매핑 없는 구: {region} ({len(items)}곳) — 건너뜀")
            continue
        slug = GU_SLUG[region]
        page_dir = gu_dir / slug
        page_dir.mkdir(parents=True, exist_ok=True)
        html, data_json = render_district(region, items, generated_at)
        (page_dir / "index.html").write_text(html, encoding="utf-8")
        (page_dir / "data.json").write_text(data_json, encoding="utf-8")
        sitemap_urls.append(f"{SITE_URL}/gu/{slug}/")

    sitemap = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for u in sitemap_urls:
        sitemap += f"  <url><loc>{u}</loc></url>\n"
    sitemap += "</urlset>\n"
    (DIST / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    (DIST / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n", encoding="utf-8")

    print(f"생성 완료: {DIST} (구 페이지 {len(sitemap_urls)-1}개 + 홈 1개)")
    print(f"  데이터 기준일: {generated_at}")


if __name__ == "__main__":
    build()
