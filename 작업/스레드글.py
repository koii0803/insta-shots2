# -*- coding: utf-8 -*-
"""스레드 글만 발행용 랜덤 글 생성기 (사주쇼츠업로드자동화 스킬).

2026-09-18 스레드 실측(docs/스레드수집/*.md) 기준. 답글 상위 글의 틀은 전부 "틀 고정 + 띠·년생·항목만 교체"였다.
그 틀(명운재 골격)을 그대로 두고 칸마다 문장을 여러 벌 준비해 매번 다른 조합으로 뽑는다.

골격(순서 고정):
  ① 훅 1줄 ("나"로 시작)          ② 🐭 띠(년생 3개)        ③ 기질 1~2줄
  ④ 올해 흐름 1줄 (엔진 관계별)    ⑤ 막혀 있던 <A·B·C> 다시 움직이기
  ⑥ 올해는 유난히 <항목 4~5> 열리는  ⑦ 시점 1줄   ⑧ 신뢰 한 줄
  ⑨ 행동 요구 = "네 년생은 링크에서 30초" (사람이 봐주는 게 아니라 표 그대로)   ⑩ 마무리 1줄   ⑪ 복채 스하리
규칙: 반말, 해시태그 0, 이모지는 띠 1개, 500자 안, 본문에 링크 없음(링크는 첫 답글 = config.THREADS_REPLY),
      금지어(문구규칙.md) 걸리면 다시 뽑음, 최근 글과 같은 띠+훅 조합이면 다시 뽑음.
띠·년생·올해 관계(삼합·육합·충·같은띠)는 saju-arcade 엔진(saju_rows.ts all)에서 한 번 받아 cache/ 에 둔다.

    python 스레드글.py                    # 랜덤 1개
    python 스레드글.py --animal 쥐        # 띠 지정
    python 스레드글.py --n 120            # 시험: 120개 뽑아 중복·글자수·금지어 검사

2026-09-19: 깃허브 액션(작업/스레드하루치.py)도 쓰게 쇼츠저장소/작업/ 으로 옮김. PC config 없이 돈다.
  띠 표 = 작업/띠년생_2026.json(엔진에서 한 번 받아 커밋), 기록 = 쇼츠저장소/스레드글기록.jsonl(PC·액션 공용, 깃으로 합쳐짐).
  PC 의 유튜브업로더/스레드글.py 는 이 파일을 부르는 껍데기.
"""
import os
import re
import sys
import json
import random
import argparse
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))                    # 쇼츠저장소/작업
STORE = os.path.dirname(HERE)                                        # 쇼츠저장소
ARCADE = os.path.join(os.path.dirname(os.path.dirname(STORE)), "saju-arcade")   # PC 에만 있음(표 새로 받을 때)
CACHE = os.path.join(HERE, "띠년생_%d.json")
RECORD = os.path.join(STORE, "스레드글기록.jsonl")     # 예약표에 들어간 글. 중복 검사용 (PC·액션 공용)
BASE_YEAR = 2026
TEXT_MAX = 500
RECENT = 30                      # 최근 이 개수와 띠+훅이 겹치면 다시 뽑음
SPEAKER = ""                     # 화자 이름(= PC config.THREADS_SPEAKER). 사장님이 정하면 여기. 비면 "나"만

EMOJI = {"쥐": "🐭", "소": "🐮", "호랑이": "🐯", "토끼": "🐰", "용": "🐲", "뱀": "🐍",
         "말": "🐴", "양": "🐑", "원숭이": "🐵", "닭": "🐔", "개": "🐶", "돼지": "🐷"}

# 문구규칙.md 1절 + 스레드 조사 결론(소름·자빠질뻔·터진다·100% 금지). 하나라도 있으면 그 글은 버린다.
BANNED = ["소름", "자빠질", "터진다", "터져", "100%", "반드시", "무조건", "확실", "틀림없", "족집게", "적중", "보장",
          "정확", "복권", "로또", "행운의 숫자", "당첨", "투자", "주식", "가상화폐", "암호화폐", "비트코인", "부동산", "합격", "수술", "수명", "죽을",
          "우울", "공황", "임신", "유산", "불임", "간·", "심장", "신장", "혈압", "혈당", "부적", "굿", "액운", "액막이",
          "저주", "운명을 바꾼", "마지막 기회", "오늘만", "놓치면", "검증", "1위", "유일", "최고", "전문가", " 명인", "명인이",
          "직접 감정", "봐줄게", "봐준다", "풀어줄게", "상담", "—"]

# ① 훅. 전부 "나"로 시작 (답글이 붙는 1인칭). {a}=띠
HOOKS = [
    "나 오늘 {a}띠 표 넘기다가 손이 멈췄잖아",
    "나 {a}띠 올해 흐름 보고 그냥 못 지나가겠더라",
    "나 돌려 말 안 해. {a}띠부터 본다",
    "나 {a}띠 표 뽑다가 놀랐다",
    "나 오늘 {a}띠 하나만 짚고 갈게",
    "나 좋은 말만 안 해. {a}띠 올해 이거야",
    "나 {a}띠 올해 표 보고 한참 들여다봤다",
    "나 오늘은 {a}띠 차례야. 짧게 간다",
]

# ③ 기질. 띠마다 3벌. 생활 비유만(자동차·날씨·계절·도구·서랍), 몸·돈 단정 없음
TRAITS = {
    "쥐": ["머리 회전 빠르고 눈치가 밝은 게 타고난 기질이야", "작은 기회를 먼저 알아채는 눈이 있어. 다만 혼자 다 챙기려다 지치기 쉬워", "겉으론 가볍게 굴어도 속에선 계산이 끝나 있는 사람이야"],
    "소": ["한번 잡으면 끝까지 끌고 가는 뚝심이 타고난 기질이야", "느리게 가는 것 같아도 남들보다 멀리 가 있는 사람이야", "말수는 적은데 책임은 제일 무겁게 지는 쪽이야"],
    "호랑이": ["앞장서는 게 편하고 멈춰 있는 걸 못 견디는 기질이야", "결정이 빠르고 밀어붙이는 힘이 있어. 그만큼 혼자 다 떠안기도 해", "판이 커질수록 살아나는 사람이야"],
    "토끼": ["분위기 읽는 눈이 밝고 사람 사이를 부드럽게 잇는 기질이야", "조용히 자리를 지키는데 정작 필요한 순간엔 제일 먼저 움직여", "예민한 만큼 남이 못 보는 걸 먼저 봐"],
    "용": ["스케일이 크고 한 번 마음먹으면 판을 새로 짜는 기질이야", "남 밑에 오래 있기 어렵고 내 이름으로 하고 싶어 하는 사람이야", "기다리는 걸 제일 못 해. 대신 움직이면 크게 움직여"],
    "뱀": ["겉은 조용한데 속에서 오래 끓이는 기질이야", "말을 아끼고 한 번에 정리하는 사람이야. 그래서 놓치는 게 없어", "감이 빠르고 사람 속을 잘 읽어"],
    "말": ["가만히 있으면 답답하고 움직여야 풀리는 기질이야", "새 길 여는 데 강하고 반복엔 약해", "밝고 빠른데 정작 자기 자리는 자주 바꿔"],
    "양": ["느긋해 보여도 속으로는 끊임없이 생각하고 또 생각하는 사람이야", "감각이 예민하고 사람 마음을 잘 살펴. 정작 본인은 그게 얼마나 강점인지 몰라", "혼자보다 누군가와 있을 때 힘이 나는 기질이야"],
    "원숭이": ["머리 회전 빠르고 손재주 좋은 게 타고난 기질이야", "재치로 판을 바꾸는 사람이야. 다만 산만해지면 다 놓쳐", "어디 가서든 금방 자리 잡는 쪽이야"],
    "닭": ["꼼꼼하고 기준이 분명한 게 타고난 기질이야", "말이 앞서는 것 같아도 준비는 제일 철저해", "눈에 띄는 자리에서 살아나는 사람이야"],
    "개": ["겉은 과묵한데 속엔 의리와 고집이 단단하게 박혀 있어", "한번 마음 먹으면 끝까지 가는 힘이 있고, 그 뚝심이 결국 기회를 끌어당겨", "사람한테 쉽게 마음 안 주는데 한 번 주면 오래 가"],
    "돼지": ["넉넉하고 사람 좋은 게 타고난 기질이야. 그래서 손해도 자주 봐", "급하게 안 가고 차곡차곡 쌓는 사람이야", "겉으로 편해 보여도 속으론 다 기억하고 있어"],
}

# ④ 올해 흐름 (엔진 관계별). {a}=띠
FLOWS = {
    "열림": ["올해는 {a}띠 자리로 바람이 들어오는 해라 묵혀 뒀던 게 한꺼번에 움직이기 시작해",
            "올해 흐름이 {a}띠 쪽으로 붙는 해야. 막혀 있던 문이 하나씩 열리는 구조",
            "{a}띠는 올해 시동이 걸리는 해야. 그동안 밀린 게 순서대로 풀리기 시작해",
            "올해는 {a}띠가 흐름을 가장 자연스럽게 타는 띠 중 하나야"],
    "이동": ["올해는 {a}띠 자리가 흔들리는 해야. 가만히 있으려 해도 상황이 먼저 움직인다",
            "{a}띠는 올해 버티는 해가 아니라 어디로 옮길지 정하는 해야",
            "올해 {a}띠는 자리를 흔들어서 옮기게 만드는 흐름이야. 미룰수록 선택지가 줄어",
            "{a}띠한테 올해는 정리하고 옮기는 해야. 붙잡고 있던 걸 놓는 순간 길이 보여"],
    "본인": ["올해는 {a}띠 본인 해라 기준을 다시 잡는 해야. 작년까지 기준으로 가면 안 맞아",
            "{a}띠는 올해 자기 자리로 돌아오는 해야. 남 따라가던 걸 멈추면 풀려",
            "올해 {a}띠는 리셋 해야. 새로 짜는 판이 앞으로 몇 년을 정해"],
    "평년": ["올해는 {a}띠한테 큰 바람은 없는 해야. 대신 지금 쌓는 게 내년에 그대로 올라와",
            "{a}띠는 올해 조용히 정비하는 해야. 서두르면 잃고 다지면 남아",
            "올해 {a}띠는 눈에 띄는 변화보다 안에서 채워지는 해야"],
}
RELATION_KIND = {"삼합": "열림", "육합": "열림", "충": "이동", "같은띠": "본인", "": "평년"}

# ⑤·⑥ 막혀 있던 <A·B·C> → 움직임 → 귀인 / 올해는 유난히 <항목 4~5>. 흐름 종류(엔진 관계)마다 말이 다르다
BLOCKED = ["연애", "재물", "직장", "인간관계", "이직", "계약", "이사", "공부", "사업", "관계 정리", "수입 흐름", "자리 이동", "새 인연", "오래된 인연"]
MOVE_ITEMS = ["이직", "이사", "사람 정리", "자리 이동", "계약 갈아타기", "관계 재정리", "새 환경", "오래 미룬 결정", "팀·소속 변화", "거리 두기"]
OPEN_ITEMS = ["이직 제안", "계약", "새 인연", "오래된 인연 다시 닿기", "수입 길 늘어나기", "자리 이동", "자격 준비", "사업 확장",
              "관계 정리", "이사·환경 변화", "공부 흐름", "사람 소개", "결정 마무리", "실력 인정", "승진·직급 변화", "해외·먼 곳 기회"]
CALM_ITEMS = ["오래 미룬 정리", "관계 다지기", "실력 쌓기", "자격 준비", "돈 계획 다시 짜기", "자리 지키기", "사람 가려 만나기", "습관 바꾸기", "공부 흐름", "내년 준비"]
POOLS = {
    "열림": dict(items=BLOCKED, blocked=["막혀 있던 <{items}> 쪽이"],
                move=["다시 움직이기 시작하고", "순서대로 풀리기 시작하고", "하나씩 열리기 시작하고", "다시 돌아가기 시작하고"],
                gain=["기다렸던 사람과 기회가 같이 들어와", "막혔던 자리에 귀인이 나타나", "멈췄던 연락이 다시 닿기 시작해", "기회가 사람을 타고 들어와"],
                strong_items=OPEN_ITEMS, strong=["강하다", "열리는 해다", "크게 움직인다", "눈에 띈다"]),
    "이동": dict(items=MOVE_ITEMS[:6], blocked=["붙잡고 있던 <{items}> 자리가", "미뤄 뒀던 <{items}> 문제가"],
                move=["먼저 흔들리기 시작하고", "더는 그대로 못 있게 되고"],
                gain=["옮긴 자리에서 새 사람이 붙어", "정리한 자리로 새 기회가 들어와", "놓은 만큼 다른 문이 열려"],
                strong_items=MOVE_ITEMS, strong=["강하다", "먼저 움직인다", "피할 수 없다"]),
    "본인": dict(items=BLOCKED, blocked=["남 따라가던 <{items}> 기준이", "흐려졌던 <{items}> 기준이"],
                move=["다시 세워지기 시작하고", "내 쪽으로 돌아오기 시작하고"],
                gain=["내 자리로 사람이 돌아와", "기준을 잡는 순간 사람이 붙어", "정리한 만큼 길이 선명해져"],
                strong_items=OPEN_ITEMS, strong=["다시 정해진다", "판이 새로 짜인다", "기준이 선다"]),
    "평년": dict(items=BLOCKED, blocked=["그동안 밀어 둔 <{items}> 쪽이", "급하게 안 풀리던 <{items}> 쪽이"],
                move=["조용히 자리 잡기 시작하고", "천천히 제자리 찾기 시작하고"],
                gain=["급하지 않게 사람이 붙어", "서두르지 않은 자리에 귀인이 와", "다진 만큼 내년에 그대로 올라와"],
                strong_items=CALM_ITEMS, strong=["쌓인다", "내년 판이 된다", "남는다"]),
}

# ⑦ 시점
TIMINGS = ["하반기 어떤 결정을 하느냐가 중요해", "10월 들어가기 전에 하나는 정해", "연말까지 석 달, 여기서 갈려",
           "지금부터 12월까지가 판 짜는 구간이야", "가을 지나기 전에 방향 잡아", "올해 안에 한 번은 움직여야 해"]

# ⑧ 신뢰 한 줄
TRUSTS = ["돌려 말 안 해", "좋은 말만 안 해준다", "희망고문 안 해", "나 돌려 말 안 한다", "좋은 말만 골라 주는 데 아니야"]

# ⑨ 행동 요구. 사람이 봐주는 게 아니라 표(만세력) 그대로. 문턱 = 링크에서 30초
ACTIONS = ["{a}띠는 네 년생 넣으면 30초. 링크는 첫 답글에", "생일 댓글 안 남겨도 돼. 네 년생은 링크에서 30초면 나와",
           "사람이 봐주는 데 아니야, 표 그대로 뽑아줘. 네 년생 30초, 첫 답글 링크", "{a}띠 네 년생만 넣어. 30초, 링크는 아래 답글",
           "댓글 기다릴 필요 없어. 네 년생은 링크에서 30초"]

# ⑩ 마무리
CLOSINGS = {
    "열림": ["너, 이제 시동 걸린 채로 간다.", "너, 조용히 큰길로 올라탄다.", "너, 기다린 만큼 한꺼번에 온다.", "너, 이제 밀린 게 순서대로 온다."],
    "이동": ["너, 서 있으려 해도 길이 먼저 움직인다.", "너, 놓는 순간 다음 자리가 보인다.", "너, 올해 옮긴 자리가 몇 년을 정한다."],
    "본인": ["너, 올해 다시 짠 판이 오래 간다.", "너, 남 기준 내려놓으면 바로 풀린다.", "너, 올해가 기준점이다."],
    "평년": ["너, 지금 쌓는 게 내년에 그대로 올라온다.", "너, 서두르지만 않으면 남는다.", "너, 조용한 해가 제일 많이 남긴다."],
}

# ⑪ 복채
FEES = ["복채는 스하리로 받을게", "복채는 스크랩 하트 리포스트", "복채는 스하리면 충분해", "복채는 스하리. 그거면 돼"]


# ── 이번 달(절기 월) ────────────────────────────────────────────────────
# 2026-09-23 사장님 지시. 우리 글은 전부 "올해 병오년"이라 급해 보이지 않았다.
# 잘 되는 계정(@taebaek_saju, 팔로워 5.8만)은 "지금 정유월은 금 기운 달이라"처럼 **이번 달**을 매번 건다.
# 절기 시작일은 엔진에서 미리 받아 월건표.json 에 굳혀 뒀다(액션엔 엔진이 없다). 2027-12 까지 들어 있음.
MONTH_TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "월건표.json")

# 오행별 한마디. "이번 달이 어떤 기운인지" 한 줄로만 — 풀이는 안 한다.
MONTH_NOTE = {
    "목": ["뻗어 나가는 기운이 도는 달이야", "새로 벌이는 기운이 도는 달이야"],
    "화": ["드러나고 퍼지는 기운이 도는 달이야", "속도가 붙는 기운이 도는 달이야"],
    "토": ["쌓이고 눌러앉는 기운이 도는 달이야", "자리를 다지는 기운이 도는 달이야"],
    "금": ["끊고 정리하는 기운이 도는 달이야", "결론이 나는 기운이 도는 달이야"],
    "수": ["가라앉고 모으는 기운이 도는 달이야", "안으로 파고드는 기운이 도는 달이야"],
}


def this_month(day=None):
    """오늘이 속한 절기 월. 표에 없으면 None → 글에서 그 줄을 통째로 뺀다(억지로 안 쓴다)."""
    try:
        with open(MONTH_TABLE, encoding="utf-8") as f:
            rows = json.load(f)["달"]
    except Exception:
        return None
    key = (day or datetime.now(KST).date()).isoformat()
    cur = [r for r in rows if r["시작"] <= key]
    return cur[-1] if cur else None


def month_line(rng, day=None):
    """"지금 정유월은 끊고 정리하는 기운이 도는 달이야" 한 줄. 표에 없으면 None."""
    m = this_month(day)
    if not m:
        return None
    return "지금 %s월은 %s" % (m["월건"], rng.choice(MONTH_NOTE.get(m["오행"], ["기운이 도는 달이야"])))


# ── 엔진: 띠별 년생·올해 관계 ───────────────────────────────────────────
def load_table(base=BASE_YEAR):
    """{띠: {"years": [...], "relation": "삼합|육합|충|같은띠|"}}. 엔진 한 번 부르고 cache/ 에 둔다."""
    path = CACHE % base
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    cmd = ["npx", "tsx", os.path.join(os.path.dirname(STORE), "saju_rows.ts"), "all", str(base), "1940", "2010"]
    r = subprocess.run(cmd, cwd=ARCADE, capture_output=True, text=True, encoding="utf-8", shell=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("엔진 실행 실패: " + (r.stderr or "")[-400:])
    table = {}
    for row in json.loads(r.stdout)["rows"]:
        a = row["animal"].replace("띠", "")
        t = table.setdefault(a, {"years": [], "relation": row["relation"]})
        t["years"].append(row["year"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, indent=1)
    return table


ADULT_BORN_MAX = 2007        # 글에 적는 년생은 어른만 (2026-09-22 사장님 "어른만 하자"). 2008 이후 = 미성년 = 답글 기계도 안 봄


def pick_years(years, rng):
    """1960 이후 ~ 어른(ADULT_BORN_MAX)까지에서 연속 세 바퀴(예: 1983 / 1995 / 2007). 명운재 상위 글 표기와 같다.
    2000년대 어른(2000~2007)도 들어간다. 2008 이후(미성년)는 글에 안 적는다 — 부르고 나서 답글 기계가 내치면 안 되니까."""
    ys = [y for y in years if 1960 <= y <= ADULT_BORN_MAX]
    start = rng.randrange(0, max(1, len(ys) - 2))
    return ys[start:start + 3]


# ── 검사 ───────────────────────────────────────────────────────────────
def check(text):
    """문제 목록. 비면 통과."""
    bad = []
    for w in BANNED:
        if w in text:
            bad.append("금지어 " + w)
    if len(text) > TEXT_MAX:
        bad.append("%d자 (500 초과)" % len(text))
    if "#" in text:
        bad.append("해시태그")
    if "http" in text or "sajuarcade" in text:
        bad.append("본문 링크")
    return bad


def load_record():
    if not os.path.exists(RECORD):
        return []
    with open(RECORD, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def add_record(entry_id, animal, hook, text, theme="흐름"):
    with open(RECORD, "a", encoding="utf-8") as f:
        f.write(json.dumps({"날짜": datetime.now().strftime("%Y-%m-%d %H:%M"), "id": entry_id, "띠": animal, "훅": hook, "주제": theme, "text": text}, ensure_ascii=False) + "\n")



# ── 주제 (2026-09-22 사장님 지시 "돈만 하면 안 돼, 조화롭게") ─────────────────────────────
# 골격은 같고(훅 → 띠 → 기질 → 흐름 → 막힘/움직임/귀인 → 유난히 <항목> → 시점 → 신뢰 → 행동 → 마무리 → 복채)
# 주제마다 훅·흐름·항목·시점·마무리만 다르다. 띠·년생·엔진 관계(열림/이동/본인/평년)는 그대로 쓴다.
# "흐름" = 2026-09-18 부터 쓰던 원래 틀(build). 돈 글도 "얼마 번다"가 아니라 "어디서 새는지 / 언제 자리가 열리는지"(걱정을 짚는 톤).
THEME_WEIGHTS = {"흐름": 25, "돈": 30, "관계": 20, "기질": 15, "시기": 10}
THEME_MAX_RECENT = {"돈": (6, 2)}       # 최근 6개 중 돈은 2개까지 (돈돈거리지 않게)
THEME_NO_REPEAT = 2                      # 바로 앞 2개와 같은 주제는 피한다

# "유난히" 줄(다음 줄이 가림 대상). 주제별로 문구가 다르다
MARKERS = {"흐름": "올해는 유난히", "돈": "올해 돈은 유난히", "관계": "올해 사람은 유난히", "기질": "이런 날 유난히", "시기": "지금은 유난히"}

MONEY_IN = ["기다리던 돈", "밀린 돈", "새 수입 길", "자리 값 올라가기", "빌려준 돈 돌아오기", "부업 자리", "계약 마무리", "값 제대로 받기"]
MONEY_OUT = ["사람한테 새는 돈", "충동으로 새는 돈", "미룬 정리 때문에 새는 돈", "체면 때문에 나가는 돈", "구독·습관으로 새는 돈", "남 대신 내는 돈"]
MONEY_KEEP = ["돈 계획 다시 짜기", "새는 구멍 막기", "자리 지키기", "값 올려 부르기 준비", "빚 줄이기", "내년 자금 만들기"]
REL_IN = ["새 인연", "오래된 인연 다시 닿기", "귀인 소개", "가족 화해", "연락 끊긴 사람", "같이 일할 사람", "마음 열리는 사람"]
REL_CUT = ["질질 끌던 관계", "말만 앞서는 사람", "기 빨리는 사람", "받기만 하는 사람", "애매하게 걸쳐 둔 사이", "돈 얽힌 사람"]
REL_KEEP = ["곁에 남을 사람 가리기", "연락 정리", "가족 시간", "오래 볼 사람 챙기기", "혼자 있는 시간", "말 줄이기"]
TIME_DO = ["미룬 결정", "연락 한 통", "계약 마무리", "자리 옮기기", "정리 시작", "말 꺼내기", "값 정하기"]
TIME_WAIT = ["큰 결정", "돈 얽힌 약속", "새 시작", "사람 들이기", "말싸움", "계약 서명"]

THEMES = {
  "돈": dict(
    hooks=["나 {a}띠 돈 자리 보다가 손이 멈췄잖아", "나 오늘 {a}띠 돈 얘기만 한다", "나 돌려 말 안 해. {a}띠 돈 자리부터 본다",
           "나 {a}띠 올해 돈 흐름 보고 그냥 못 지나가겠더라", "나 {a}띠 돈 새는 자리 짚고 갈게", "나 좋은 말만 안 해. {a}띠 돈은 이거야"],
    flows={"열림": ["올해는 {a}띠 돈 자리로 바람이 들어오는 해야. 묵혀 뒀던 돈이 움직이기 시작해",
                  "{a}띠는 올해 돈 문이 열리는 구조야. 대신 새는 구멍부터 막아야 남아"],
           "이동": ["올해 {a}띠는 돈 나오는 자리가 바뀌는 해야. 붙잡고 있던 자리에서 계속 새",
                  "{a}띠는 올해 돈줄을 옮기는 해야. 미룰수록 새는 돈이 커져"],
           "본인": ["올해는 {a}띠 본인 해라 돈 기준을 다시 잡는 해야. 작년 씀씀이로 가면 안 맞아",
                  "{a}띠는 올해 돈 판을 새로 짜는 해야. 여기서 짠 게 몇 년을 가"],
           "평년": ["올해 {a}띠 돈은 크게 들어오기보다 새는 걸 막아서 남기는 해야",
                  "{a}띠는 올해 돈이 조용히 쌓이는 해야. 서두르면 잃고 다지면 남아"]},
    blocked={"열림": ["막혀 있던 <{items}> 쪽이"], "이동": ["붙잡고 있던 <{items}> 자리가"], "본인": ["흐려졌던 <{items}> 기준이"], "평년": ["급하게 안 풀리던 <{items}> 쪽이"]},
    items={"열림": MONEY_IN, "이동": MONEY_OUT, "본인": MONEY_KEEP, "평년": MONEY_KEEP},
    move={"열림": ["다시 움직이기 시작하고", "순서대로 들어오기 시작하고"], "이동": ["먼저 티가 나기 시작하고", "더는 못 본 척 못 하게 되고"],
          "본인": ["내 쪽으로 돌아오기 시작하고", "다시 세워지기 시작하고"], "평년": ["조용히 자리 잡기 시작하고", "천천히 메워지기 시작하고"]},
    gain={"열림": ["막혔던 자리에 돈 가져오는 사람이 나타나", "기다리던 돈과 사람이 같이 들어와"],
          "이동": ["구멍 막은 만큼 다른 문이 열려", "옮긴 자리에서 값이 달라져"],
          "본인": ["기준 잡는 순간 새는 게 멈춰", "정리한 만큼 남는 게 늘어"],
          "평년": ["서두르지 않은 자리에 돈이 남아", "다진 만큼 내년에 그대로 올라와"]},
    strong={"열림": (MONEY_IN, ["열린다", "강하다", "눈에 띈다"]), "이동": (MONEY_OUT, ["새기 쉽다", "먼저 티 난다", "조심할 자리다"]),
            "본인": (MONEY_KEEP, ["다시 정해진다", "판이 새로 짜인다"]), "평년": (MONEY_KEEP, ["쌓인다", "남는다", "내년 밑천이 된다"])},
    timings=["10월 들어가기 전에 새는 구멍 하나는 막아", "연말까지 석 달, 돈은 여기서 갈려", "하반기 돈은 어디에 쓰느냐가 중요해", "올해 안에 돈 계획 한 번은 다시 짜"],
    closings={"열림": ["너, 막힌 데 뚫리면 한꺼번에 들어온다.", "너, 새는 것만 막으면 올해 남는다."],
              "이동": ["너, 자리 옮기면 값이 달라진다.", "너, 놓는 순간 새는 게 멈춘다."],
              "본인": ["너, 올해 짠 돈 판이 오래 간다.", "너, 남 기준 내려놓으면 돈이 남는다."],
              "평년": ["너, 조용히 쌓는 해가 제일 남는다.", "너, 지금 막은 구멍이 내년 밑천이다."]}),
  "관계": dict(
    hooks=["나 {a}띠 사람 자리 보다가 한참 들여다봤다", "나 오늘 {a}띠 인연 얘기만 한다", "나 돌려 말 안 해. {a}띠 사람 문제부터 본다",
           "나 {a}띠 올해 인연 흐름 보고 그냥 못 지나가겠더라", "나 {a}띠 곁에 남을 사람 짚고 갈게", "나 좋은 말만 안 해. {a}띠 사람은 이거야"],
    flows={"열림": ["올해는 {a}띠 자리로 사람이 들어오는 해야. 끊겼던 연락이 먼저 움직여",
                  "{a}띠는 올해 인연 문이 열리는 구조야. 대신 가려 받아야 남아"],
           "이동": ["올해 {a}띠는 사람이 갈리는 해야. 붙잡고 있던 관계가 먼저 흔들려",
                  "{a}띠는 올해 사람을 정리하는 해야. 놓는 만큼 새 사람이 들어와"],
           "본인": ["올해는 {a}띠 본인 해라 사람 기준을 다시 잡는 해야. 작년 기준으로 만나면 안 맞아",
                  "{a}띠는 올해 내 곁을 새로 짜는 해야. 여기서 남은 사람이 오래 가"],
           "평년": ["올해 {a}띠 인연은 새로 늘기보다 있는 사람이 깊어지는 해야",
                  "{a}띠는 올해 사람이 조용히 자리 잡는 해야. 서두르면 놓치고 다지면 남아"]},
    blocked={"열림": ["막혀 있던 <{items}> 쪽이"], "이동": ["붙잡고 있던 <{items}> 자리가"], "본인": ["흐려졌던 <{items}> 기준이"], "평년": ["급하게 안 풀리던 <{items}> 쪽이"]},
    items={"열림": REL_IN, "이동": REL_CUT, "본인": REL_KEEP, "평년": REL_KEEP},
    move={"열림": ["다시 닿기 시작하고", "순서대로 풀리기 시작하고"], "이동": ["먼저 흔들리기 시작하고", "더는 그대로 못 있게 되고"],
          "본인": ["내 쪽으로 돌아오기 시작하고", "다시 세워지기 시작하고"], "평년": ["조용히 자리 잡기 시작하고", "천천히 깊어지기 시작하고"]},
    gain={"열림": ["막혔던 자리에 귀인이 나타나", "멈췄던 연락이 다시 닿기 시작해"],
          "이동": ["정리한 자리로 새 사람이 들어와", "놓은 만큼 다른 사람이 붙어"],
          "본인": ["기준을 잡는 순간 사람이 가려져", "정리한 만큼 곁이 선명해져"],
          "평년": ["급하지 않게 사람이 붙어", "다진 만큼 오래 가는 사람이 남아"]},
    strong={"열림": (REL_IN, ["열린다", "강하다", "눈에 띈다"]), "이동": (REL_CUT, ["먼저 갈린다", "정리된다", "피할 수 없다"]),
            "본인": (REL_KEEP, ["다시 정해진다", "기준이 선다"]), "평년": (REL_KEEP, ["깊어진다", "남는다", "오래 간다"])},
    timings=["10월 들어가기 전에 연락 하나는 정리해", "연말까지 석 달, 사람은 여기서 갈려", "하반기 누구 곁에 있느냐가 중요해", "올해 안에 한 번은 마음을 열어"],
    closings={"열림": ["너, 기다린 사람이 먼저 온다.", "너, 가려 받으면 올해 곁이 든든해진다."],
              "이동": ["너, 놓는 순간 다음 사람이 보인다.", "너, 정리한 자리에 오래 갈 사람이 온다."],
              "본인": ["너, 올해 남긴 사람이 오래 간다.", "너, 남 기준 내려놓으면 사람이 편해진다."],
              "평년": ["너, 조용히 깊어지는 해가 제일 남는다.", "너, 지금 곁에 있는 사람이 내년 귀인이다."]}),
  "기질": dict(
    hooks=["나 {a}띠 사람들 보면 꼭 이래", "나 오늘 {a}띠 속마음 하나 짚는다", "나 {a}띠 표 보다가 웃었잖아. 너무 나야",
           "나 돌려 말 안 해. {a}띠 이래서 지쳐", "나 {a}띠 지치는 이유 알겠더라", "나 좋은 말만 안 해. {a}띠 이거 맞지"],
    flows={"열림": ["근데 올해는 {a}띠 그 기질이 제대로 먹히는 해야. 그동안 안 통하던 게 통하기 시작해",
                  "{a}띠는 올해 그 성격이 길을 여는 해야. 억누르지 말고 써"],
           "이동": ["근데 올해 {a}띠는 그 기질 때문에 자리가 흔들리는 해야. 같은 방식으로 버티면 안 맞아",
                  "{a}띠는 올해 그 성격을 조금 바꿔 써야 하는 해야. 안 그러면 계속 부딪혀"],
           "본인": ["올해는 {a}띠 본인 해라 그 기질이 제일 진하게 나오는 해야. 좋은 쪽도 지치는 쪽도",
                  "{a}띠는 올해 자기 성격이랑 정면으로 마주치는 해야"],
           "평년": ["올해 {a}띠는 그 기질을 조용히 다듬는 해야. 큰 사건보다 습관이 갈려",
                  "{a}띠는 올해 그 성격이 크게 흔들리진 않아. 대신 지치는 자리가 정해져 있어"]},
    blocked={"열림": ["막혀 있던 <{items}> 쪽이"], "이동": ["버릇처럼 붙잡던 <{items}> 쪽이"], "본인": ["흐려졌던 <{items}> 기준이"], "평년": ["급하게 안 풀리던 <{items}> 쪽이"]},
    items={"열림": BLOCKED, "이동": MOVE_ITEMS[:6], "본인": BLOCKED, "평년": BLOCKED},
    move={"열림": ["다시 움직이기 시작하고", "순서대로 풀리기 시작하고"], "이동": ["먼저 흔들리기 시작하고", "더는 그대로 못 있게 되고"],
          "본인": ["내 쪽으로 돌아오기 시작하고", "다시 세워지기 시작하고"], "평년": ["조용히 자리 잡기 시작하고", "천천히 제자리 찾기 시작하고"]},
    gain={"열림": ["기질 그대로 밀어도 사람이 붙어", "안 통하던 자리에 귀인이 나타나"],
          "이동": ["방식 하나 바꾼 자리에서 새 사람이 붙어", "놓은 만큼 다른 문이 열려"],
          "본인": ["나답게 가는 순간 사람이 붙어", "기준을 잡는 순간 길이 선명해져"],
          "평년": ["서두르지 않은 자리에 귀인이 와", "다진 만큼 내년에 그대로 올라와"]},
    strong={"열림": (OPEN_ITEMS, ["강하다", "열리는 해다", "눈에 띈다"]), "이동": (MOVE_ITEMS, ["먼저 움직인다", "피할 수 없다"]),
            "본인": (OPEN_ITEMS, ["다시 정해진다", "기준이 선다"]), "평년": (CALM_ITEMS, ["쌓인다", "남는다"])},
    timings=["하반기 어떤 결정을 하느냐가 중요해", "10월 들어가기 전에 하나는 정해", "가을 지나기 전에 방향 잡아", "올해 안에 한 번은 움직여야 해"],
    closings={"열림": ["너, 그 성격 그대로 가도 된다.", "너, 억누르던 걸 풀면 길이 열린다."],
              "이동": ["너, 방식 하나만 바꾸면 안 부딪힌다.", "너, 놓는 순간 다음 자리가 보인다."],
              "본인": ["너, 올해는 나답게 가는 게 답이다.", "너, 남 기준 내려놓으면 바로 풀린다."],
              "평년": ["너, 지치는 자리만 피하면 남는다.", "너, 조용한 해가 제일 단단하다."]}),
  "시기": dict(
    hooks=["나 {a}띠 이번 달 표 보다가 손이 멈췄잖아", "나 오늘 {a}띠 타이밍 하나만 짚는다", "나 돌려 말 안 해. {a}띠 지금 움직일 때야",
           "나 {a}띠 이번 달 흐름 보고 그냥 못 지나가겠더라", "나 {a}띠 언제 움직일지 짚고 갈게", "나 좋은 말만 안 해. {a}띠 지금 이거야"],
    flows={"열림": ["{a}띠는 지금이 올해 중에 문이 제일 열려 있는 구간이야. 미루면 다음 자리는 내년이야",
                  "올해 {a}띠는 지금 움직이는 게 제일 순하게 풀리는 때야"],
           "이동": ["{a}띠는 지금 자리가 흔들리는 구간이야. 버티는 것보다 옮길 자리를 정하는 때",
                  "올해 {a}띠는 지금이 정리하고 옮기는 구간이야. 미룰수록 선택지가 줄어"],
           "본인": ["{a}띠는 본인 해라 지금이 기준을 다시 잡는 구간이야. 여기서 정한 게 오래 가",
                  "올해 {a}띠는 지금이 판을 새로 짜는 때야"],
           "평년": ["{a}띠는 지금 큰 바람은 없는 구간이야. 대신 지금 다진 게 내년 초에 그대로 올라와",
                  "올해 {a}띠는 지금 조용히 준비하는 때야. 서두르면 잃고 다지면 남아"]},
    blocked={"열림": ["미뤄 뒀던 <{items}> 쪽이"], "이동": ["붙잡고 있던 <{items}> 자리가"], "본인": ["흐려졌던 <{items}> 기준이"], "평년": ["급하게 안 풀리던 <{items}> 쪽이"]},
    items={"열림": TIME_DO, "이동": TIME_DO, "본인": TIME_DO, "평년": TIME_WAIT},
    move={"열림": ["지금 움직이면 순서대로 풀리고", "지금 꺼내면 바로 답이 오고"], "이동": ["먼저 흔들리기 시작하고", "더는 그대로 못 있게 되고"],
          "본인": ["내 쪽으로 돌아오기 시작하고", "다시 세워지기 시작하고"], "평년": ["지금은 조용히 두는 게 맞고", "서두르면 오히려 틀어지고"]},
    gain={"열림": ["지금 움직인 자리에 귀인이 나타나", "미룬 걸 꺼내는 순간 사람이 붙어"],
          "이동": ["옮긴 자리에서 새 사람이 붙어", "놓은 만큼 다른 문이 열려"],
          "본인": ["기준을 잡는 순간 사람이 붙어", "정리한 만큼 길이 선명해져"],
          "평년": ["기다린 자리에 때가 맞춰 와", "다진 만큼 내년 초에 그대로 올라와"]},
    strong={"열림": (TIME_DO, ["지금 해야 한다", "지금이 때다", "미루면 늦는다"]), "이동": (TIME_DO, ["먼저 움직인다", "피할 수 없다"]),
            "본인": (TIME_DO, ["지금 정해야 한다", "기준이 선다"]), "평년": (TIME_WAIT, ["미뤄야 한다", "지금은 아니다", "내년 초가 맞다"])},
    timings=["이번 달 넘기기 전에 하나는 해", "10월 들어가기 전에 하나는 정해", "연말까지 석 달, 여기서 갈려", "가을 지나기 전에 방향 잡아"],
    closings={"열림": ["너, 지금 움직이면 한꺼번에 온다.", "너, 이번 달이 올해 문이다."],
              "이동": ["너, 놓는 순간 다음 자리가 보인다.", "너, 올해 옮긴 자리가 내년을 정한다."],
              "본인": ["너, 지금 잡은 기준이 오래 간다.", "너, 올해가 기준점이다."],
              "평년": ["너, 기다리는 것도 움직이는 거다.", "너, 지금 다진 게 내년 초에 그대로 온다."]}),
}
TIMING_FRONT_EXTRA = {"10월 들어가기 전에 새는 구멍 하나는 막아": "10월 들어가기 전에", "연말까지 석 달, 돈은 여기서 갈려": "연말까지 석 달",
                      "하반기 돈은 어디에 쓰느냐가 중요해": "하반기 돈은 어디에 쓰느냐가", "올해 안에 돈 계획 한 번은 다시 짜": "올해 안에 돈 계획 한 번은",
                      "10월 들어가기 전에 연락 하나는 정리해": "10월 들어가기 전에", "연말까지 석 달, 사람은 여기서 갈려": "연말까지 석 달",
                      "하반기 누구 곁에 있느냐가 중요해": "하반기 누구 곁에 있느냐가", "올해 안에 한 번은 마음을 열어": "올해 안에 한 번은",
                      "이번 달 넘기기 전에 하나는 해": "이번 달 넘기기 전에"}


def pick_theme(rng, recent):
    """최근 기록을 보고 주제를 고른다. 바로 앞 THEME_NO_REPEAT 개와 같은 주제·돈 상한을 피한 뒤 가중치 랜덤."""
    themes = [r.get("주제", "흐름") for r in recent if r.get("종류", "띠") == "띠"]
    avoid = set(themes[-THEME_NO_REPEAT:])
    for th, (n, cap) in THEME_MAX_RECENT.items():
        if themes[-n:].count(th) >= cap:
            avoid.add(th)
    cands = [(th, w) for th, w in THEME_WEIGHTS.items() if th not in avoid] or list(THEME_WEIGHTS.items())
    return rng.choices([c[0] for c in cands], weights=[c[1] for c in cands])[0]


def build_theme(animal, table, rng, theme):
    """주제 틀로 한 벌 조립. (글, 훅번호)"""
    T = THEMES[theme]
    t = table[animal]
    kind = RELATION_KIND.get(t["relation"], "평년")
    years = pick_years(t["years"], rng)
    hook_i = rng.randrange(len(T["hooks"]))
    lines = []
    if SPEAKER:
        lines.append("나 %s." % SPEAKER)
    lines.append(T["hooks"][hook_i].format(a=animal))
    lines.append("%s %s띠(%s)" % (EMOJI[animal], animal, " / ".join(str(y) for y in years)))
    lines.append(rng.choice(TRAITS[animal]))
    lines.append(rng.choice(T["flows"][kind]).format(a=animal))
    ml = month_line(rng)                      # 이번 달 한 줄 (표에 없으면 건너뜀)
    if ml:
        lines.append(ml)
    items = " · ".join(rng.sample(T["items"][kind], 3))
    lines.append(rng.choice(T["blocked"][kind]).format(items=items))
    lines.append(rng.choice(T["move"][kind]))
    lines.append(rng.choice(T["gain"][kind]))
    strong_items, strong_words = T["strong"][kind]
    strong = " · ".join(rng.sample(strong_items, min(rng.choice([4, 5]), len(strong_items))))
    lines.append(MARKERS[theme])
    lines.append("<%s> %s" % (strong, rng.choice(strong_words)))
    lines.append(rng.choice(T["timings"]))
    lines.append(rng.choice(TRUSTS))
    lines.append(rng.choice(ACTIONS).format(a=animal))
    lines.append(rng.choice(T["closings"][kind]))
    lines.append(rng.choice(FEES))
    return "\n".join(lines), hook_i


# ── 생성 ───────────────────────────────────────────────────────────────
def build(animal, table, rng):
    """골격대로 한 벌 조립. (글, 훅번호)"""
    t = table[animal]
    kind = RELATION_KIND.get(t["relation"], "평년")
    years = pick_years(t["years"], rng)
    hook_i = rng.randrange(len(HOOKS))
    lines = []
    if SPEAKER:
        lines.append("나 %s." % SPEAKER)
    lines.append(HOOKS[hook_i].format(a=animal))
    lines.append("%s %s띠(%s)" % (EMOJI[animal], animal, " / ".join(str(y) for y in years)))
    lines.append(rng.choice(TRAITS[animal]))
    lines.append(rng.choice(FLOWS[kind]).format(a=animal))
    ml = month_line(rng)                      # 이번 달 한 줄 (표에 없으면 건너뜀)
    if ml:
        lines.append(ml)
    pool = POOLS[kind]
    items = " · ".join(rng.sample(pool["items"], 3))
    lines.append(rng.choice(pool["blocked"]).format(items=items))
    lines.append(rng.choice(pool["move"]))
    lines.append(rng.choice(pool["gain"]))
    strong = " · ".join(rng.sample(pool["strong_items"], rng.choice([4, 5])))
    lines.append("올해는 유난히")
    lines.append("<%s> %s" % (strong, rng.choice(pool["strong"])))
    lines.append(rng.choice(TIMINGS))
    lines.append(rng.choice(TRUSTS))
    lines.append(rng.choice(ACTIONS).format(a=animal))
    lines.append(rng.choice(CLOSINGS[kind]))
    lines.append(rng.choice(FEES))
    return "\n".join(lines), hook_i


def generate(animal=None, rng=None, recent=None, tries=40, theme=None):
    """검사 통과한 글 하나. recent = 최근 기록(띠+주제+훅 겹침 검사). theme 없으면 pick_theme(). 못 만들면 RuntimeError."""
    rng = rng or random.Random()
    table = load_table()
    recent = load_record()[-RECENT:] if recent is None else recent
    theme = theme or pick_theme(rng, recent)
    used = {(r.get("띠"), r.get("주제", "흐름"), r.get("훅")) for r in recent}
    texts = {r.get("text") for r in recent}
    last_animals = [r.get("띠") for r in recent[-3:]]       # 바로 앞 3개와 같은 띠는 피한다 (띠 지정 때는 예외)
    last_bad = []
    for _ in range(tries):
        a = animal or rng.choice([x for x in table if x not in last_animals] or list(table))
        text, hook_i = build(a, table, rng) if theme == "흐름" else build_theme(a, table, rng, theme)
        last_bad = check(text)
        if last_bad or text in texts or (a, theme, hook_i) in used:
            continue
        return {"animal": a, "hook": hook_i, "text": text, "theme": theme}
    raise RuntimeError("글 생성 실패: %s" % (", ".join(last_bad) or "최근 글과 계속 겹침"))


def entities(text, phrases):
    """AI가 고른 가릴 문구(글자 그대로) → API text_entities [{entity_type, offset, length}].
    AI는 숫자를 안 만진다. 위치는 여기서 잰다(파이썬 글자 단위 = 유니코드 코드포인트. API 단위는 미확인 → 첫 발행 때 확인).
    문구가 글에 없거나 두 번 나오거나 겹치면 ValueError. 최대 10개."""
    if not phrases:
        return []
    if len(phrases) > 10:
        raise ValueError("가릴 문구는 10개까지")
    spans = []
    for ph in phrases:
        ph = ph.strip()
        n = text.count(ph)
        if n == 0:
            raise ValueError("글에 없는 문구: " + ph)
        if n > 1:
            raise ValueError("두 번 이상 나오는 문구(더 길게 잡아): " + ph)
        off = text.index(ph)
        spans.append((off, len(ph)))
    spans.sort()
    for (a, la), (b, _) in zip(spans, spans[1:]):
        if a + la > b:
            raise ValueError("가릴 문구가 서로 겹침")
    return [{"entity_type": "SPOILER", "offset": o, "length": l} for o, l in spans]


# 시점 줄 앞부분(가림 기준 표: "언제"까지만 가리고 뒤 "하나는 정해"·"중요해"는 보이게)
TIMING_FRONT = {"하반기 어떤 결정을 하느냐가 중요해": "하반기 어떤 결정을 하느냐가", "10월 들어가기 전에 하나는 정해": "10월 들어가기 전에",
                "연말까지 석 달, 여기서 갈려": "연말까지 석 달", "지금부터 12월까지가 판 짜는 구간이야": "지금부터 12월까지가",
                "가을 지나기 전에 방향 잡아": "가을 지나기 전에", "올해 안에 한 번은 움직여야 해": "올해 안에 한 번은"}


def auto_hide(text):
    """스레드발행 스킬 '가림 기준' 표를 그대로 코드로: ① "올해는 유난히" 다음 줄(항목 줄) 통째 ② 시점 줄의 앞부분. 1~2곳.
    글에 두 번 나오는 문구는 건너뛴다(entities 가 거부). 돌려주는 것: text_entities 목록."""
    lines = text.split("\n")
    phrases = []
    for i, ln in enumerate(lines):
        if ln in MARKERS.values() and i + 1 < len(lines):      # 주제별 "유난히" 줄 다음 = 항목 줄 통째
            phrases.append(lines[i + 1])
        if ln in TIMING_FRONT:
            phrases.append(TIMING_FRONT[ln])
        elif ln in TIMING_FRONT_EXTRA:
            phrases.append(TIMING_FRONT_EXTRA[ln])
    ok = []
    for ph in phrases:
        try:
            entities(text, ok + [ph])
            ok.append(ph)
        except ValueError:
            continue
    return entities(text, ok)


def show_hidden(text, ents):
    """확인용: 가린 자리를 ▒ 로 바꿔 보여준다."""
    out, last = [], 0
    for e in sorted(ents, key=lambda x: x["offset"]):
        out.append(text[last:e["offset"]])
        out.append("▒" * e["length"])
        last = e["offset"] + e["length"]
    out.append(text[last:])
    return "".join(out)


def selftest(n):
    """n개 뽑아 중복·글자수·금지어 검사. 결과 한 줄."""
    rng = random.Random(1)
    table = load_table()
    animals = list(table)
    seen, lens, problems = set(), [], []
    for i in range(n):
        text, _ = build(animals[i % len(animals)], table, rng)
        bad = check(text)
        if bad:
            problems.append((i, bad))
        seen.add(text)
        lens.append(len(text))
    print("생성 %d개 / 서로 다른 글 %d개 / 글자수 %d~%d / 검사 걸린 것 %d개" % (n, len(seen), min(lens), max(lens), len(problems)))
    for i, bad in problems[:10]:
        print("  #%d %s" % (i, ", ".join(bad)))
    return len(seen) == n and not problems



# ── 하루 계획 (00시 넘어 첫 AI 가 부른다. 개수·시각·자리 종류를 기계가 정한다) ─────────────
PLAN_MIN, PLAN_MAX = 4, 6     # 2026-09-22 사장님 지시 "최소 4~6개, 시간은 올랜덤" (전엔 3~5)
# 시간대 6개 (사장님이 정한 4개를 살짝 넓히고 오전·오후 2개 추가). 한 자리엔 글 하나. 자리 안에서 분은 완전 랜덤.
SLOT_WINDOWS = {"아침": (7, 30, 8, 50), "오전": (10, 0, 11, 20), "낮": (11, 40, 13, 30),
                "오후": (15, 0, 16, 20), "저녁": (17, 30, 18, 50), "밤": (21, 0, 23, 30)}   # (시,분,시,분)
PERSON_EVERY_DAYS = 3        # 사람 글은 3~4일에 한 번
ANIMAL_EXTRA = 1             # 띠 글 2개(쇼츠와 같이) 말고 **추가로** 띠 자리 몇 개를 더 줄지.
                             # 2026-09-23 사장님 "일상글 한 단계 낮추자" → 1. 0 으로 되돌리면 예전 비율.


def plan_today(day=None, rng=None, last_person=None):
    """오늘 글 자리 4~6개(2026-09-22). 띠 글 2개(쇼츠와 같은 낮·밤)는 고정, 나머지는 일상글, 3~4일에 한 번 사람 글(저녁).
    돌려주는 것: [{"kind": "띠|일상|사람", "at": "YYYY-MM-DD HH:MM"}, ...] 시각순. 서로 1시간 이상 띄운다.
    last_person = 마지막 사람 글 날짜(str) 또는 None."""
    from datetime import datetime, timedelta
    rng = rng or random.Random()
    day = day or datetime.now().strftime("%Y-%m-%d")
    n = rng.randint(PLAN_MIN, PLAN_MAX)
    d0 = datetime.strptime(day, "%Y-%m-%d")

    def pick(win):
        h1, m1, h2, m2 = SLOT_WINDOWS[win]
        a, b = h1 * 60 + m1, h2 * 60 + m2
        t = rng.randint(a, b)
        return d0 + timedelta(minutes=t)

    slots = [("띠", pick("낮")), ("띠", pick("밤"))]
    person_due = True
    if last_person:
        person_due = (d0 - datetime.strptime(last_person, "%Y-%m-%d")).days >= rng.choice([PERSON_EVERY_DAYS, PERSON_EVERY_DAYS + 1])
    extra = ["아침", "오전", "오후", "저녁"]        # 띠 글이 낮·밤을 쓰니 나머지 4자리에서 랜덤으로 고른다
    rng.shuffle(extra)
    # 2026-09-23 사장님 지시 "일상글 한 단계 낮추자": 남는 자리 중 하나를 띠 글로 돌린다.
    # 일상 글이 하루 2.3개(45%)라 사주 얘기보다 많았다. 이 한 줄로 1.3개(26%)가 된다.
    animal_extra = ANIMAL_EXTRA
    for win in extra:
        if len(slots) >= n:
            break
        if person_due and win == "저녁" and not any(k == "사람" for k, _ in slots):
            kind = "사람"                          # 사람 글은 저녁(밤은 띠 글)
        elif not any(k == "증상" for k, _ in slots):
            # 증상 글 하루 1개 (2026-09-23). 띠를 안 부르고 '증상'으로 걸어서 12명 중 1명이 아니라 누구나 멈추게.
            # 유입은 띠 글에서만 나오는데(조회 3,874 vs 일상 30~280) 그 띠 사람만 멈추는 게 한계였다.
            kind = "증상"
        elif animal_extra > 0:
            kind, animal_extra = "띠", animal_extra - 1
        else:
            kind = "일상"
        slots.append((kind, pick(win)))
    # 일상 자리는 **반드시 하나 이상**. 개수가 3개로 뽑히고 사람 글이 걸린 날은
    # 띠2 + 사람1 이 돼서 일상이 0이 됐다(300번 중 27번 = 9%). 그러면 일진 글까지 같이 사라진다
    # — 일진은 '일상 자리 중 첫 번째'를 쓰기 때문(2026-09-21 오늘 실제로 하루치 0개가 나왔다).
    if not any(k == "일상" for k, _ in slots):
        used = {t.hour for _, t in slots}
        for win in extra:
            h1 = SLOT_WINDOWS[win][0]
            if not any(abs(h - h1) < 2 for h in used):
                slots.append(("일상", pick(win)))
                break
        else:
            slots.append(("일상", pick("아침")))

    slots.sort(key=lambda x: x[1])
    # 1시간 간격 보장: 겹치면 뒤로 민다
    for i in range(1, len(slots)):
        if (slots[i][1] - slots[i - 1][1]) < timedelta(hours=1):
            slots[i] = (slots[i][0], slots[i - 1][1] + timedelta(hours=1))
    # 뒤로 밀다가 **자정을 넘긴 자리는 버린다.**
    # 넘기면 그 글이 다음 날짜로 등록되고, 다음 날 하루치가 또 만들어져 글이 겹친다
    # (2026-09-21 확인: 300번 중 6번 = 2%. 9/22 에 띠 글이 3개가 된 원인으로 보인다).
    end = d0 + timedelta(days=1)
    slots = [s for s in slots if s[1] < end]
    return [{"kind": k, "at": t.strftime("%Y-%m-%d %H:%M")} for k, t in slots]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--animal", help="띠 (쥐·소·호랑이·토끼·용·뱀·말·양·원숭이·닭·개·돼지)")
    ap.add_argument("--n", type=int, help="시험: n개 생성해 검사")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--plan", action="store_true", help="오늘 하루 계획(개수·시각·자리)만 보여줌")
    args = ap.parse_args()
    if args.plan:
        for x in plan_today(rng=random.Random(args.seed)):
            print(x["at"], x["kind"])
        sys.exit(0)
    if args.n:
        sys.exit(0 if selftest(args.n) else 1)
    g = generate(args.animal, random.Random(args.seed))
    print(g["text"])
    print("\n(%s띠, %d자)" % (g["animal"], len(g["text"])))