# -*- coding: utf-8 -*-
"""일진 글 — 오늘 날짜의 사주(일진)로 "오늘 이런 사람 조심 / 이런 사람 좋은 날" 한마디 (2026-09-19 사장님 지시).
스레드하루치.py 가 일상 글 자리 하나를 이걸로 채운다. 제미나이 없음, 전부 규칙. 한자·전문어 없음(사장님 지시 "한자 없애").
    python 작업/일진글.py                 # 오늘 글 1개
    python 작업/일진글.py --day 2026-09-21 --n 5   # 그날 글 5개 뽑아 보기
틀 20개(일반 10 + 연애 5 + 재물 5). 날마다 일진이 바뀌니 같은 틀이라도 내용이 다르다. 60일 주기.
"""
import argparse
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import 스레드글   # check(): 금지어·500자·링크·해시태그

# ── 달력 ─────────────────────────────────────────────────────────────
GAN = "갑을병정무기경신임계"
JI = "자축인묘진사오미신유술해"
ANIMAL = ["쥐", "소", "호랑이", "토끼", "용", "뱀", "말", "양", "원숭이", "닭", "개", "돼지"]           # 지지 순서
GAN_EL = ["나무", "나무", "불", "불", "흙", "흙", "쇠", "쇠", "물", "물"]                              # 천간 오행(우리말)
JI_EL = ["물", "흙", "나무", "나무", "흙", "불", "불", "흙", "쇠", "쇠", "흙", "물"]
EL_COLOR = {"나무": "초록", "불": "빨강", "흙": "노랑", "쇠": "흰색", "물": "검정"}
EL_ITEM = {"나무": "화분이든 나무 소품이든", "불": "빨간 소품이든 조명이든", "흙": "노란 소품이든 도자기든", "쇠": "반지든 셔츠든", "물": "검은 옷이든 물병이든"}
# 오행 상극: 내가 이기는 것(=돈 자리), 나를 이기는 것(=일·남자 자리)
BEATS = {"나무": "흙", "흙": "물", "물": "불", "불": "쇠", "쇠": "나무"}
REF_DAY, REF_IDX = datetime(2026, 9, 19), 32     # 2026-09-19 = 병신(丙申) 일. 사이트 엔진(computeSaju)으로 확인. 60갑자 32번
CLASH = {0: 6, 1: 7, 2: 8, 3: 9, 4: 10, 5: 11}                       # 충(부딪힘): 자오·축미·인신·묘유·진술·사해
CLASH.update({v: k for k, v in CLASH.items()})
HARM = {0: 7, 1: 6, 2: 5, 3: 4, 8: 11, 9: 10}                        # 원진(신경 긁힘): 자미·축오·인사·묘진·신해·유술
HARM.update({v: k for k, v in HARM.items()})
SIX = {0: 1, 2: 11, 3: 10, 4: 9, 5: 8, 6: 7}                         # 육합(짝): 자축·인해·묘술·진유·사신·오미
SIX.update({v: k for k, v in SIX.items()})
TRI = [(8, 0, 4), (2, 6, 10), (5, 9, 1), (11, 3, 7)]                # 삼합: 신자진·인오술·사유축·해묘미
PEACH = {(8, 0, 4): 9, (2, 6, 10): 3, (5, 9, 1): 6, (11, 3, 7): 0}   # 삼합별 도화(인연 자리)
HOUR_TXT = {0: "밤 11시 넘어서", 1: "새벽 1~3시", 2: "새벽 3~5시", 3: "새벽 5~7시", 4: "아침 7~9시", 5: "오전 9~11시",
            6: "낮 11시~1시", 7: "오후 1~3시", 8: "오후 3~5시", 9: "저녁 5~7시", 10: "저녁 7~9시", 11: "밤 9~11시"}


def pillar(day):
    """날짜(datetime) → (천간 idx, 지지 idx). 일진은 절기와 무관한 60일 주기라 기준일에서 세면 된다."""
    i = (REF_IDX + (day - REF_DAY).days) % 60
    return i % 10, i % 12


def facts(day):
    g, j = pillar(day)
    tri = next(t for t in TRI if j in t)
    mates = [ANIMAL[x] for x in tri if x != j]
    g2, j2 = pillar(day + timedelta(days=1))
    good_hours = [HOUR_TXT[x] for x in tri if x != j]
    return {
        "animal": ANIMAL[j], "clash": ANIMAL[CLASH[j]], "harm": ANIMAL[HARM[j]] if j in HARM else None,
        "six": ANIMAL[SIX[j]] if j in SIX else None, "mates": mates, "mates_txt": " ".join(m + "띠" for m in mates),
        "el": JI_EL[j], "color": EL_COLOR[JI_EL[j]], "item": EL_ITEM[JI_EL[j]],
        "money_day": BEATS[GAN_EL[g]] == JI_EL[j],          # 일지가 일간이 이기는 오행 = 돈 자리(남자한텐 여자 자리)
        "boss_day": BEATS[JI_EL[j]] == GAN_EL[g],           # 일지가 일간을 이기는 오행 = 일·남자 자리
        "peach_tomorrow": PEACH[tri] == j2,                 # 내일이 이 삼합의 도화(인연) 날
        "hours": " , ".join(good_hours[:2]).replace(" , ", ", "),
        "tomorrow": ANIMAL[j2], "tomorrow_clash": ANIMAL[CLASH[j2]],
    }


# ── 틀 20개. {} 자리는 facts 로 채운다. 맨 줄은 질문 ────────────────
Q_ANY = ["너 오늘 어땠어?", "지금 뭐 하고 있었어?", "너 무슨 띠야?", "오늘 뭐 하나 걸린 거 있어?"]
TEMPLATES = [
    # 일반 10
    dict(key="경고", text="오늘 {animal} 날. {clash}띠는 부딪히는 날이야\n계약, 말싸움, 큰 결정 내일로 미뤄\n오늘 이미 뭐 하나 틀어진 사람 있지?"),
    dict(key="좋은날", text="{mates_txt} 오늘 {animal}랑 짝이 맞는 날이야\n미뤄둔 연락 오늘 해. 받는 쪽도 열려 있어\n누구한테 먼저 연락할 거야?"),
    dict(key="AB", need="six", text="오늘 같은 날 {six}띠는 사람 만나면 풀리고\n{clash}띠는 사람 만나면 꼬여\n너는 어느 쪽이야?"),
    dict(key="목록", text="{animal} 날 하지 말 것 3개\n1. {clash}띠랑 돈 얘기\n2. 오후에 새 일 시작\n3. 안 하던 말 하기\n너 오늘 몇 개 했어?"),
    dict(key="색", text="오늘 {el} 기운 센 날. 사주에 {el} 없는 사람은 뭔가 허전할 거야\n{color} 하나 걸치고 나가. {item}\n너 오늘 무슨 색 입었어?"),
    dict(key="시간", text="오늘은 {hours}가 {animal}랑 맞는 시간이야\n중요한 거 그 시간에 넣어\n지금 몇 시에 이 글 보고 있어?"),
    dict(key="관계", need="six", text="오늘 {six}띠 만나면 얘기 잘 풀려\n{clash}띠는 오늘만 피해. 내일 다시 봐\n지금 옆에 있는 사람 무슨 띠야?"),
    dict(key="돈날", need="money_day", text="오늘은 돈이 움직이는 날이야\n들어오든 나가든 오늘 통장 한 번 봐\n너 오늘 뭐 샀어?"),
    dict(key="썰", text="아침부터 뭐 하나 꼬여서 달력 봤더니 오늘 {animal} 날이더라\n{clash}띠는 오늘 그냥 조용히 보내. 나도 집에서 코드나 만졌어\n너희는 오늘 어땠어?"),
    dict(key="예고", text="내일 {tomorrow} 날. {tomorrow_clash}띠가 부딪혀\n오늘 밤에 미리 정리해 둬. 내일 아침 시끄러워\n{tomorrow_clash}띠 있어?"),
    # 연애 5
    dict(key="연애남", need="money_day", text="오늘은 남자한텐 여자 자리가 열리는 날이야\n눈에 들어오는 사람 있으면 그냥 넘기지 마\n너 오늘 누구 생각났어?"),
    dict(key="연애여", need="boss_day", text="오늘 여자한텐 남자 기운이 깔린 날이야\n겉으론 조용한데 연락 하나 온다. 씹지 마\n아직 안 왔어?"),
    dict(key="재회", need="peach_tomorrow", text="오늘은 헤어진 사람 생각나는 날이야. 옛 인연이 당겨\n근데 오늘 연락하면 도로 꼬여. 내일이 인연 날이야, 그때 해\n너 지금 폰 들었지?"),
    dict(key="썸", need="six", text="{six}띠랑 썸 타는 사람, 오늘 밥 먹자고 해. 맞는 날이야\n{clash}띠랑 썸이면 오늘 말 아껴. 한마디에 틀어져\n상대 무슨 띠야?"),
    dict(key="짜증", need="harm", text="오늘 {harm}띠랑은 이유 없이 신경 긁혀\n싸운 것도 아닌데 짜증나면 그거야. 오늘만 거리 둬\n지금 누구 때문에 짜증나?"),
    # 재물 5
    dict(key="돈들어옴", need="money_day", text="오늘 돈 글자가 뜬 날이야. 돈이 움직여\n받을 거 있으면 오늘 말해. 받는 쪽이 열려 있어\n누구한테 받을 거 있어?"),
    dict(key="돈나감", need="money_day", text="돈 움직이는 날은 나가기도 해. 오늘 충동구매 조심\n장바구니에 넣고 자. 내일 봐도 사고 싶으면 그때\n오늘 뭐 담았어?"),
    dict(key="돈띠", text="{mates_txt}는 오늘 돈 얘기 꺼내도 돼\n{clash}띠는 오늘 돈 얘기 하면 깨져\n너 오늘 돈 얘기 했어?"),
    dict(key="계약", need="el_metal", text="{el} 기운 센 날은 숫자·계약·서류가 잘 굴러가\n미뤄둔 견적, 월급 협상 오늘 던져\n던질 거 있어?"),
    dict(key="한방", text="오늘은 큰 거 한 방 아니고 작은 거 여러 개야\n복권 말고 미수금 챙겨. 그게 오늘 돈\n너 받을 돈 얼마 있어?"),
]


def usable(t, f):
    need = t.get("need")
    if not need:
        return True
    if need == "el_metal":
        return f["el"] == "쇠"
    return bool(f.get(need))


def generate(day=None, rng=None, avoid_keys=()):
    """그날 쓸 수 있는 틀 중 하나 골라 채운 글. avoid_keys = 최근 쓴 틀(안 겹치게)."""
    rng = rng or random.Random()
    d = datetime.strptime(day, "%Y-%m-%d") if isinstance(day, str) else (day or datetime.now())
    f = facts(d)
    pool = [t for t in TEMPLATES if usable(t, f) and t["key"] not in avoid_keys] or [t for t in TEMPLATES if usable(t, f)]
    for _ in range(20):
        t = rng.choice(pool)
        text = t["text"].format(**f)
        if not text.rstrip().endswith("?"):
            text = text.rstrip() + "\n" + rng.choice(Q_ANY)
        if not 스레드글.check(text):
            return {"text": text, "key": t["key"], "animal": f["animal"], "hook": t["key"]}
    raise RuntimeError("일진 글 생성 실패 (검사 계속 걸림)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--day")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--seed", type=int)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    d = datetime.strptime(a.day, "%Y-%m-%d") if a.day else datetime.now()
    g, j = pillar(d)
    f = facts(d)
    print("%s = %s%s 일 (%s 날) 부딪힘 %s / 짝 %s / 삼합 %s / 돈날 %s / 일날 %s" % (
        d.strftime("%Y-%m-%d"), GAN[g], JI[j], f["animal"], f["clash"], f["six"], f["mates_txt"], f["money_day"], f["boss_day"]))
    rng = random.Random(a.seed)
    used = []
    for _ in range(a.n):
        r = generate(d, rng, avoid_keys=used)
        used.append(r["key"])
        print("\n[%s]\n%s" % (r["key"], r["text"]))
