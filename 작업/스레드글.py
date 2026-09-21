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


def pick_years(years, rng):
    """1968 이후에서 연속 세 바퀴(예: 1984 / 1996 / 2008). 명운재 상위 글 표기와 같다."""
    ys = [y for y in years if y >= 1960]
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


def add_record(entry_id, animal, hook, text):
    with open(RECORD, "a", encoding="utf-8") as f:
        f.write(json.dumps({"날짜": datetime.now().strftime("%Y-%m-%d %H:%M"), "id": entry_id, "띠": animal, "훅": hook, "text": text}, ensure_ascii=False) + "\n")


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


def generate(animal=None, rng=None, recent=None, tries=40):
    """검사 통과한 글 하나. recent = 최근 기록(띠+훅 겹침 검사). 못 만들면 RuntimeError."""
    rng = rng or random.Random()
    table = load_table()
    recent = load_record()[-RECENT:] if recent is None else recent
    used = {(r.get("띠"), r.get("훅")) for r in recent}
    texts = {r.get("text") for r in recent}
    last_animals = [r.get("띠") for r in recent[-3:]]       # 바로 앞 3개와 같은 띠는 피한다 (띠 지정 때는 예외)
    last_bad = []
    for _ in range(tries):
        a = animal or rng.choice([x for x in table if x not in last_animals] or list(table))
        text, hook_i = build(a, table, rng)
        last_bad = check(text)
        if last_bad or text in texts or (a, hook_i) in used:
            continue
        return {"animal": a, "hook": hook_i, "text": text}
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
        if ln == "올해는 유난히" and i + 1 < len(lines):
            phrases.append(lines[i + 1])
        if ln in TIMING_FRONT:
            phrases.append(TIMING_FRONT[ln])
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
    for win in extra:
        if len(slots) >= n:
            break
        kind = "사람" if (person_due and win == "저녁" and not any(k == "사람" for k, _ in slots)) else "일상"   # 사람 글은 저녁(밤은 띠 글)
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