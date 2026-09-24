# -*- coding: utf-8 -*-
"""깃허브 액션이 매일 아침 돌리는 스레드 하루치 만들기 (2026-09-19, PC 꺼져 있어도 글이 나가게). 사용자가 직접 만질 일 없음.

하는 일 (스레드발행 스킬 '하루치 만들기' 절을 그대로 코드로):
  1) 오늘 계획 = 스레드글.plan_today() (3~5개: 띠 2 + 일상 + 3~4일에 한 번 사람). 개수·시각은 기계가 정한다.
  2) 예약표(쇼츠예약.json)에 오늘 것이 이미 있으면 그만큼 뺀다.
     - 띠 글: PC 새벽 루틴이 쇼츠와 같이 넣은 띠 글(threads_text 있는 인스타 건)이 오늘 2개 있으면 안 만든다. 부족한 만큼만 글만으로 만든다.
       (PC 가 꺼져 쇼츠가 없으면 띠 글 2개를 여기서 만든다 → 스레드는 하루도 안 빈다)
     - 일상·사람: 오늘 같은 종류가 이미 있으면 안 만든다.
  3) 띠 글 = 스레드글.generate() + auto_hide()(가림 기준 표 그대로: 항목 줄 + 시점 앞부분).
     일진 글 = 일진글.py(오늘 달력, 규칙만, AI 없음) — 일상 자리 중 첫 번째. 나머지 일상 글 = 클로드에 스킬 '일상 글' 절 규칙으로 부탁 → 스레드글.check() 통과할 때까지 3번.
     사람 글 = 실제 있었던 일만 → 스레드소재.txt 에 사장님(또는 PC AI)이 적어 둔 줄 하나를 써서 클로드에 부탁. 소재 없으면 그 자리는 비운다(안 지어냄).
  4) 예약표에 threads-<종류>-<시각> 건으로 넣고(threads_status 대기), 스레드글기록.jsonl 에 기록. 발행은 shorts-publish 가 30분마다.
  5) 스레드하루치기록.json 에 오늘 날짜를 적어 같은 날 두 번 안 돈다(수동 실행해도).
클로드가 없으면 띠 글만 만들고 일상·사람은 건너뛴다(기록 남김, 액션은 성공).
로컬 시험: python 작업/스레드하루치.py --dry-run [--day 2026-09-19]  (아무것도 안 바꿈. 키 없으면 일상 글은 건너뜀)
"""
import os
import re
import sys
import json
import random
import shutil
import subprocess
import urllib.request
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import 스레드글
import 일진글          # 일상 자리 하나는 오늘 일진 글 (2026-09-19 사장님 지시)

ROOT = Path(__file__).resolve().parent.parent
import 쇼츠창고                    # 예약표·기록·소재는 전부 R2 창고 shorts/ (2026-09-25). 깃허브엔 안 남긴다
LOG_ERR = "오류기록.txt"
DONE = "스레드하루치기록.json"
TOPICS = "스레드소재.txt"          # 사람 글 소재. 한 줄에 하나, 위에서부터 쓰고 지운다. 넣기: python 쇼츠창고.py --소재 "한 줄"
KST = ZoneInfo("Asia/Seoul")
DRY = "--dry-run" in sys.argv
# 글 쓰는 AI = 클로드 (2026-09-23 사장님 지시 "제미나이 근처도 가지 마").
# 답글 기계(스레드자동답글.py)와 **같은 방식·같은 열쇠**다. 구독으로 돌아 API 키가 없다.
# 깃허브에선 Secrets 의 CLAUDE_CODE_OAUTH_TOKEN, PC 에선 터미널 로그인을 그대로 쓴다.
CLAUDE_MODEL = "sonnet"
CLAUDE_OK = bool(shutil.which("claude") or shutil.which("claude.cmd"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 스레드발행 스킬 '일상 글'·'사람 글' 절 그대로. 실측 원문은 공개 저장소에 안 넣는다(남의 글). 말투 규칙만.
# 2026-09-21: 소재가 '요일 + 코딩'으로 굳어서 소재 바퀴(일상소재축.json) + 시간대 톤 + 실제 날씨를 넣음. 사업·코딩 소재는 뺌(= 사람 글 몫).
DAILY_PROMPT = """너는 스레드 계정 "팔자오빠"로 글을 쓴다. 혼자 사는 30대 남자. 출근은 안 한다. 직장인 흉내 안 낸다.
오늘: {day} {weekday}요일, {slot}({hour}시쯤 올라감).

이번 글의 소재는 "{axis}" 하나로 간다. 다른 소재로 새지 않는다.
  쓸 것: {axis_use}
  피할 것: {axis_avoid}
{weather}
말투는 {tone}. **말투만 그렇게 한다. 소재는 위 "{axis}" 하나뿐이다. 말투 때문에 다른 소재로 새지 않는다.**
마지막 질문은 {qname}으로 끝낸다 ({qhow})

스레드 일상 글 딱 하나만 써라. 설명·따옴표·제목 없이 글 본문만.
- 반말, 1인칭 "나". 마지막 줄은 반드시 물음표로 끝낸다.
- **반드시 2줄 또는 3줄로 줄을 나눠 쓴다.** 한 덩어리로 길게 쓰지 않는다. 줄마다 한 문장이면 된다.
- 140자 안. 짧을수록 좋다.

**사람이 쓴 글처럼 보이는 게 제일 중요하다:**
- **한 가지만 붙잡는다.** 소재 안에서도 장면 하나만 쓴다. 두세 가지를 나열하면 광고처럼 보인다.
  (나쁜 예: 배달비도 비싸고 구독료도 나가고 통신비도 나가고 / 좋은 예: 배달비 5천원 보고 앱 껐다)
- 구체적인 것 하나를 꼭 넣는다. 숫자·물건 이름·시각 같은 것 (예: "4천원", "3시", "편의점", "충전기 두 개").
- 결론을 내지 않는다. 교훈·정리·조언으로 끝내지 않는다.
- 문장을 다듬지 않는다. 앞뒤 대구를 맞추거나 운율을 만들지 않는다. 같은 구조의 문장을 나란히 쓰지 않는다.
- "~하는 요즘이다", "~인 것 같다", "~기분이네" 같은 매끈한 마무리 안 쓴다. 말하다 만 것처럼 툭 끊어도 된다.
- 감탄·호들갑 없다. 담담하게.
- 내가 무슨 일 하는지 설명하지 않는다. 사주·사이트·일 얘기는 아예 꺼내지 않는다.

- 링크·해시태그·이모지 없음. "스하리" 없음. 줄표(—) 없음.
- 금지어: 소름, 자빠질, 터진다, 100%, 반드시, 무조건, 확실, 족집게, 적중, 보장, 정확, 병·치료·수술·죽음·임신·우울, 복권·로또·주식·투자·부동산, 부적·굿, 상담, 봐준다.
- 사주 봐준다는 말, 실력 자랑, 상담 권유 없음."""

PERSON_PROMPT = """너는 스레드 계정 "팔자오빠"로 글을 쓴다. 사업 처음 하는 사람이 낮은 자세로 도움을 구하는 글이다. 목적은 답글(훈수·시비·응원 전부 환영).
실제 있었던 일(아래 소재)만 쓴다. 없는 일·숫자를 보태지 않는다.
소재: {topic}
틀(순서대로, 각 한 줄, 총 4~5줄, 반말):
① "나 팔자오빠." + 지금 상황 한 줄(초보·준비 중·처음)
② 솔직한 고백(모르는 것 / 안 되는 것 / 헷갈리는 것)
③ 구체적인 질문 하나("이거 어떻게 해?")
④ 살짝 열어두기("욕해도 됨" / "틀린 거 있으면 말해줘")
- 사주 봐준다는 말·실력 자랑·상담 없음. 돈 얘기는 그냥 "돈"·"원". 사이트 안 화폐를 말할 때만 "엽전"(코인이라 부르지 않음). 링크·해시태그·이모지·줄표(—) 없음.
- 금지어: 소름, 자빠질, 터진다, 100%, 반드시, 무조건, 확실, 족집게, 적중, 보장, 정확.
- 300자 안. 설명·따옴표·제목 없이 글 본문만."""

# 증상 훅 글 (2026-09-23 사장님 지시). 띠를 안 부르고 '증상'으로 건다 — 12명 중 1명이 아니라 누구나 멈춘다.
# 실측 근거: 우리 띠 글은 조회 3,874까지 나오지만 그 띠 사람만 멈춘다. 팔로워 5.8만 계정은 전부 이 방식.
SYMPTOM_PROMPT = """너는 스레드 계정 "팔자오빠"로 글을 쓴다. 사주로 사람을 가르는 글이다. 반말. 30대 남자.
목적: 읽는 사람이 "이거 난데" 하고 멈춰서 댓글에 생년월일을 남기게 하는 것.

오늘 소재: {axis} — {symptom}
이런 식으로 갈린다(참고만, 그대로 베끼지 마): {split}
가르는 기준: {basis} — {basis_how}
오늘 글꼴: {form} — {form_how}

틀(반말, 총 6~12줄):
① 첫 줄 = 증상 한마디. 띠·사주 얘기 없이 증상만. 짧게. (예: "잘못 자면 더 피곤해")
② 둘째 줄 = 무슨 기준으로 가르는지 한 줄
③ 본문 = **위 글꼴대로** 쓴다. 글꼴이 목록이 아니면 번호를 억지로 붙이지 않는다
④ 증상은 **구체적으로**. 슬래시로 툭툭 끊어도 된다 (예: "누우면 내일 계획 / 지난 대화 재생 / 두 시 세 시")
⑤ 마지막 = 네 년생 넣으면 30초. 링크는 첫 답글에
⑥ 맨 끝 = 질문 한 줄로 끝낸다 (물음표로 끝)

- 지금은 {month}월이다. 이 달 기운을 한 줄 넣어도 좋다(억지로는 말고).
- 단정하지 않는다. "~인 사람이 있어", "~쪽이야" 처럼 연다.
- 전문어(십성·신살 이름)는 써도 한 번만. 쓰면 바로 쉬운 말로 풀어준다.
- 건강·병·수술·죽음·임신, 주식·투자·부동산·로또, 부적·굿 얘기 금지. 법으로 막혀 있다.
- 금지어: 소름, 자빠질, 터진다, 100%, 반드시, 무조건, 확실, 족집게, 적중, 보장, 정확, 합격, 1위.
  ("1위"는 광고법상 순위 표시라 막혀 있다. 순서를 매길 땐 "제일 심한 건 / 그다음은" 처럼 쓴다.)
- 링크·해시태그·이모지·줄표(—) 없음. 450자 안.
- 설명·따옴표·제목 없이 글 본문만."""

WEEKDAY = "월화수목금토일"


def now():
    return datetime.now(KST).replace(tzinfo=None)


def stamp():
    return now().strftime("%Y-%m-%d %H:%M")


def log_err(line):
    print(line)
    if not DRY:
        쇼츠창고.열기().붙이기(LOG_ERR, line)


def claude(prompt):
    """글 본문 문자열. 실패면 예외.

    답글 기계와 같은 요령: 도구를 아예 안 싣는다(--tools Read --disallowedTools Read).
    도구 설명이 요청마다 2만 7천 토큰을 먹는다 — 우리는 글만 받으면 되니 필요 없다.
    """
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", CLAUDE_MODEL,
           "--safe-mode", "--system-prompt", "너는 스레드에 글을 쓰는 사람이다. 시킨 글 한 편만 그대로 내놓는다. 설명·머리말·따옴표 없이.",
           "--tools", "Read", "--disallowedTools", "Read"]
    r = subprocess.run(cmd, capture_output=True, timeout=180,
                       encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError("claude 실행 실패: %s" % (r.stderr or "")[:150])
    outer = json.loads(r.stdout)
    if outer.get("is_error"):
        msg = str(outer.get("result"))
        if re.search(r"authenticat|OAuth|Login expired|로그인", msg, re.I):
            raise RuntimeError("로그인만료: %s" % msg[:120])
        raise RuntimeError("claude 오류: %s" % msg[:150])
    text = (outer.get("result") or "").strip()
    text = text.strip("\"“”'` ").replace("—", ",").strip()
    text = "\n".join(l.strip() for l in text.splitlines() if l.strip())
    return text


def ask(prompt, must_question=False, tries=3, daily=False, maxlines=4, minlines=0):
    """클로드에 부탁해 스레드글.check() 통과한 글. 못 얻으면 None(이유 출력).

    daily=True 면 일상 글 규칙(2~3줄, 140자)도 같이 본다 — AI 가 프롬프트를 자주 흘려서.
    maxlines/minlines = 줄 수. 증상 글은 목록 꼴이라 8~12줄이 정상이다(2026-09-23).
    """
    last = ""
    for _ in range(tries):
        try:
            t = claude(prompt)
        except Exception as e:
            last = "클로드 호출 실패: %s" % str(e)[:200]
            continue
        bad = 스레드글.check(t)
        if "#" in t or "http" in t:
            bad.append("링크·해시태그")
        if must_question and not t.rstrip().endswith("?"):
            bad.append("질문으로 안 끝남")
        if t.count("\n") > maxlines:
            bad.append("줄 수 초과(%d줄, 한도 %d)" % (t.count("\n") + 1, maxlines + 1))
        if minlines and len([l for l in t.splitlines() if l.strip()]) < minlines:
            bad.append("줄이 너무 적음(%d줄 미만)" % minlines)
        if daily:
            n = len([l for l in t.splitlines() if l.strip()])
            if n < 2:
                bad.append("한 덩어리(줄 안 나눔)")
            if len(t) > 145:
                bad.append("%d자 (140 넘김)" % len(t))
        if not bad:
            return t
        last = ", ".join(bad) + " / " + t[:60].replace("\n", " ")
    print("  글 못 얻음: " + last)
    return None


AXES = Path(__file__).resolve().parent / "일상소재축.json"


def weather_today():
    """서울 오늘 날씨 한 줄. open-meteo(무료·키 없음). 실패하면 None → '날씨' 축을 안 쓴다."""
    url = ("https://api.open-meteo.com/v1/forecast?latitude=37.5665&longitude=126.978"
           "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
           "&current=temperature_2m&timezone=Asia%2FSeoul&forecast_days=1")
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            j = json.load(r)
        d, c = j["daily"], j.get("current", {})
        hi, lo = round(d["temperature_2m_max"][0]), round(d["temperature_2m_min"][0])
        rain = d["precipitation_sum"][0] or 0
        now_t = c.get("temperature_2m")
        s = "서울 오늘 최고 %d도 최저 %d도" % (hi, lo)
        if now_t is not None:
            s += ", 지금 %d도" % round(now_t)
        s += ", 비 %s" % ("옴(%.0fmm)" % rain if rain >= 1 else "안 옴")
        return s
    except Exception as e:
        print("  날씨 못 받음(%s) → 날씨 축 건너뜀" % str(e)[:60])
        return None


def pick_axis(rec, rng, weather):
    """최근 10개 일상 글에 쓴 축을 빼고 하나 고른다. 다 썼으면 가장 오래된 것부터 푼다."""
    cfg = json.loads(AXES.read_text(encoding="utf-8"))
    axes = [a for a in cfg["축"] if weather or not a.get("날씨필요")]
    used = [r.get("훅") for r in rec if r.get("종류") == "일상" and r.get("훅")][-10:]
    left = [a for a in axes if a["이름"] not in used]
    if not left:                                  # 11개를 다 돌았으면 가장 오래 안 쓴 것
        order = {n: i for i, n in enumerate(used)}
        left = sorted(axes, key=lambda a: order.get(a["이름"], -1))[:3]
    a = rng.choice(left)
    q = rng.choice(cfg["질문틀"])
    return a, q, cfg["시간대톤"]


SYMPTOMS = Path(__file__).resolve().parent / "증상축.json"


def _rotate(items, used, keep, rng):
    """최근에 쓴 것을 빼고 하나 고른다. 다 썼으면 가장 오래 안 쓴 것 중에서.

    "무게"가 있으면 그만큼 자주 뽑힌다 — 고민 축(재회·결혼시기·이직·돈)은 3, 성격 축은 1.
    성격 글은 좋아요만 받고 생년월일은 안 남는다(2026-09-23 사장님 "유입이 제일 잘 되는 주제로").
    """
    recent = used[-keep:]
    left = [x for x in items if x["이름"] not in recent]
    if not left:
        order = {n: i for i, n in enumerate(recent)}
        left = sorted(items, key=lambda x: order.get(x["이름"], -1))[:3]
    return rng.choices(left, weights=[x.get("무게", 1) for x in left])[0]


def pick_symptom(rec, rng):
    """축·가르는 기준·글꼴을 따로 돌려 고른다. (축, 기준, 글꼴)

    경우의 수 24 × 6 × 5 = 720 (2026-09-23 사장님 "경우의 수를 여러 가지 뒀으면").
    축은 최근 10개, 기준·글꼴은 최근 4개를 피한다 — 축은 소재라 오래 피해야 하고,
    기준·글꼴은 개수가 적어 너무 오래 피하면 돌 게 없다.
    """
    cfg = json.loads(SYMPTOMS.read_text(encoding="utf-8"))
    rows = [r for r in rec if r.get("종류") == "증상"]
    ax = _rotate(cfg["축"], [r.get("훅") for r in rows if r.get("훅")], 10, rng)
    basis = _rotate(cfg["가르는 기준"], [r.get("기준") for r in rows if r.get("기준")], 4, rng)
    form = _rotate(cfg["글꼴"], [r.get("글꼴") for r in rows if r.get("글꼴")], 4, rng)
    return ax, basis, form


def slot_name(at):
    h = int(at[11:13]) * 60 + int(at[14:16])
    for name, (h1, m1, h2, m2) in 스레드글.SLOT_WINDOWS.items():
        if h1 * 60 + m1 - 60 <= h <= h2 * 60 + m2 + 60:
            return name
    return "낮"


def pop_topic():
    """스레드소재.txt 첫 줄을 꺼내고(파일에서 지움) 돌려준다. 없으면 None."""
    raw = (쇼츠창고.열기().글읽기(TOPICS, "") or "").splitlines()
    lines = [l.strip() for l in raw if l.strip() and not l.strip().startswith("#")]
    if not lines:
        return None
    if not DRY:
        rest = [l for l in raw if l.strip() != lines[0]]
        쇼츠창고.열기().글쓰기(TOPICS, chr(10).join(rest).rstrip(chr(10)) + chr(10))
    return lines[0]


def main():
    day = sys.argv[sys.argv.index("--day") + 1] if "--day" in sys.argv else now().strftime("%Y-%m-%d")
    창고 = 쇼츠창고.열기()
    done = 창고.읽기(DONE) or {}
    if done.get("날짜") == day and not DRY:
        print("오늘(%s) 이미 만들었음 (%s). 끝" % (day, done.get("결과")))
        return 0
    q = 창고.예약표읽기()
    # 오늘 스레드에 실제로 나갈(나간) 건만 센다. 페북 전용 건(threads_status "없음")·실패 건을 띠 글로 세면 그만큼 덜 만들어 하루가 빈다 (2026-09-22)
    today = [it for it in q if it.get("publish_at", "").startswith(day)
             and (it.get("threads_status") in ("대기", "게시") or (it.get("threads_text") and not it.get("threads_status")))]
    have = {"띠": 0, "일상": 0, "사람": 0, "일진": 0, "증상": 0}
    for it in today:
        k = it.get("threads_kind") or "띠"
        have[k] = have.get(k, 0) + 1
    rec = 스레드글.load_record()
    last_person = max((r["날짜"][:10] for r in rec if r.get("종류") == "사람"), default=None)
    plan = 스레드글.plan_today(day=day, rng=random.Random(), last_person=last_person)
    for slot in plan:                                   # 일상 자리 중 첫 번째는 일진 글(오늘 달력 한마디). 나머지 일상은 그대로
        if slot["kind"] == "일상":
            slot["kind"] = "일진"
            break
    recent_keys = [r.get("훅") for r in rec[-20:] if r.get("종류") == "일진"]
    print("계획 %d개: %s / 이미 있음 %s" % (len(plan), ", ".join("%s %s" % (x["at"][11:], x["kind"]) for x in plan), have))
    if not CLAUDE_OK:
        print("claude 가 없음 → 일상·사람 글은 건너뜀 (깃허브: Secrets CLAUDE_CODE_OAUTH_TOKEN, PC: 터미널에서 claude 로그인)")

    weather = weather_today() if any(s["kind"] == "일상" for s in plan) else None
    used_axes = []                                  # 오늘 이미 쓴 소재축
    used_symptoms = []                              # 오늘 이미 쓴 증상축
    made, skipped, 새건 = [], [], []
    for slot in plan:
        kind, at = slot["kind"], slot["at"]
        if have.get(kind, 0) > 0:
            have[kind] -= 1
            skipped.append("%s %s(이미 있음)" % (at[11:], kind))
            continue
        if datetime.strptime(at, "%Y-%m-%d %H:%M") < now() and "--day" not in sys.argv:
            skipped.append("%s %s(시각 지남)" % (at[11:], kind))
            continue
        if kind == "띠":
            try:
                g = 스레드글.generate(rng=random.Random())
            except RuntimeError as e:
                log_err("%s 스레드 하루치: 띠 글 생성 실패 %s" % (stamp(), e))
                continue
            text, ents, animal, hook = g["text"], 스레드글.auto_hide(g["text"]), g["animal"], g["hook"]
            theme = g.get("theme", "흐름")                       # 2026-09-22 주제(흐름·돈·관계·기질·시기)
        elif kind == "일진":
            try:
                g = 일진글.generate(day, random.Random(), avoid_keys=recent_keys)
            except RuntimeError as e:
                log_err("%s 스레드 하루치: 일진 글 생성 실패 %s" % (stamp(), e)); continue
            text, ents, animal, hook = g["text"], [], g["animal"], g["key"]
        elif kind == "일상":
            if not CLAUDE_OK:
                skipped.append("%s 일상(키 없음)" % at[11:]); continue
            sl = slot_name(at)
            axis, qform, tones = pick_axis(rec + [{"종류": "일상", "훅": h} for h in used_axes], random.Random(), weather)
            print("  소재축: %s / 질문틀: %s" % (axis["이름"], qform["이름"]))
            text = ask(DAILY_PROMPT.format(
                day=day, weekday=WEEKDAY[datetime.strptime(day, "%Y-%m-%d").weekday()], slot=sl, hour=at[11:13],
                axis=axis["이름"], axis_use=axis["쓸 것"], axis_avoid=axis["피할 것"],
                weather=("오늘 날씨: %s (이 숫자와 다른 말 하지 않는다)\n" % weather) if axis.get("날씨필요") else "",
                tone=tones.get(sl, tones["낮"]), qname=qform["이름"], qhow=qform["쓰는 법"]), must_question=True, daily=True)
            if not text:
                log_err("%s 스레드 하루치: 일상 글 못 만듦(%s, 축 %s)" % (stamp(), at, axis["이름"])); continue
            used_axes.append(axis["이름"])          # 같은 날 두 번째 일상 글이 같은 축을 안 쓰게
            ents, animal, hook = [], "", axis["이름"]
        elif kind == "증상":
            if not CLAUDE_OK:
                skipped.append("%s 증상(클로드 없음)" % at[11:]); continue
            ax, basis, form = pick_symptom(rec + used_symptoms, random.Random())
            m = 스레드글.this_month(datetime.strptime(day, "%Y-%m-%d").date())
            print("  증상축: %s / 기준: %s / 글꼴: %s" % (ax["이름"], basis["이름"], form["이름"]))
            text = ask(SYMPTOM_PROMPT.format(axis=ax["이름"], symptom=ax["증상"], split=ax["가르는 말"],
                                             basis=basis["이름"], basis_how=basis["쓰는 법"],
                                             form=form["이름"], form_how=form["쓰는 법"],
                                             month=(m or {}).get("월건", "이번")),
                       must_question=True, maxlines=13, minlines=5)
            if not text:
                log_err("%s 스레드 하루치: 증상 글 못 만듦(%s, 축 %s)" % (stamp(), at, ax["이름"])); continue
            # 같은 날 두 번째가 같은 축·기준·글꼴을 안 쓰게
            used_symptoms.append({"종류": "증상", "훅": ax["이름"], "기준": basis["이름"], "글꼴": form["이름"]})
            ents, animal, hook = [], "", ax["이름"]
            sym_meta = {"기준": basis["이름"], "글꼴": form["이름"]}
        else:   # 사람
            if not CLAUDE_OK:
                skipped.append("%s 사람(키 없음)" % at[11:]); continue
            topic = pop_topic()
            if not topic:
                skipped.append("%s 사람(소재 없음, 스레드소재.txt 비어 있음)" % at[11:]); continue
            text = ask(PERSON_PROMPT.format(topic=topic))
            if not text:
                log_err("%s 스레드 하루치: 사람 글 못 만듦(%s) 소재는 다시 넣어야 함: %s" % (stamp(), at, topic)); continue
            ents, animal, hook = [], "", None
        vid = "threads-%s-%s" % (kind, at.replace("-", "").replace(" ", "-").replace(":", ""))
        entry = {"id": vid, "video_url": "", "caption": "", "publish_at": at, "status": "없음", "youtube_url": "",
                 "threads_kind": kind, "threads_text": text, "threads_entities": ents, "threads_status": "대기"}
        print("[%s%s] %s (%d자, 가림 %d곳)" % (kind, ("·" + theme) if kind == "띠" else "", at, len(text), len(ents)))
        print("  " + (스레드글.show_hidden(text, ents) if ents else text).replace("\n", "\n  "))
        q = [x for x in q if x.get("id") != vid]
        q.append(entry)
        made.append(vid)
        새건.append(entry)
        if not DRY:
            rec_row = {"날짜": stamp(), "id": vid, "종류": kind, "띠": animal, "훅": hook, "text": text}
            if kind == "띠":
                rec_row["주제"] = theme
            if kind == "증상":
                rec_row.update(sym_meta)       # 기준·글꼴도 남겨야 다음에 안 겹친다
            스레드글.add_record_row(rec_row)
    if DRY:
        print("[dry-run] 아무것도 안 바꿈. 만들 것 %d개, 건너뜀 %s" % (len(made), skipped))
        return 0
    if made:
        # 글 만드는 데 몇 분 걸리니 잠금은 **넣을 때만** 잡는다. 그 사이 바뀐 예약표 위에 얹는다
        새아이디 = {e["id"] for e in 새건}
        if not 쇼츠창고.예약표고치기(lambda 표: [x for x in 표 if x.get("id") not in 새아이디] + 새건, "깃허브-하루치"):
            log_err("%s 스레드 하루치: 예약표가 잠겨 있어 못 넣었다 (%s). 다음 실행에 다시" % (stamp(), made))
            return 1
    창고.쓰기(DONE, {"날짜": day, "결과": "만듦 %d개 %s / 건너뜀 %s" % (len(made), made, skipped), "때": stamp()})
    print("끝. 만듦 %d개, 건너뜀 %s" % (len(made), skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
