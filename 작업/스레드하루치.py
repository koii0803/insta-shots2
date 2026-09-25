# -*- coding: utf-8 -*-
"""깃허브 액션이 매일 새벽 돌리는 스레드 하루치 만들기 (2026-09-19, PC 꺼져 있어도 글이 나가게). 사용자가 직접 만질 일 없음.

2026-09-26 사장님 지시로 바뀜: **하루 4개만. 일반글(일상·일진·사람) 아예 안 올린다.**
  1) 오늘 계획 = 스레드글.plan_today() — 시간대 4개(06:17~07:27 · 14:13~15:11 · 18:33~18:46 · 23:00~23:30)에 하나씩,
     분은 시간대 안에서 랜덤. 종류는 5유형(소원·특징·띠·경고·모집) 중 그날 안 겹치게 랜덤 4개.
  2) 띠 = 스레드글.generate() + auto_hide(). 나머지 넷 = 클로드에 유형별 틀로 부탁 → 스레드글.check() 통과할 때까지 3번.
     특징 글은 마지막 "어떤 사주냐면," 다음 줄(답)을 가림(스포일러)으로 숨긴다.
  3) 예약표에 threads-<종류>-<시각> 건으로 넣는다(threads_status 대기). 발행은 shorts-publish 가 30분마다.
     릴스에 딸린 스레드 글은 쇼츠발행.py 가 더는 안 올린다 (하루 4개를 지키려고).
  4) 스레드하루치기록.json 에 오늘 날짜를 적어 같은 날 두 번 안 돈다(수동 실행해도).
  시각이 이미 지난 자리는 그 시간대 남은 구간에서 다시 뽑는다. 시간대가 다 지났으면 건너뛴다.
로컬 시험: python 작업/스레드하루치.py --dry-run [--day 2026-09-27]  (아무것도 안 바꿈)
"""
import os
import re
import sys
import json
import random
import shutil
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import 스레드글

ROOT = Path(__file__).resolve().parent.parent
import 쇼츠창고                    # 예약표·기록은 전부 R2 창고 shorts/ (2026-09-25). 깃허브엔 안 남긴다
LOG_ERR = "오류기록.txt"
DONE = "스레드하루치기록.json"
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

# ── 5유형 틀 (2026-09-26 스레드 상위 사주 글 실측). 남의 글 원문은 안 넣는다. 꼴만 ──────────
_막힌말 = ", ".join(w for w in 스레드글.BANNED if w.strip() and w not in ("—", "·"))
COMMON = """
공통 규칙
- 너는 스레드 계정 "팔자오빠"다. 30대 남자. 사주 달력표 뽑는 사람.
- 링크, 해시태그, 이모지, 줄표(—), 가운뎃점(·) 없음. 여러 개를 묶을 땐 쉼표로.
- 금지어(법, 계정 규칙): """ + _막힌말 + """
- 건강, 병, 임신, 주식, 투자, 부동산, 로또, 부적, 굿 얘기 금지.
- 단정하지 않는다. "~인 사람이 있어", "~쪽이야" 처럼 연다.
- 설명, 따옴표, 제목 달기 없이 글 본문만 내놓는다."""

# ① 소원형: "이 글 보이면 ~ 댓글에 한 단어" (실측 7천/771 — 풀이 없이 댓글 한 줄로 끝나서 참여가 쉽다)
WISH_PROMPT = """스레드에 올릴 짧은 글 하나. 목적: 지나가던 사람이 멈춰서 댓글에 한 단어를 남기게.
틀(반말, 4~6줄):
1) 첫 줄은 "이 글 보이면" 으로 시작해서 그냥 넘기지 말라는 한 줄
2) 이번 달 기운 한 줄: {month}
3) 이 흐름이 누구한테 오는지 한두 줄. 누구나 자기 얘기 같게(오래 버틴 사람, 막혀 있던 사람 같은 식)
4) 마지막 줄: 댓글에 "{word}" 한 단어 남기고 가라는 말
""" + COMMON

# ② 특징 나열형: <○○한 사람 사주> + 번호 특징 + "어떤 사주냐면," + 답 한 줄(가림) (실측 1.1천)
FEATURE_PROMPT = """스레드에 올릴 글 하나. 목적: 읽는 사람이 "이거 난데" 하고 멈춰서 가려진 답을 눌러 보게.
오늘 소재: {axis} ({symptom})
이런 식으로 갈린다(참고만, 베끼지 마): {split}
틀(반말):
1) 첫 줄 = 꺾쇠 제목 한 줄. 예 모양: <{axis} 쪽으로 사는 사람 사주> (말은 네가 새로)
2) 번호 붙인 특징 5~7줄. 누구나 뜨끔할 만큼 구체적으로, 한 줄에 하나
3) 끝에서 둘째 줄 = 딱 "어떤 사주냐면,"
4) 마지막 줄 = 답 한 줄. 일간이나 오행이나 십성 하나로, 쉬운 말을 붙여서 (예 모양: 식상이 강한 사주, 말과 손으로 먹고사는 쪽)
""" + COMMON

# ④ 경고형: "죄송하지만" + 살(煞) 이름 한자 + 뜻 (실측 530/127 — 경고인 척 칭찬, 한자가 붙어 전문가처럼 보인다)
WARN_PROMPT = """스레드에 올릴 글 하나. 경고인 척하지만 사실은 추켜세우는 글.
오늘 붙잡을 살: {sal}
틀(이 글만 합쇼체, 5~8줄):
1) 첫 줄 = "죄송하지만"
2) 둘째 줄 = 이 살 가진 사람은 ~하게 살지 마십시오, ~하며 사십시오 같은 한 줄 (뜻밖의 칭찬 쪽으로)
3) 번호 붙여 2~3개. 첫째는 반드시 위 살. 모양: 살 이름(한자) 다음 줄에 그 뜻 한 줄
4) 마지막 줄 = 내 사주에 이 살 있는지 궁금하면 년생 남기라는 한 줄
""" + COMMON

# ⑤ 모집형: 생년월일시, 성별, 고민 남기라고 받는다 (실측 42/71 — 좋아요보다 댓글이 많다. 답글 기계가 다 받는다)
RECRUIT_PROMPT = """스레드에 올릴 글 하나. 목적: 댓글로 생년월일을 받는 것. 답글은 내가 순서대로 단다.
오늘: {day} {weekday}요일 {when}
틀(반말, 6~9줄):
1) 첫 줄 = 오늘 좀 한가하다는 식의 자연스러운 이유 한 줄 (요일이나 시간대를 핑계로. 매번 다르게)
2) 요즘 제일 신경 쓰이는 거 하나 남기라는 한 줄
3) 예시 고민 서너 개 쉼표로 (재회, 이직, 돈, 결혼, 인간관계 중에서)
4) 남길 것 세 줄: 생년월일 / 태어난 시간(몰라도 됨) / 성별
5) 마지막 줄 = 댓글 순서대로 짚어준다는 한 줄 ("봐줄게", "상담" 이라는 말은 쓰지 마)
""" + COMMON

WISH_WORDS = ["받는다", "온다", "나다", "열린다", "간다", "들어와"]
SALS = ["백호살(白虎殺)", "현침살(懸針殺)", "괴강살(魁罡殺)", "양인살(羊刃殺)", "화개살(華蓋殺)", "역마살(驛馬殺)",
        "도화살(桃花殺)", "홍염살(紅艶殺)", "천을귀인(天乙貴人)", "문창귀인(文昌貴人)", "암록(暗祿)", "원진살(怨嗔殺)"]

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


def _pick(items, used, keep, rng):
    """최근 keep 개에 쓴 것을 빼고 하나. 다 썼으면 아무거나."""
    left = [x for x in items if x not in used[-keep:]] or items
    return rng.choice(left)


def feature_hide(text):
    """특징 글: "어떤 사주냐면," 다음 마지막 줄(답)을 가린다. 모양이 안 맞으면 None → 다시 쓰게."""
    lines = [l for l in text.split("\n") if l.strip()]
    if len(lines) < 4 or not lines[-2].strip().startswith("어떤 사주냐면"):
        return None
    try:
        return 스레드글.entities(text, [lines[-1].strip()])
    except ValueError:
        return None


def slot_time(slot, day):
    """시각이 지났으면 그 시간대 남은 구간에서 다시 뽑는다. 다 지났으면 None."""
    at = datetime.strptime(slot["at"], "%Y-%m-%d %H:%M")
    if "--day" in sys.argv or at >= now() + timedelta(minutes=5):
        return slot["at"]
    h1, m1, h2, m2 = 스레드글.SLOT_WINDOWS[slot["win"]]
    end = datetime.strptime(day, "%Y-%m-%d") + timedelta(hours=h2, minutes=m2)
    lo = now() + timedelta(minutes=5)
    if lo >= end:
        return None
    span = int((end - lo).total_seconds() // 60)
    return (lo + timedelta(minutes=random.randint(0, span))).strftime("%Y-%m-%d %H:%M")


def main():
    day = sys.argv[sys.argv.index("--day") + 1] if "--day" in sys.argv else now().strftime("%Y-%m-%d")
    창고 = 쇼츠창고.열기()
    done = 창고.읽기(DONE) or {}
    if done.get("날짜") == day and not DRY:
        print("오늘(%s) 이미 만들었음 (%s). 끝" % (day, done.get("결과")))
        return 0
    q = 창고.예약표읽기()
    # 오늘 이미 들어가 있는 **글만 건**(릴스 아님). 손으로 다시 돌려도 겹치지 않게 그 종류는 안 만든다
    have = {it.get("threads_kind") for it in q if it.get("publish_at", "").startswith(day)
            and not it.get("video_url") and it.get("threads_status") in ("대기", "게시")}
    rec = 스레드글.load_record()
    plan = 스레드글.plan_today(day=day, rng=random.Random())
    print("계획 %d개: %s / 이미 있음 %s" % (len(plan), ", ".join("%s %s" % (x["at"][11:], x["kind"]) for x in plan),
                                        sorted(k for k in have if k)))
    if not CLAUDE_OK:
        print("claude 가 없음 → 띠 글만 만든다 (깃허브: Secrets CLAUDE_CODE_OAUTH_TOKEN, PC: 터미널에서 claude 로그인)")

    def used(k):
        return [r.get("훅") for r in rec if r.get("종류") == k and r.get("훅")]

    wd = WEEKDAY[datetime.strptime(day, "%Y-%m-%d").weekday()]
    made, skipped, 새건 = [], [], []
    for slot in plan:
        kind = slot["kind"]
        if kind in have:
            skipped.append("%s %s(이미 있음)" % (slot["at"][11:], kind))
            continue
        at = slot_time(slot, day)
        if not at:
            skipped.append("%s %s(시간대 지남)" % (slot["at"][11:], kind))
            continue
        rng = random.Random()
        text, ents, animal, hook, theme = None, [], "", None, None
        if kind == "띠":
            try:
                g = 스레드글.generate(rng=rng)
            except RuntimeError as e:
                log_err("%s 스레드 하루치: 띠 글 생성 실패 %s" % (stamp(), e))
                continue
            text, ents, animal, hook = g["text"], 스레드글.auto_hide(g["text"]), g["animal"], g["hook"]
            theme = g.get("theme", "흐름")
        elif not CLAUDE_OK:
            skipped.append("%s %s(클로드 없음)" % (at[11:], kind))
            continue
        elif kind == "소원":
            hook = _pick(WISH_WORDS, used("소원"), 3, rng)
            month = 스레드글.month_line(rng, datetime.strptime(day, "%Y-%m-%d").date()) or "요즘 막혔던 게 풀리는 쪽으로 기운이 도는 달이야"
            text = ask(WISH_PROMPT.format(month=month, word=hook), maxlines=6, minlines=4)
        elif kind == "특징":
            cfg = json.loads(SYMPTOMS.read_text(encoding="utf-8"))
            ax = _rotate(cfg["축"], used("특징"), 10, rng)
            hook = ax["이름"]
            for _ in range(2):                          # 모양("어떤 사주냐면," + 답)이 틀리면 한 번 더
                t = ask(FEATURE_PROMPT.format(axis=ax["이름"], symptom=ax["증상"], split=ax["가르는 말"]),
                        maxlines=10, minlines=7)
                ents = (feature_hide(t) if t else None) or []
                if ents:
                    text = t
                    break
        elif kind == "경고":
            hook = _pick(SALS, used("경고"), 6, rng)
            text = ask(WARN_PROMPT.format(sal=hook), maxlines=9, minlines=5)
        else:   # 모집
            when = {"아침": "아침", "낮": "오후", "저녁": "저녁", "밤": "밤"}.get(slot["win"], "")
            text = ask(RECRUIT_PROMPT.format(day=day, weekday=wd, when=when), maxlines=9, minlines=6)
        if not text:
            log_err("%s 스레드 하루치: %s 글 못 만듦(%s)" % (stamp(), kind, at))
            continue
        vid = "threads-%s-%s" % (kind, at.replace("-", "").replace(" ", "-").replace(":", ""))
        entry = {"id": vid, "video_url": "", "caption": "", "publish_at": at, "status": "없음", "youtube_url": "",
                 "threads_kind": kind, "threads_text": text, "threads_entities": ents, "threads_status": "대기"}
        print("[%s] %s (%d자, 가림 %d곳)" % (kind, at, len(text), len(ents)))
        print("  " + (스레드글.show_hidden(text, ents) if ents else text).replace("\n", "\n  "))
        made.append(vid)
        새건.append(entry)
        if not DRY:
            rec_row = {"날짜": stamp(), "id": vid, "종류": kind, "띠": animal, "훅": hook, "text": text}
            if theme:
                rec_row["주제"] = theme
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
