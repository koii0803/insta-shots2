# -*- coding: utf-8 -*-
"""페북 페이지(인생역전 운세명당) 릴스 캡션 생성기 (사주쇼츠업로드자동화 스킬, 2026-09-19).

2026-09-18 페북 실측(docs/페북수집/인기글.md) 결론: 댓글은 "댓글에 ○○ 남겨 주세요" 한 줄이 만들고, 띠 하나를 제목에 콕 집어야 멈추고,
40대 이상은 띠보다 년생으로 자기를 찾고, 존댓말 "~셨다면 / ~흐름입니다" 조건문, 가족(부모님·자녀) 각도. 영상은 껍데기, 글이 전부.
남들이 붙이는 주술 약속("기운이 닿습니다")·DM·선착순·횡재·빚·로또는 문구규칙 위반이라 뺀다. 댓글 유도는 예고형(A안, 사장님 확정 2026-09-19).

덩어리 8개, 빈 줄로 나눔 (사장님 확정 2026-09-19). 한 줄 25자 안쪽:
  ① 훅(화면 제목 첫 줄 그대로)  ② 주제 표 + 띠 하나(년생 3개)  ③ 조건 + 흐름(엔진 관계별)  ④ 표에 더 있다·본인 해·부모님 해
  ⑤ 사람 안 봐줌·만세력 표 + 가족  ⑥ 👉 링크  ⑦ 댓글 유도(예고형)  ⑧ 입춘·오락 고지
입력(meta.json): screen_hook(화면 제목 첫 줄), screen_topic(둘째 줄), rows [[year, 띠, ...], ...] 또는 rank1(순위 표 1등 띠).
grid.py 가 아직 안 적어 주는 편은 yt_title 에서 주제만 뽑아 띠 없는 예비 틀로 간다.

    python 페북글.py                # 시험 1개
    python 페북글.py --n 120        # 자검: 120개 뽑아 금지어·길이·링크 검사
"""
import os
import re
import sys
import json
import random
import argparse
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import 스레드글

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SITE = "https://sajuarcade.com"
ANIMALS = ["쥐", "소", "호랑이", "토끼", "용", "뱀", "말", "양", "원숭이", "닭", "개", "돼지"]
TEXT_MAX = 2000
BANNED = 스레드글.BANNED + ["횡재", "빚", "로또", "대박", "기운이 닿", "DM", "선착순", "봐드립니다", "풀어드립니다", "짚어드립니다"]

# ③ 조건 (관계별: 삼합·육합=열림 / 충=이동 / 같은띠=본인 / 나머지=평년). 존댓말, "~셨다면,"
COND = {
    "열림": ["오래 참아 온 일이 있으셨다면,", "미뤄 둔 결정이 마음에 걸려 계셨다면,", "올해 들어 사람 만날 일이 부쩍 늘었다 느끼셨다면,",
             "끊겼던 연락이 요즘 다시 오기 시작했다면,", "올해 유독 제안이 많이 들어온다 느끼셨다면,", "막혀 있던 일이 요즘 조금씩 움직인다 느끼셨다면,"],
    "이동": ["자리를 옮길까 오래 망설이셨다면,", "지금 있는 곳이 답답하게 느껴지셨다면,", "올해 유독 이사·이직 생각이 자주 드셨다면,",
             "정리하고 싶은 관계가 마음에 걸려 계셨다면,", "새 환경이 자꾸 눈에 들어오셨다면,", "올해는 뭔가 바꿔야겠다 싶으셨다면,"],
    "본인": ["올해가 본인 해라 조심하며 지내셨다면,", "올해 유난히 잔일이 많다 느끼셨다면,", "올해는 벌이는 것마다 손이 많이 갔다면,",
             "올해 들어 몸보다 마음이 먼저 지쳤다 느끼셨다면,", "올해는 지키는 데 힘을 다 쓰셨다면,"],
    "평년": ["올해가 유난히 조용하다 느끼셨다면,", "큰일 없이 버티는 한 해였다 느끼셨다면,", "티 안 나게 애쓴 시간이 길었다면,",
             "남 좋은 일만 한 것 같은 해였다면,", "올해는 뭘 해도 반응이 늦다 느끼셨다면,", "묵묵히 자리 지킨 시간이 길었다면,"],
}
# ③ 흐름. {m} = 다음 달 또는 이번 달
FLOW = {
    "열림": ["{m}월 들어 그 문이 하나씩 열리는 흐름입니다.", "{m}월부터 막혔던 자리가 풀리기 시작하는 흐름입니다.", "{m}월에 그동안의 정성이 자리를 잡는 흐름입니다.",
             "{m}월엔 사람을 통해 길이 나는 흐름입니다.", "{m}월은 미뤄 둔 것이 제자리를 찾는 흐름입니다.", "{m}월엔 오래 기다린 답이 오는 흐름입니다."],
    "이동": ["{m}월은 움직이면 길이 나는 흐름입니다. 서두르지만 않으시면 됩니다.", "{m}월 들어 옮길 자리가 눈에 들어오는 흐름입니다.",
             "{m}월엔 정리한 만큼 가벼워지는 흐름입니다.", "{m}월은 한 번 움직여 두면 내년이 편한 흐름입니다.", "{m}월엔 새 자리에서 사람이 붙는 흐름입니다."],
    "본인": ["{m}월은 벌이기보다 지키는 쪽이 남는 흐름입니다.", "{m}월엔 정리해 둔 것이 내년 힘이 되는 흐름입니다.", "{m}월은 조용히 넘기는 게 제일 남는 흐름입니다.",
             "{m}월엔 무리하지 않은 자리가 지켜지는 흐름입니다.", "{m}월은 쉬어 가는 게 곧 준비인 흐름입니다."],
    "평년": ["{m}월은 조용히 쌓은 것이 그대로 남는 흐름입니다.", "{m}월엔 서두르지 않은 자리에 사람이 붙는 흐름입니다.", "{m}월은 애쓴 만큼 돌아오기 시작하는 흐름입니다.",
             "{m}월엔 느리지만 단단히 자리 잡는 흐름입니다.", "{m}월은 묵힌 것이 값을 받기 시작하는 흐름입니다.", "{m}월엔 늦게 온 답이 더 오래 가는 흐름입니다."],
}
# ④ 표 안내
TABLE = ["{a}띠만이 아닙니다.\n표에 출생연도 {n}개가 더 올라 있으니\n본인 해와 부모님 해를 찾아보세요.",
         "표에는 {a}띠 말고도\n같은 흐름인 출생연도가 {n}개 더 있습니다.\n본인 해를 찾아보세요.",
         "{a}띠 말고도 {n}개 해가 더 있습니다.\n본인 해가 있는지, 어머니 해가 있는지\n표에서 찾아보세요."]
TABLE_RANK = ["2등부터 12등까지는 영상 표에 있습니다.\n본인 띠와 부모님 띠를 찾아보세요.",
              "나머지 순위는 표에 있습니다.\n본인 띠가 몇 등인지 찾아보세요."]
TABLE_NOANIMAL = ["표에 올라 있는 출생연도가 {n}개입니다.\n본인 해와 부모님 해를 찾아보세요.",
                  "출생연도 {n}개가 표에 있습니다.\n본인 해가 있는지 찾아보세요."]
# ⑤ 정체 + 가족
IDENT = ["사람이 봐드리는 곳이 아닙니다.\n만세력 달력표를 그대로 뽑아 드립니다.",
         "누가 봐주는 게 아니라\n만세력 표를 그대로 뽑아 보여 드리는 곳입니다.",
         "사주 봐주는 곳이 아닙니다.\n달력표(만세력)를 그대로 뽑는 곳입니다."]
FAMILY = ["부모님·자녀 출생연도도 같이 넣어 보세요. 30초면 됩니다.",
          "본인 해 다음엔 어머니 해, 아이 해도 넣어 보세요. 30초씩입니다.",
          "가족 출생연도 하나씩 넣어 보세요. 30초면 나옵니다."]
# ⑦ 댓글 유도 — 예고형(A안). 약속이므로 새벽 루틴이 전날 댓글 띠를 다음 주제로 잡는다
COMMENT = ["댓글에 본인 해(년생)를 남겨 주시면\n다음 글에서 그 띠부터 짚습니다.",
           "본인 년생을 댓글에 남겨 주세요.\n다음 글은 댓글에 많은 띠부터 올립니다.",
           "댓글에 년생 남겨 주시면\n다음 표는 그 띠부터 만듭니다."]
NOTICE = "띠는 입춘 기준입니다. 오락 목적으로 제공됩니다."
HOLIDAYS = {"추석": (9, 25), "설": (2, 17), "연말": (12, 31)}     # 2026 기준. ±14일이면 ③ 앞에 명절 말 붙임
HOLIDAY_LINE = {"추석": "추석 지나며 ", "설": "설 지나며 ", "연말": "연말 앞두고 "}


def animal_of(year):
    return ANIMALS[(int(year) - 4) % 12]


def month_for(d=None):
    d = d or date.today()
    return d.month + 1 if d.day >= 15 and d.month < 12 else d.month     # 보름 지나면 다음 달 얘기


def holiday_prefix(d=None):
    d = d or date.today()
    for name, (m, dd) in HOLIDAYS.items():
        h = date(d.year, m, dd)
        if abs((d - h).days) <= 14:
            return HOLIDAY_LINE[name]
    return ""


def check(text):
    bad = [("금지어 " + w) for w in BANNED if w in text]
    if len(text) > TEXT_MAX:
        bad.append("%d자 (2000 초과)" % len(text))
    if text.count("http") != 1:
        bad.append("링크는 하나")
    if "#" in text:
        bad.append("해시태그")
    if "—" in text:
        bad.append("줄표")
    return bad


def pick_animal(rows):
    """표 줄에서 가장 많이 나온 띠와 그 띠의 년생 3개(1960 이후 우선, 표에 실제 있는 것만). (띠, [년생], 나머지 개수)"""
    count = {}
    for r in rows:
        y = int(r[0]) if str(r[0]).isdigit() else None
        if y is None:
            continue
        a = (r[1].replace("띠", "") if len(r) > 1 and r[1] else animal_of(y))
        count.setdefault(a, []).append(y)
    if not count:
        return None, [], len(rows)
    a = max(count, key=lambda k: (len(count[k]), -min(count[k])))
    ys = (sorted(y for y in count[a] if y >= 1960) or sorted(count[a]))[-3:]
    return a, ys, len(rows) - len(count[a])


def build(hook, topic, rows=None, rank1=None, rng=None, today=None, n_hint=0):
    rng = rng or random.Random()
    table = 스레드글.load_table()
    m = month_for(today)
    pre = holiday_prefix(today)
    a, ys, n_more = (None, [], n_hint)
    if rows:
        a, ys, n_more = pick_animal(rows)
    elif rank1:
        a = rank1.replace("띠", "")
        ys = 스레드글.pick_years(table[a]["years"], rng)
    kind = 스레드글.RELATION_KIND.get(table[a]["relation"], "평년") if a else "평년"
    yrs = " / ".join(str(y) for y in ys) + "년생"
    parts = []
    if hook:
        parts.append(hook.rstrip(".") + ".")
    if a and rows:
        parts.append("%s 표에\n%s띠(%s)가 올라 있습니다." % (topic, a, yrs))
    elif a:
        parts.append("%s 1등은\n%s띠(%s)입니다." % (topic, a, yrs))
    else:
        parts.append("%s 표입니다." % topic)
    flow = rng.choice(FLOW[kind]).format(m=m)
    parts.append(rng.choice(COND[kind]) + "\n" + (pre + flow[0].lower() + flow[1:] if pre else flow))
    if a and rows:
        parts.append(rng.choice(TABLE).format(a=a, n=n_more))
    elif a:
        parts.append(rng.choice(TABLE_RANK))
    elif "순위" in topic:
        parts.append(rng.choice(TABLE_RANK))
    else:
        parts.append(rng.choice(TABLE_NOANIMAL).format(n=n_more or "여러 "))
    parts.append(rng.choice(IDENT) + "\n" + rng.choice(FAMILY))
    parts.append("👉 " + SITE)
    parts.append(rng.choice(COMMENT))
    parts.append(NOTICE)
    return "\n\n".join(parts)


def from_meta(m, rng=None, today=None):
    """meta.json 한 편 → 캡션. grid.py 가 screen_hook·screen_topic·rows(또는 rank1)를 적어 주면 온전한 틀, 없으면 예비 틀."""
    hook = m.get("screen_hook") or ""
    topic = m.get("screen_topic") or re.sub(r"\s*#shorts\s*$", "", (m.get("yt_title") or "")).split("|")[0].strip()
    rows = m.get("rows")
    rank1 = m.get("rank1")
    mm = re.search(r"(\d+)개", topic)
    n_hint = int(mm.group(1)) if mm else 0
    for _ in range(20):
        t = build(hook, topic, rows, rank1, rng, today, n_hint)
        if not check(t):
            return t
    raise RuntimeError("페북 캡션 생성 실패: " + ", ".join(check(t)))


def selftest(n):
    rng = random.Random(1)
    table = 스레드글.load_table()
    seen, probs, lens = set(), [], []
    for i in range(n):
        a = ANIMALS[i % 12]
        rows = [[y, a + "띠"] for y in table[a]["years"][-3:]] + [[y, animal_of(y) + "띠"] for y in range(1950 + i, 1950 + i + 20)]
        t = build("이 줄에 있으면 한숨 돌리셔도 됩니다", "시험용 출생연도", rows, None, rng) if i % 3 else build("긴 겨울 끝났습니다", "시험용 띠 순위", None, a, rng)
        bad = check(t)
        if bad:
            probs.append((i, bad))
        seen.add(t); lens.append(len(t))
    print("생성 %d개 / 서로 다른 글 %d개 / 글자수 %d~%d / 검사 걸린 것 %d개" % (n, len(seen), min(lens), max(lens), len(probs)))
    for i, b in probs[:10]:
        print("  #%d %s" % (i, ", ".join(b)))
    return not probs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int)
    ap.add_argument("--seed", type=int)
    args = ap.parse_args()
    if args.n:
        sys.exit(0 if selftest(args.n) else 1)
    rows = [[y, animal_of(y) + "띠"] for y in (1936, 1938, 1939, 1942, 1946, 1948, 1957, 1958, 1961, 1967, 1974, 1978, 1979, 1981, 1982, 1988, 1995, 1997, 1998, 1999, 2001, 2004, 2005, 2007)]
    print(build("버틴 보람 있습니다", "직장에서 자리 잡는 출생연도", rows, None, random.Random(args.seed)))
