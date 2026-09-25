# -*- coding: utf-8 -*-
"""내 스레드 글 답글에 **만세력 엔진으로 풀어서** 자동으로 답한다 (2026-09-21 사장님 지시).

사람이 안 봐도 돈다. 목적은 **채널 성장** — 풀어주고 → 빠진 항목을 물어 댓글을 한 번 더 받고 →
어느 정도 마무리되면 스하리·프로필 링크를 청한다. 사이트 결제는 프로필 링크로 간다.

    python 스레드자동답글.py            # 한 바퀴 (작업 스케줄러가 5분마다 부른다)
    python 스레드자동답글.py --dry-run   # 판단·풀이만. 발행·보고·기록 없음
    python 스레드자동답글.py --check     # 대기줄 상태만
    python 스레드자동답글.py --test "댓글 내용"   # 그 댓글 하나로 추출→엔진→풀이만 돌려 본다

한 바퀴:
  1) 일주일치 내 글의 대화 전체(/conversation, 페이지 끝까지) → 아직 답 안 한 답글. 대댓글 체인 포함
  2) 규칙 필터 — 이모지·짧음·링크·횟수초과 → 조용히 무시 (LLM 안 부름 = 돈 안 씀)
  3) 분류 + 생년 추출 — claude(haiku). 답함/무시/동업자/악의 + 생년월일시·성별·양음력
  4) 2008년 이후 출생이면 건너뜀 (만 14세 미만 = 개인정보보호법 법정대리인 동의 필요. 사이트 정책과 같음)
  5) 생년월일이 있으면 **만세력 엔진**(saju-arcade/report/dump-saju.ts) → 사주 팩트
  6) 풀이 작성 — claude(sonnet). **엔진 값에 없는 말은 못 쓴다.** 턴이 깊어질수록 전문가 → 보듬는 톤으로
  7) 4~37분 뒤 완전 랜덤 시각으로 대기줄 → 시각 지나면 발행
  8) 동업자·악의·확신 부족 → 답하지 않고 텔레그램 보고 ("답해" 답장하면 올림)

절대 안 하는 것: 남의 글에 답글, 엔진에 없는 말 지어내기, 미성년 풀이, 링크 뿌리기(링크는 사장님이 직접).
"""
import os
import re
import sys
import json
import time
import random
import argparse
import subprocess
import datetime as dt
import urllib.parse
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── 어디서 도는가 (2026-09-21 "창고 하나": PC 와 깃허브가 같은 코드·같은 R2 를 쓴다) ──
# 이 파일은 쇼츠저장소/작업/ 에 있다. PC 는 유튜브업로더/스레드자동답글.py(껍데기)가 이걸 부른다.
HERE = Path(__file__).resolve().parent            # 쇼츠저장소/작업
REPO = HERE.parent                                 # 쇼츠저장소 (오류기록·예약표가 여기)
sys.path.insert(0, str(HERE))
import 금고
import 스레드글
import 답글창고

if os.environ.get("GITHUB_ACTIONS"):
    WHO = "깃허브"
    ROOT = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "threads-reply"   # 실행기록만. 진짜 기록은 전부 R2
    ROOT.mkdir(parents=True, exist_ok=True)
    ARCADE = Path(os.environ["SAJUARCADE_DIR"])                            # 워크플로가 열쇠로 받아 둔 홈페이지 창고
    HEARTBEAT_MAX_MIN = int(os.environ.get("HEARTBEAT_MAX_MIN", "20"))     # PC 가 이만큼 조용하면 대신 나선다
else:
    WHO = "PC"
    import config
    ROOT = Path(config.ROOT)                                                # 유튜브업로더
    ARCADE = ROOT.parent / "saju-arcade"
    HEARTBEAT_MAX_MIN = 0

API = "https://graph.threads.net/v1.0/"
TOKEN_FILE = os.path.expanduser("~/.saju_meta_tokens.json")               # PC 에만 있다
ME = "paljaoppa"

RUNLOG = ROOT / "스레드자동답글_실행기록.txt"   # 이것만 로컬. 나머지(대기·상태·답한것·기록·잠금)는 R2

# ── 사장님이 바꾸는 값 ────────────────────────────────────────────
DELAY_MIN, DELAY_MAX = 3, 15    # 발행까지 랜덤 대기(분). 2026-09-23 사장님 지시 4~37 → 3~15
CONFIDENCE = 85                 # 이 미만이면 답 안 하고 보고
MAX_PER_PERSON = 5              # 한 글에서 같은 사람과 최대 몇 번 (2026-09-25 사장님 지시 10 → 5).
                                # 5턴에 유료 안내하고 끊는다. 최근 3일 206건 중 6턴 넘는 건 9건(4.4%)뿐
PROMO_TURN = 1                  # 리포스트를 청하는 턴 (2026-09-25 사장님 지시 3 → 1).
                                # 1턴이 전체의 40.8%%(84/206)다. 3턴부터면 그 84명이 아예 못 듣고 떠났다
PROFILE_TURN = 3                # 이 턴부터 프로필(유료)을 안내한다. 3~4턴 = 53건에 닿는다
LAST_TURN = MAX_PER_PERSON      # 이 턴에 안내하고 끊는다. 여기선 되묻지 않는다
MAX_PER_DAY = 998               # 하루 자동 답글 상한 (2026-09-21 사장님 지시). 넘으면 다음 날로 밀린다
META_RESERVE = 20               # 메타 한도(답글 1000/일)에서 이만큼은 남겨 둔다
                                # — 쇼츠 첫 답글(링크)과 손으로 다는 답글도 같은 한도를 먹는다
REPLY_GAP_SEC = 120             # 답글과 답글 사이 최소 2분 (2026-09-25 사장님 지시). 자동·AI자동답변·사장님 답장 전부
PUBLISH_WAIT_MAX = 240          # 한 바퀴에 2분 간격 맞추느라 기다리는 최대 시간. 나머지는 다음 바퀴(5분마다)로
MAX_PER_RUN = 12                # 한 바퀴에 처리할 최대 건수. 1건당 약 45초라 12건이면 9분쯤 걸린다
LOCK_STALE_MIN = 60             # 잠금을 '깨진 것'으로 보는 시간. 한 바퀴가 길어질 수 있어 넉넉히
POST_AGE_DAYS = 7               # 일주일치 글까지 답글을 본다 (2026-09-21 사장님 "일주일은 커버를 해야지")
HOT_DAYS = 2                    # 최근 이틀 글은 매 바퀴, 나머지는 한 시간에 한 번만 훑는다(읽기 호출 절약)
MIN_LEN = 3                     # 이 글자 수 이하는 무시
MINOR_BORN = 2008               # 이 해 이후 출생 = 안 봄 (만 14세 미만 보호)
REPORT_EVERY_HOURS = 6          # 몇 시간마다 한눈 요약을 텔레그램으로 보낼지 (00·06·12·18시)
MODEL_EXTRACT = "sonnet"        # 2026-09-24 사장님 지시로 haiku → sonnet.
# 실측: haiku 가 출력 4,233 토큰을 토해서 값이 sonnet($0.0297)과 거의 같았다($0.0246).
# 분류만 하는데 싼 모델 값이 안 싸면 쓸 이유가 없다.
MODEL_WRITE = "sonnet"          # 풀이 작성용

# 풀이를 허용하면서(2026-09-21) 법적 금지어는 그대로 둔다.
# 뺀 것: 봐줄게·봐준다·풀어줄게 — 프로필에 "사람이 봐주는 데 아님"을 이미 밝혔으므로 거짓 신뢰가 아니다.
# 남긴 것: 문구규칙.md 근거(의료법·표시광고법·PG 심사) + '전문가·명인이 직접 감정'(거짓 신뢰) + '상담'.
BANNED = [w for w in 스레드글.BANNED if w not in ("봐줄게", "봐준다", "풀어줄게")]


STORE = None                     # R2 창고. run() 이 연다. 아래 저장 함수들은 전부 이걸 쓴다


def now():
    return dt.datetime.now()


def runlog(msg):
    """이것만 로컬 파일. 스케줄러가 돈 흔적 (PC 와 깃허브가 각자)."""
    line = "%s [%s] %s" % (now().strftime("%Y-%m-%d %H:%M:%S"), WHO, msg)
    print(line)
    try:
        if RUNLOG.exists() and RUNLOG.stat().st_size > 400_000:
            keep = RUNLOG.read_text(encoding="utf-8").splitlines()[-1000:]
            RUNLOG.write_text("\n".join(keep) + "\n", encoding="utf-8")
        with open(RUNLOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def log_err(msg):
    """오류도 실행기록(로컬)에만. 저장소 오류기록.txt 엔 안 쓴다 (2026-09-22) — PC 가 거기 쓰면 커밋 안 된 줄이 남아
    upload_instagram 의 git pull 이 막히고(실제로 7커밋 뒤처져 있었음), 액션과 같은 파일에 양쪽이 덧붙여 충돌이 난다."""
    runlog("오류: " + msg)


# ── 저장: 전부 R2 (2026-09-21 "창고 하나") ─────────────────────────
# 대기줄·상태·답한것·기록·잠금이 R2 에 있어서 PC 와 깃허브가 **같은 것**을 본다.
# 그래서 어느 쪽이 답했든, 잡아뒀든 서로 알고 같은 댓글에 두 번 안 단다.

def jload(path, default):
    """로컬 JSON 읽기 — 이제 쇼츠예약.json(글 발행량 세기) 같은 저장소 파일에만 쓴다."""
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log_err("%s 읽기 실패: %s" % (p.name, str(e)[:80]))
        return default


def load_done():
    return STORE.답한것_읽기()


def mark_done(reply_id, my_id, text):
    STORE.답한것_추가(reply_id)


def write_log(row, link=""):
    """판단 기록. 남의 생년월일이 들어가니 R2 에만, 하루 뒤 삭제.
    link = 그 댓글 주소. 6시간 요약에 무시·보류 링크로 붙는다 (2026-09-25 사장님 지시)."""
    keys = ["시각", "답글ID", "상대", "상대글", "라벨", "확신도", "이유", "처리", "답글문"]
    d = dict(zip(keys, row))
    if link:
        d["링크"] = link
    STORE.기록_추가(d)


# ── 텔레그램 ──────────────────────────────────────────────────────
def tg_send(vault, text, preview=True):
    tok, chat = vault.get("telegram_bot_token"), vault.get("telegram_chat_id")
    if not tok or not chat:
        log_err("텔레그램 토큰 없음")
        return None
    msg = {"chat_id": chat, "text": text[:4000]}
    if not preview:
        msg["disable_web_page_preview"] = "true"      # 링크 여러 개 붙은 요약에 미리보기 카드가 끼지 않게
    body = urllib.parse.urlencode(msg).encode("utf-8")
    try:
        with urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % tok, body, timeout=30) as r:
            return json.load(r).get("result", {}).get("message_id")
    except Exception as e:
        log_err("텔레그램 보내기 실패: %s" % e)
        return None


def tg_updates(vault, offset):
    tok = vault.get("telegram_bot_token")
    if not tok:
        return [], offset
    url = "https://api.telegram.org/bot%s/getUpdates?timeout=0&offset=%d" % (tok, offset)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            js = json.load(r)
    except Exception as e:
        log_err("텔레그램 읽기 실패: %s" % e)
        return [], offset
    out = []
    for u in js.get("result", []):
        offset = max(offset, u["update_id"] + 1)
        m = u.get("message") or {}
        txt = (m.get("text") or "").strip()
        rep = (m.get("reply_to_message") or {}).get("message_id")
        if txt:
            out.append((rep, txt))
    return out, offset


# ── 스레드 API ────────────────────────────────────────────────────
def vault_open():
    """스레드 토큰은 금고(토큰.enc, 저장소 공용). 금고 열쇠와 텔레그램은 —
    PC: ~/.saju_meta_tokens.json / 깃허브: 보관함(Secrets) 에서."""
    if WHO == "깃허브":
        page_tok = os.environ.get("IG_ACCESS_TOKEN", "").strip()
        if not page_tok:
            sys.exit("보관함에 IG_ACCESS_TOKEN 없음")
        v = 금고.load(page_tok, REPO / "토큰.enc")
        v["telegram_bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        v["telegram_chat_id"] = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        return v
    local = json.load(open(TOKEN_FILE, encoding="utf-8"))
    page_tok = (local.get("pages") or [{}])[0].get("page_token")
    if not page_tok:
        sys.exit("토큰 파일에 page_token 없음")
    v = 금고.load(page_tok)
    for k in ("telegram_bot_token", "telegram_chat_id"):
        if local.get(k):
            v[k] = local[k]
    return v


def th_get(tok, path, **params):
    params["access_token"] = tok
    url = API + path + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=40) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError("스레드 GET %s %s: %s" % (path, e.code, e.read().decode("utf-8", "replace")[:300]))


def th_post(tok, path, **params):
    params["access_token"] = tok
    body = urllib.parse.urlencode(params).encode("utf-8")
    try:
        with urllib.request.urlopen(urllib.request.Request(API + path, body), timeout=40) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError("스레드 POST %s %s: %s" % (path, e.code, e.read().decode("utf-8", "replace")[:300]))


def th_get_all(tok, path, max_pages=10, **params):
    """페이지를 끝까지 따라가며 data 를 모은다.

    /conversation 은 기본 25개만 준다. 그대로 쓰면 **대화가 길어졌을 때 최신 댓글이 잘려 나가고**,
    스크립트는 "새 답글 0" 이라고 보고한다 (2026-09-21 겪음 — 3턴째 댓글을 20분 동안 못 잡았다).
    """
    params["access_token"] = tok
    params.setdefault("limit", 100)
    url = API + path + "?" + urllib.parse.urlencode(params)
    out = []
    for _ in range(max_pages):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=40) as r:
                js = json.load(r)
        except urllib.error.HTTPError as e:
            raise RuntimeError("스레드 GET %s %s: %s" % (path, e.code, e.read().decode("utf-8", "replace")[:300]))
        out.extend(js.get("data", []))
        url = (js.get("paging") or {}).get("next")
        if not url:
            break
    return out


def reply_quota_left(tok, uid):
    """메타가 정한 오늘 답글 한도에서 몇 개 남았나. 못 읽으면 None(막지 않는다).

    우리 상한(MAX_PER_DAY)만 믿으면 안 된다 — 쇼츠 첫 답글(링크)과 손으로 단 답글도
    같은 한도를 먹기 때문에, 자동 답글이 다 써 버리면 그것들이 막힌다.
    """
    try:
        d = th_get(tok, uid + "/threads_publishing_limit",
                   fields="reply_quota_usage,reply_config")["data"][0]
        return d["reply_config"]["quota_total"] - d["reply_quota_usage"]
    except Exception as e:
        log_err("답글 한도 조회 실패: %s" % str(e)[:100])
        return None


_last_reply_local = [0.0]        # R2 에 못 적었을 때를 대비한 이 프로세스 안 기록


def reply_gap_left():
    """마지막 답글 뒤 2분이 안 지났으면 남은 초 (2026-09-25 사장님 지시: 답글 사이 최소 2분).
    R2 의 마지막답글.json 을 본다 — PC·깃허브·AI자동답변이 다 같은 시각을 본다."""
    passed = []
    try:
        last = (STORE.읽기("마지막답글.json") or {}).get("때")
        if last:
            passed.append((now() - dt.datetime.strptime(last, "%Y-%m-%d %H:%M:%S")).total_seconds())
    except Exception as e:
        log_err("마지막답글 시각 못 읽음: %s" % str(e)[:80])
    if _last_reply_local[0]:
        passed.append(time.time() - _last_reply_local[0])
    return max(0, int(REPLY_GAP_SEC - min(passed)) + 1) if passed else 0


def publish(tok, uid, reply_id, text):
    """답글 하나 올린다. **앞 답글과 2분이 안 됐으면 기다렸다가** 올린다 (여기가 답글 나가는 유일한 문)."""
    wait = reply_gap_left()
    if wait > 0:
        runlog("  2분 간격: %d초 기다림" % wait)
        time.sleep(wait)
    c = th_post(tok, uid + "/threads", media_type="TEXT", text=text, reply_to_id=reply_id)
    time.sleep(5)
    mid = th_post(tok, uid + "/threads_publish", creation_id=c["id"]).get("id")
    _last_reply_local[0] = time.time()
    try:
        STORE.쓰기("마지막답글.json", {"때": now().strftime("%Y-%m-%d %H:%M:%S"), "누가": WHO})
    except Exception as e:
        log_err("마지막답글 시각 못 적음: %s" % str(e)[:80])      # 답은 나갔다. 이 프로세스 안에선 로컬 시각으로 막는다
    return mid


def build_chain(by_id, c, limit=12, 머리=3):
    """이 답글까지 오는 대화 줄기 (오래된 것 → 최신). 내 답글도 포함해야 앞에 뭘 말했는지 안다.

    **맨 앞 몇 칸은 무슨 일이 있어도 남긴다** (2026-09-24 사고).
    손님은 생년월일을 **첫 마디에** 준다. 그런데 줄기가 길어지면 앞에서부터 잘려 나가
    사주가 통째로 사라지고, 7턴째 손님한테 "생년월일 알려줄래?" 하고 되물었다
    (@coco_eunstar: 13칸 대화에 한도 12칸, 잘린 0번 칸에 '82.05.05 음력, 09:37 여자').
    12턴 넘는 대화는 전부 이렇게 됐다.

    그래서 자를 때 앞이 아니라 **가운데**를 버린다 — 맨 앞 머리칸 + 최근 것들.
    """
    전체, cur, seen = [], c, set()
    while cur and cur["id"] not in seen and len(전체) < 60:      # 60 은 안전장치
        seen.add(cur["id"])
        who = "나" if cur.get("username") == ME else "@" + str(cur.get("username"))
        전체.append("%s: %s" % (who, (cur.get("text") or "").replace("\n", " ")[:300]))
        cur = by_id.get((cur.get("replied_to") or {}).get("id"))
    전체.reverse()                                               # 오래된 것 → 최신
    if len(전체) <= limit:
        return 전체
    머리칸 = 전체[:머리]
    꼬리칸 = 전체[-(limit - 머리 - 1):]
    return 머리칸 + ["(사이 %d마디 줄임)" % (len(전체) - len(머리칸) - len(꼬리칸))] + 꼬리칸


def post_age_days(p):
    """글이 올라간 지 며칠 됐나. 시각을 못 읽으면 0(최신 취급)."""
    try:
        t = dt.datetime.strptime((p.get("timestamp") or "")[:19], "%Y-%m-%dT%H:%M:%S")
        return (dt.datetime.utcnow() - t).total_seconds() / 86400
    except Exception:
        return 0.0


def collect(tok, uid, deep=None):
    """일주일치 내 글의 대화 전체 → 내가 아직 답 안 한 답글. 대댓글 체인 포함.

    글 개수로 자르지 않고 **날짜로** 자른다(하루 3~5개씩 올리니 개수로 자르면 며칠치밖에 못 본다).
    deep=False 면 최근 HOT_DAYS 일 글만 본다 — 오래된 글엔 새 댓글이 드물어서 매 5분마다 볼 필요가 없다.
    """
    if deep is None:
        deep = now().minute < 5            # 5분마다 도니까 한 시간에 한 번만 깊게 훑는다
    posts = [p for p in th_get_all(tok, uid + "/threads",
                                   fields="id,text,permalink,timestamp,is_reply", limit=100, max_pages=3)
             if not p.get("is_reply")]
    limit_days = POST_AGE_DAYS if deep else HOT_DAYS
    posts = [p for p in posts if post_age_days(p) <= limit_days]
    done = load_done()
    rows = []
    for p in posts:
        try:
            conv = th_get_all(tok, p["id"] + "/conversation",
                              fields="id,text,username,timestamp,permalink,replied_to,is_reply_owned_by_me",
                              reverse="false")
        except RuntimeError as e:
            log_err("대화 조회 실패 %s: %s" % (p["id"], e))
            continue
        by_id = {c["id"]: c for c in conv}
        mine_ids = {c["id"] for c in conv if c.get("username") == ME or c.get("is_reply_owned_by_me")}
        answered = {(c.get("replied_to") or {}).get("id") for c in conv if c["id"] in mine_ids}
        for c in conv:
            if c["id"] in mine_ids or c["id"] in done or c["id"] in answered:
                continue
            used = sum(1 for m in conv if m["id"] in mine_ids
                       and ((by_id.get((m.get("replied_to") or {}).get("id")) or {}).get("username") == c.get("username")))
            # 홍보를 이미 했나 — **안 자른 원문**으로 잰다. 줄기(300자 자름)로 재면 놓친다.
            # 같은 글 안에서 이 손님에게 단 내 답글을 전부 본다(옆가지 포함).
            내답들 = [(m.get("text") or "") for m in conv if m["id"] in mine_ids
                      and (by_id.get((m.get("replied_to") or {}).get("id")) or {}).get("username") == c.get("username")]
            rows.append({"post": p, "reply": c, "used": used, "turn": used + 1,
                         "홍보함": any(w in t for t in 내답들 for w in PROMO_WORDS),
                         "리포스트함": any(w in t for t in 내답들 for w in 리포스트말),
                         "프로필함": any(w in t for t in 내답들 for w in 프로필말),
                         "chain": build_chain(by_id, c)})
    return rows


# ── 규칙 필터 (LLM 부르기 전. 여기서 걸리면 돈 안 씀) ──────────────
def prefilter(row):
    # 사장님이 직접 챙기기로 한 사람은 봇이 아예 손대지 않는다 (2026-09-25).
    # 손님이 디엠으로 넘어갔는데 스레드에서 또 말 걸면 겹친다
    try:
        if STORE is not None and (row["reply"].get("username") or "") in STORE.손대지마_목록():
            return "사장님이 직접 챙기는 사람"
    except Exception:
        pass
    t = (row["reply"].get("text") or "").strip()
    if not t:
        return "빈 글"
    if len(t) <= MIN_LEN:
        return "너무 짧음(%d자)" % len(t)
    if not re.search(r"[가-힣a-zA-Z0-9]", t):
        return "이모지·기호만"
    if re.search(r"https?://|t\.me/|오픈채팅|open\.kakao", t, re.I):
        return "링크·홍보"
    if row["used"] >= MAX_PER_PERSON:
        return "같은 사람과 %d번 주고받음(상한)" % row["used"]
    return None


# ── claude 호출 ───────────────────────────────────────────────────
def claude(prompt, schema, model, sys_prompt, timeout=240, 부르는곳="?"):
    """claude -p 로 JSON 하나 받는다. 구독으로 돈다(API 키 없음). 실패하면 {'__오류__': ...}."""
    # --tools/--disallowedTools 로 **도구를 아예 안 싣는다.**
    # 도구 설명이 요청마다 2만 7천 토큰을 먹고 있었다 → 1,400 으로 줄었다(2026-09-21 실측, 93% 절감).
    # 우리는 글만 받으면 되니 도구가 필요 없다.
    cmd = ["claude", "-p", prompt, "--output-format", "json",
           "--json-schema", json.dumps(schema, ensure_ascii=False),
           "--model", model, "--safe-mode", "--system-prompt", sys_prompt,
           "--tools", "Read", "--disallowedTools", "Read"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"__오류__": "시간 초과"}
    if r.returncode != 0:
        return {"__오류__": "claude 실행 실패: %s" % (r.stderr or "")[:150]}
    try:
        outer = json.loads(r.stdout)
    except Exception:
        return {"__오류__": "claude 출력이 JSON 아님"}
    # 토큰·값 기록 (2026-09-24). is_error 검사 **앞**에 둔다 — 실패한 호출도 토큰은 나가니까.
    # 통째로 try 라 여기서 뭐가 터져도 답글 흐름은 안 멈춘다.
    try:
        _u = outer.get("usage") or {}
        _값 = float(outer.get("total_cost_usd") or 0)
        _줄 = {"때": now().strftime("%Y-%m-%d %H:%M:%S"), "누가": WHO, "무엇": 부르는곳,
               "모델": model, "입력": _u.get("input_tokens", 0),
               "생성": _u.get("cache_creation_input_tokens", 0),
               "읽기": _u.get("cache_read_input_tokens", 0),
               "출력": _u.get("output_tokens", 0), "값": round(_값, 5)}
        runlog("토큰 %s/%s 입력%s 생성%s 읽기%s 출력%s $%.4f" % (
            부르는곳, model, _줄["입력"], _줄["생성"], _줄["읽기"], _줄["출력"], _값))
        if STORE is not None:                    # 클라우드(R2)에도. --test 때는 창고가 없다
            STORE.토큰_적기(_줄)
    except Exception:
        pass
    if outer.get("is_error"):
        msg = str(outer.get("result"))
        # 로그인 만료는 사장님이 손을 써야 풀린다(터미널에서 claude → /login).
        # 그냥 "처리 못 함"으로 보내면 무슨 일인지 모르고 며칠 답글이 안 나간다.
        if re.search(r"authenticat|OAuth|Login expired|로그인", msg, re.I):
            return {"__오류__": "로그인만료: %s" % msg[:120]}
        return {"__오류__": "claude 오류: %s" % msg[:150]}
    m = re.search(r"\{.*\}", (outer.get("result") or "").strip(), re.S)
    if not m:
        return {"__오류__": "결과에 JSON 없음"}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"__오류__": "결과 JSON 깨짐"}


# ── 1단계: 분류 + 생년 추출 ───────────────────────────────────────
EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": ["답함", "동업자", "악의"]},
        "confidence": {"type": "integer"},
        "reason": {"type": "string"},
        "year": {"type": "integer"}, "month": {"type": "integer"}, "day": {"type": "integer"},
        "hour": {"type": "integer"}, "minute": {"type": "integer"},
        "gender": {"type": "string", "enum": ["M", "F", ""]},
        "calendar": {"type": "string", "enum": ["solar", "lunar", ""]},
        "worry": {"type": "string"},
        "minor": {"type": "boolean"},
        # 2026-09-25: 감사·인사·가벼운 반응이냐. true 면 사주를 더 풀지 않고 짧게 한마디만 한다
        "light": {"type": "boolean"},
        # 두 사람 사주를 같이 준 경우(재회·궁합). 있으면 둘 다 풀어 준다 (2026-09-24)
        "year2": {"type": "integer"}, "month2": {"type": "integer"}, "day2": {"type": "integer"},
        "hour2": {"type": "integer"}, "minute2": {"type": "integer"},
        "gender2": {"type": "string", "enum": ["M", "F", ""]},
        "calendar2": {"type": "string", "enum": ["solar", "lunar", ""]},
    },
    "required": ["label", "confidence", "reason", "year", "month", "day", "hour", "minute", "gender", "calendar", "worry", "minor", "light"],
}

EXTRACT_PROMPT = """스레드 계정 @paljaoppa(팔자오빠)에 달린 댓글이다. 분류하고, 사주 정보를 뽑아라.

[내 원글]
{post}

[대화 줄기 (오래된 것 → 최신. "나" = 팔자오빠)]
{chain}

[지금 답해야 할 댓글]
@{user}: {text}

1) 분류
- 답함 : 평범한 사용자. 사주 봐달라는 요청, 질문, 공감, 감사, 잡담. **생년월일을 준 사람은 거의 다 여기다.**
- 보류 : **여기는 "답할지 말지 내가 못 정하겠다" 는 자리다.** 버리는 자리가 아니다.
  나중에 다른 기계가 앞 대화를 더 놓고 다시 본다. 애매하면 무조건 여기로 보내라.
  ("무시" 라는 답은 없다 — 2026-09-24 사장님 지시로 없앴다. 버리다가 열 건을 놓쳤다.)
  **★ 내가 앞에서 물은 것에 이 사람이 답한 것은 보류가 아니다. 무조건 '답함'이다.**
    대화 줄기의 마지막 "나" 줄이 물음으로 끝났으면 이번 댓글은 그 답이다.
    짧아도, 성의 없어 보여도, 새로 묻는 게 없어도 답함이다.
    (실제로 놓친 것들: "웅 있어....", "조금 쉬었다가 갈생각이야", "한텀걸리는 자리예요",
     "하나 둘 셋 넷 다섯 여섯 일곱? 정도", "요몇일 연락하다가 저번주 주말에 끊겼다")
    **내가 물어 놓고 그 답을 무시하면 손님은 씹힌 것이다.** 2026-09-24 이걸로 열 건을 놓쳤다.
  **★ 사주 재료를 새로 준 것도 무시가 아니다** — 성별·태어난 시간·띠·생년월일·양음력.
    성별을 모르면 대운을 순행·역행으로 못 갈라 **아예 빼고 풀었기 때문에**, 이제야 풀 수 있게 된 것이다.
    앞 풀이에 그 말이 나왔더라도 중복이 아니다 (예: "여자야", "🐷띠", "새벽 3시").
  **★ 감사·인사·가벼운 반응도 '답함' 이다** (2026-09-25 사장님 지시).
    "감사합니다" "고마워" "응 스하리~" "넵" 같은 말에도 답한다. 버리지 않는다.
    다만 **light = true** 로 표시해라. 그러면 사주를 더 풀지 않고 짧은 한마디만 나간다.
    light 가 true 인 것: 고맙다는 인사 · 웃음 · 감탄 · 가벼운 맞장구 ·
                        "메시지로 연락할게" 같은 마무리 인사 · 새로 묻는 게 없는 짧은 반응.
    light 가 false 인 것: 내가 물은 것에 답한 것 · 새로 묻는 것 · 사주 재료를 준 것 ·
                        자기 사정을 더 말한 것. **이건 제대로 풀어 줘야 한다.**
  **★ 뜻을 모르겠으면 보류가 아니라 답함이다.** 앞 대화에 견주면 거의 다 답이다.
    보류로 보낼 것은 "고마워요" "넵" "ㅋㅋ" 처럼 **더 받을 말이 없어 보이는 인사**뿐이고,
    그것조차 버리는 게 아니라 나중에 다시 보는 것이다.
- 동업자 : 다른 사주·운세 계정으로 의심됨. 계정명에 사주/운세/명리/타로/철학관,
          **내 산출 방식을 캐물음**(만세력 뭐 쓰냐, 절입·야자시 기준, 어떤 프로그램),
          내 풀이를 틀렸다고 지적하며 자기 해석을 붙임.
          (주의: 십신·대운 같은 말을 쓴다고 다 동업자가 아니다. 자기 사주를 묻는 사람은 '답함'이다.)
- 악의 : 조롱·욕설·비하·시비·희롱.

2) 사주 정보 — **대화 줄기 전체**에서 찾아라. 앞 댓글에서 생년월일을 주고 이번 댓글에서 성별만 준 경우도 있다.
- year/month/day: 양력 기준 없이 적힌 대로. "820322" = 1982년 3월 22일. "94년" 만 있고 월일이 없으면 month·day 는 0.
- 두 자리 연도는 00~09 면 2000년대, 10~99 면 1900년대.
- hour/minute: "오후 6시30분" = 18,30. 모르면 -1.
  **★ 한자 시간(12지 시)도 반드시 알아들어라. 이걸 놓쳐서 손님한테 시각을 또 물은 사고가 일주일에 6번 났다(2026-09-24).**
    자시=0, 축시=2, 인시=4, 묘시=6, 진시=8, 사시=10,
    오시=12, 미시=14, 신시=16, 유시=18, 술시=20, 해시=22  (minute 은 0)
    "자시"처럼 '시' 없이 "묘"·"미"로만 적어도 같다. "야자시"·"조자시"도 자시(0)로 본다.
  **★ 범위로 적어도 가운데 값을 쓴다.** "오전 7-9시" = 8,0 / "새벽 3~5시" = 4,0 / "저녁 6시쯤" = 18,0
  **★ "새벽 5시"·"아침 7시" 같은 말도 숫자로 바꾼다.** 새벽/아침=그대로, 낮/오후/저녁/밤 = +12(12시는 그대로).
  **손님이 시각을 어떤 식으로든 한 번이라도 적었으면 hour 를 -1 로 두지 마라.**
- gender: 남자/남 = M, 여자/여 = F, 없으면 빈 문자열.
  **★ "여"·"남" 한 글자만 적어도 잡아라.** "890206 시간몰라 여" → F.
  "여자에요", "내가 여자", "남임", "남자야" 도 전부 잡는다.
  **대화 줄기 어디에든 한 번이라도 나왔으면 그 값을 쓴다.**
- calendar: 음력이라고 적혀 있으면 lunar, 아니면 solar.
- **★ 한 사람이 자기 생일을 양력·음력 둘 다 적는 일이 흔하다. 그건 헷갈릴 일이 아니다** (2026-09-25).
  예: "890215 양 / 890110 음 / 13시 40분 / 남" — 한 사람이 같은 날을 두 가지로 적은 것이다.
  이럴 때 **양력 쪽을 year/month/day 에 넣고 calendar 는 solar**, 음력 쪽은 year2~calendar2 에 넣어라.
  같은 날인지 아닌지는 **기계가 엔진으로 돌려서 판별한다.** 네가 고민하지 마라.
  그리고 **이걸로 확신(confidence)을 깎지 마라.** 생년월일이 또렷하게 적혀 있으면 90 이상이다.
- **★ 사주를 두 사람 것 주면(재회·궁합) 두 번째 사람을 year2~calendar2 에 넣어라.**
  (예: "891018 신시 양력 남 900402 묘시 양력 여 재회가능할지"
   → 첫째 1989-10-18 16시 M, 둘째 1990-04-02 6시 F)
  **누가 본인인지 고르지 마라.** 앞에 적은 사람을 첫째로 둔다. 둘 다 풀어 줄 것이다.
  한 사람만 있으면 year2 는 0 으로 둔다.
- 없는 값은 year/month/day 는 0, hour/minute 는 -1 로 둔다. **추측해서 채우지 마라.**
- worry: 뭘 물었는지 짧게(한국어) (직장운, 재물운, 결혼, 이직, 없으면 빈 문자열).
- **minor: 이 사람이 미성년으로 보이면 true.** 생년이 없어도 말로 드러나면 true 다.
  신호: 중학생·고등학생·중2·고1·학생이라·교복·수능·내신·야자·급식·엄마한테 물어봐야·미성년·17살·18살 같은 어린 나이.
  **애매하면 true 로 둔다.** 잘못 true 하면 답글 하나 안 나갈 뿐이지만, 잘못 false 하면 미성년에게 사주를 봐 주게 된다.

애매하면 확신도를 낮춰라. 85 미만은 사람이 직접 본다. JSON 하나만 출력."""


# 12지 시 → 시작 시각의 가운데 (자시는 23~01 이라 0시로 본다)
BRANCH_HOUR = {"자": 0, "축": 2, "인": 4, "묘": 6, "진": 8, "사": 10,
               "오": 12, "미": 14, "신": 16, "유": 18, "술": 20, "해": 22}


def 글에서_시각(chain_text):
    """대화 줄기에서 시각을 직접 찾는다. AI 가 흘린 걸 코드로 한 번 더 건진다 (2026-09-24 사고).

    일주일에 6번, 손님이 '묘시'·'미시'·'오전 7-9시' 라고 적었는데 못 알아듣고 또 물었다.
    """
    t = chain_text
    # "시간 몰라"라고 했으면 손대지 않는다. 생년월일 숫자(890206시간)에서 '06시'를 잘못 줍는 걸 막는다
    if re.search(r"시\s*(간|각)?\s*(몰라|모름|모르|기억\s*안)", t):
        return None
    m = re.search(r"([자축인묘진사오미신유술해])\s*시(?!\s*(간|각))", t)
    if m:
        return BRANCH_HOUR[m.group(1)], 0
    m = re.search(r"(오전|오후|새벽|아침|낮|저녁|밤)?\s*(?<!\d)(\d{1,2})\s*[-~]\s*(\d{1,2})\s*시", t)   # 범위
    if m:
        h = (int(m.group(2)) + int(m.group(3))) / 2
        if m.group(1) in ("오후", "저녁", "밤") and h < 12:
            h += 12
        return int(h), 0
    # (?<!\d) — 앞에 숫자가 붙어 있으면 생년월일의 일부다("890206시간" 의 06)
    m = re.search(r"(오전|오후|새벽|아침|낮|저녁|밤)?\s*(?<!\d)(\d{1,2})\s*시\s*(?:(\d{1,2})\s*분)?", t)
    if m:
        h, mi = int(m.group(2)), int(m.group(3) or 0)
        if m.group(1) in ("오후", "저녁", "밤") and h < 12:
            h += 12
        if 0 <= h <= 24:
            return (h % 24), mi
    return None


# 남의 사주를 같이 적을 때 쓰는 말. 이게 있으면 성별을 코드로 안 건진다(누구 것인지 모른다)
OTHER_PERSON = re.compile(r"(상대|그\s*사람|남친|여친|남편|아내|와이프|전남|전여|애인|배우자|couple|둘\s*다|두\s*사람"
                          r"|남자는|여자는|남자가|여자가|남자\s*쪽|여자\s*쪽)")


def 글에서_성별(chain_text):
    """'여' 한 글자도 잡는다. 두 사람 얘기면 손대지 않는다(누구 성별인지 알 수 없다)."""
    if OTHER_PERSON.search(chain_text):
        return None
    남 = re.search(r"(남자|남성|남임|남이야|male|(?<![가-힣])남(?![가-힣]))", chain_text)
    여 = re.search(r"(여자|여성|여임|여야|female|(?<![가-힣])여(?![가-힣]))", chain_text)
    if bool(남) == bool(여):
        return None                      # 둘 다 있거나 둘 다 없으면 사람이 판단
    return "M" if 남 else "F"


def extract(row):
    ex = claude(EXTRACT_PROMPT.format(
        post=(row["post"].get("text") or "")[:600],
        chain="\n".join(row["chain"][:-1]) or "(없음)",
        user=row["reply"].get("username"),
        text=(row["reply"].get("text") or "")[:500],
    ), EXTRACT_SCHEMA, MODEL_EXTRACT, "너는 댓글 분류기다. 지시한 JSON 하나만 출력한다.",
        부르는곳="분류추출")
    if "__오류__" in ex:
        return ex
    # ── AI 가 흘린 것을 코드로 건진다 (2026-09-24). 손님이 적은 걸 또 묻는 게 제일 화나는 일이다
    줄기 = "\n".join(row["chain"])
    if int(ex.get("hour", -1) or -1) < 0:
        찾음 = 글에서_시각(줄기)
        if 찾음:
            ex["hour"], ex["minute"] = 찾음
            ex["reason"] = (ex.get("reason") or "") + " | 시각은 글에서 직접 건짐(%d시)" % 찾음[0]
    if not ex.get("gender"):
        g = 글에서_성별(줄기)
        if g:
            ex["gender"] = g
            ex["reason"] = (ex.get("reason") or "") + " | 성별은 글에서 직접 건짐(%s)" % g
    return ex


# ── 2단계: 만세력 엔진 ────────────────────────────────────────────
def engine_facts(y, m, d, hh, mi, gender, calendar):
    """saju-arcade 엔진으로 사주 팩트. 재구현 금지 — 이 엔진이 단일 진실 소스다."""
    hh_arg = "x" if hh is None or hh < 0 else str(hh)
    mi_arg = str(mi if mi and mi >= 0 else 0)
    g = gender if gender in ("M", "F") else "M"      # 성별 없으면 M 으로 계산하되 대운은 안 쓴다
    cmd = ["npx", "tsx", "report/dump-saju.ts", str(y), str(m), str(d), hh_arg, mi_arg, g,
           "lunar" if calendar == "lunar" else "solar"]
    # 윈도우는 npx 가 .cmd 라 shell 이 있어야 찾는다. 리눅스(깃허브)에서 shell=True 로 목록을 주면
    # 첫 낱말(npx)만 실행되고 나머지 인자가 버려진다 → 거기선 shell 없이.
    r = subprocess.run(cmd, cwd=str(ARCADE), capture_output=True, timeout=180,
                       encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, shell=(os.name == "nt"))
    if r.returncode != 0:
        raise RuntimeError("엔진 실패: %s" % (r.stderr or "")[:200])
    return json.loads(r.stdout)


def facts_digest(j, gender_known):
    """엔진 JSON(27KB)에서 풀이에 쓸 것만 추린다. 여기 없는 말은 풀이에 못 쓴다."""
    r = j["result"]
    out = {
        "일주": next((p["ganzhi"] for p in r["pillars"] if p["name"] == "일주"), ""),
        "일간": "%s(%s)" % (r["dayMaster"]["korean"], r["dayMaster"]["element"]),
        "띠": r["zodiacAnimal"]["label"],
        "네기둥": ["%s %s : 천간 %s(%s,%s) / 지지 %s(%s,%s)" % (
            p["name"], p["ganzhi"], p["gan"]["korean"], p["gan"]["element"], p["gan"].get("tenGod") or "일간",
            p["ji"]["korean"], p["ji"]["element"], p["ji"].get("tenGod") or "-") for p in r["pillars"]],
        "오행개수": r["elementCounts"],
        "강한오행": r["strongest"], "약한오행": r["weakest"],
        "시간모름": r.get("timeUnknown", False),
        "양력생일": r.get("solarDate", ""),
        "보정": r.get("corrections", []),
        "원국관계": ["%s — %s" % (x.get("name"), x.get("note", "")) for x in j.get("natalInteractions", [])],
        "올해": "%d년" % now().year,
        "세운": ["%d년 %s : 천간 %s / 지지 %s%s%s" % (
            s["year"], s["korean"], s["ganTenGod"], s["jiTenGod"],
            (" [" + ", ".join(x["name"] for x in s.get("interactions", [])) + "]") if s.get("interactions") else "",
            "  ← 올해" if s["year"] == now().year else ("  ← 내년" if s["year"] == now().year + 1 else ""))
            for s in j.get("seun", [])[:6]],
        "일간설명": (j.get("texts", {}).get("ilgan") or {}).get("desc", ""),
        "약한오행설명": j.get("texts", {}).get("elementWeak", ""),
        "강한오행설명": j.get("texts", {}).get("elementStrong", ""),
    }
    if gender_known:
        cur = now().year
        out["대운"] = ["%d세~(%d년~) %s : 천간 %s / 지지 %s%s%s" % (
            d["startAge"], d["startYear"], d["ganzhiKorean"], d["ganTenGod"], d["jiTenGod"],
            (" [" + ", ".join(x["name"] for x in d.get("interactions", [])) + "]") if d.get("interactions") else "",
            "  ← 지금 여기" if d["startYear"] <= cur < d["startYear"] + 10 else "")
            for d in j.get("daeunAnalyzed", [])[:8]]
    else:
        out["대운"] = "성별을 몰라서 계산 안 함 (대운은 성별에 따라 순행·역행이 갈린다)"
    return out


# ── 3단계: 풀이 작성 ──────────────────────────────────────────────
WRITE_SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string"}, "note": {"type": "string"}},
    "required": ["reply", "note"],
}

WRITE_PROMPT = """너는 스레드 계정 @paljaoppa(팔자오빠)로 답글을 쓴다.
만세력 엔진이 계산한 사주를 보고 **진짜로 풀어준다**. 반말, 1인칭 "나", 담백하게.
프로필에 "사람이 봐주는 데 아니라 만세력 표 뽑는 곳"이라고 이미 밝혀 놨으니 풀어줘도 된다.

[내 원글]
{post}

[대화 줄기 (오래된 것 → 최신. "나" = 나)]
{chain}

[지금 답할 댓글]
@{user}: {text}
이 사람이 궁금해하는 것: {worry}

[만세력 엔진이 계산한 사주 — **이 안에 있는 것만 쓴다**]
{facts}

[빠진 정보] {missing}
[지금 몇 번째 주고받음] {turn}번째

## 이번 글의 톤 ({turn}번째 주고받음)
{tone}

## 어떻게 쓰나

**0) 대화 줄기를 처음부터 끝까지 읽어라.**
   - 앞에서 내가 이미 말한 풀이를 **다시 설명하지 마라.** 같은 말 두 번 하면 봇인 게 티 난다.
   - 상대가 **이번에 새로 꺼낸 얘기**에 먼저 반응해라. 그게 이 답글의 출발점이다.
   - 내가 앞에서 물어본 것에 상대가 답했으면, 그 답을 받아서 이어라.
   - 상대의 말투·길이에 맞춰라. 짧게 쓰면 짧게, 길게 털어놓으면 받아 줘라.

**1) 엔진 값에만 근거한다.** 위 표에 없는 글자·관계·연도를 지어내면 안 된다. 상대가 검증하면 바로 들킨다.
   **연도를 말할 땐 반드시 서기 연도를 붙여라** (예: "2026년 병오년"). 올해가 몇 년인지는 위 표의 "올해"에 있다.
   "내년", "올해" 같은 말은 표에 붙은 ← 올해 / ← 내년 표시와 **반드시 맞춰라.** 여기서 틀리면 다 틀린 걸로 보인다.
   쓸 수 있는 것: 일주·띠·네 기둥의 십신, 오행 개수, 원국 관계(충·합·원진), 세운(그 해 십신), 대운(있을 때만).
   대운이 "성별을 몰라서 계산 안 함"이면 **대운·나이 얘기를 절대 하지 마라.**
   시간모름이 true 면 시주·시지 얘기를 하지 마라.

**2) 근거를 한 번은 드러낸다.** "시지 유금이 월지 묘목이랑 부딪혀서" 처럼 어느 글자 때문인지 짧게 붙인다.
   그래야 띠별 운세가 아니라 네 사주라는 게 보인다. 다만 한자 남발은 하지 말고 한글로.

**3) 상대가 물은 것에 먼저 답한다.** 직장운을 물었으면 직장 얘기부터.

**4) 마지막 줄은 반드시 되묻는다. 댓글이 한 번 더 붙어야 한다.**
{turn_guide}

## 지켜야 할 것
- 4~7줄, 500자 안. 줄을 나눠 쓴다.
- 링크·URL 절대 넣지 않는다. 해시태그 없음. 줄표(—) 없음.
- 확언하지 않는다. "반드시", "100%", "정확" 같은 말 금지.
- 건강·병·수술·죽음·임신, 주식·투자·부동산·로또, 부적·굿 얘기 금지. 법으로 막혀 있다.
- "전문가가 직접 감정" 같은 말 금지. 사람이 보는 게 아니다.
- 상대를 가르치거나 훈계하지 않는다.

{fix}
JSON 하나만 출력. note 에는 어느 엔진 값을 근거로 썼는지 한 줄."""

# ── 턴마다 무엇을 하나 (2026-09-25 사장님 지시로 깔때기를 다시 짰다) ──────────
#
#   1턴  풀이 + 되물음 + "복채 안 받아, 리포스트 하나면 충분"
#   2턴  풀이 + 되물음만
#   3턴  풀이 + 되물음 + 프로필 안내 (여기서 더 자세히 본다 = 유료)
#   4턴  3턴에 못 했으면 여기서 프로필 안내
#   5턴  풀이 + 프로필 안내 + 마무리. **되묻지 않는다.** 여기서 끝
#
# 왜 리포스트를 1턴으로 옮겼나
#   1턴이 전체의 40.8%(최근 3일 206건 중 84건)다. 3턴부터 청하면 그 84명은
#   리포스트 얘기를 아예 못 듣고 떠났다. 1턴으로 옮기면 206건 전원에 닿는다.
#   대신 **결이 중요하다.** "리포스트 해줘"로 나가면 1턴부터 광고 계정으로 보여 바로 닫힌다.
#   "복채는 안 받는다"는 말로 시작해야 받아내는 말이 아니라 안 받는다는 말이 된다.
#
# 왜 5턴에서 끊나
#   5턴까지 무료로 보여주고 더 깊은 건 유료로 넘긴다. 6턴 넘는 손님은 9건(4.4%)뿐이고
#   그 사람들이 제일 깊게 붙은 사람이라 유료로 넘길 대상이다.
#   **5턴째는 되묻지 않는다.** 물어 놓고 문을 닫으면 손님이 진짜 씹힌 것이 된다.
TURN_GUIDE = {
    "빠짐": "빠진 정보가 있으니 그걸 청해라. 왜 필요한지 한마디 붙이면 더 준다 (예: 대운은 성별이 있어야 순행·역행이 갈린다).",

    "보통": ("풀이에서 자연스럽게 이어지는 걸 하나 물어라 (예: 지금 회사 계속 다닐 생각이야? 그거에 따라 시기를 다르게 본다).\n"
             "   ★ **맨 끝 줄은 반드시 물음표로 끝나는 질문 한 줄이다.** 알아주는 말이나 다독이는 말로 글을 닫지 마라.\n"
             "     그런 말은 쓰되 **그 뒤에 질문 한 줄이 더 와야 한다.** 여기서 대화가 끊기면 채널이 안 큰다."),

    "리포스트": ("풀이에서 자연스럽게 이어지는 걸 하나 물어라.\n"
                 "   ★ 그리고 **리포스트를 한 줄만** 청한다. 이번 글의 결: **{promo}**\n"
                 "     이 뜻은 살리되 문장은 네 말로 다시 써라. 그대로 베끼지 마라.\n"
                 "   ★ **반드시 '복채는 안 받는다'는 쪽에서 시작해라.** 달라고 하면 1턴부터 광고 계정으로 보여 바로 닫힌다.\n"
                 "     받아내는 말이 아니라 안 받는다는 말이라 부담이 없다. 구걸하듯 매달리지 말고 툭 던지듯 짧게 한 줄.\n"
                 "   ★ **여기서 프로필 얘기는 하지 마라.** 프로필은 나중 턴 몫이다.\n"
                 "   ★ 줄 순서: … 풀이 … → (끝에서 둘째 줄) 리포스트 한 줄 → **(맨 끝 줄) 물음표로 끝나는 질문 한 줄.**\n"
                 "     리포스트 줄로 글을 끝내면 안 된다. 그 뒤에 질문이 한 줄 더 와야 한다."),

    # 2026-09-25 사장님: "더 자세한 흐름은 프로필에서 볼 수 있어" 는 뭘 주는지를 안 말한다.
    # 손님은 "그래서 뭘?" 이 된다. **방금 물은 그 질문에 붙여서, 거기 가면 뭐가 있는지**를 말한다.
    "유료": ("풀이에서 자연스럽게 이어지는 걸 하나 물어라.\n"
             "   ★ 그리고 **더 궁금하면 인스타 디엠 보내라고 한 줄.** 대놓고 말해라, 돌려 말하지 마라.\n"
             "     **링크 주소는 쓰지 마라.** '프로필에 인스타 있어, 디엠 줘' 정도로 짧게.\n"
             "   ★ 매달리지 마라. 툭 던지고 넘어간다. 한 줄이면 된다.\n"
             "   ★ 줄 순서: … 풀이 … → (끝에서 둘째 줄) 디엠 한 줄 → **(맨 끝 줄) 물음표로 끝나는 질문 한 줄.**"),

    # 2026-09-25 사장님 지시. 서아(@eslyn_yes)가 "감사합니다" 에 이렇게 받아서 대화가 이어졌다:
    #   손님: 감사합니다
    #   서아: 고맙긴 / 아직 안 보여준 그림도 있는데
    #   손님: 오잉? 멀까 .. 댓글 반말 적는게 익숙지가 않네 ㅎ
    # 인사를 받아주되 **덜 보여준 게 있다**고 흘려서 다시 묻게 만든다.
    "가볍게": ("**이건 인사다. 사주를 더 풀지 마라.** 짧게 한마디만 받는다.\n"
               "   ★ **한두 줄.** 길면 안 읽는다. 표 얘기, 글자 얘기, 풀이 얘기 하지 마라.\n"
               "   ★ 고맙다는 말을 받아주되 **아직 안 본 자리가 있다**고 한 자락 흘려라.\n"
               "     (예: '고맙긴, 아직 안 짚은 자리도 있는데')\n"
               "     어디인지 자세히 말하지 마라. 궁금하게만 두고 멈춘다.\n"
               "   ★ **물음표로 끝내지 마라.** 묻지 말고 흘려라. 되물으면 취조가 된다.\n"
               "   ★ 리포스트·프로필·디엠 얘기 하지 마라. 여긴 그 자리가 아니다.\n"
               "   ★ 매달리지 마라. 또 오라는 말, 아쉬운 말 하지 마라."),

    "마무리": ("**마지막 턴이다. 여기서 대화를 닫는다.**\n"
               "   ★ **되묻지 마라. 물음표로 끝내지 마라.** 물어 놓고 문을 닫으면 손님이 씹힌 것이 된다.\n"
               "   ★ 순서: … 이번 풀이 … → 더 궁금하면 인스타 디엠 보내라고 한 줄 → 짧은 마무리 한 줄.\n"
               "     **링크 주소는 쓰지 마라.** '프로필에 인스타 있어, 디엠 줘' 정도.\n"
               "   ★ 마무리는 **짧고 담백하게.** 아쉬운 척, 매달리는 말, 또 오라는 말 하지 마라.\n"
               "     할 말 하고 툭 끊는 결이다.\n"
               "   ★ 왜 끊는지 변명하지 마라. 그냥 끝내라."),
}

# 대화가 깊어질수록 톤이 옮겨간다 (2026-09-21 사장님: "초반은 전문가, 3~4회 넘어가면 마음을 보듬어").
# 처음엔 실력을 보여야 믿고, 믿은 뒤에는 사람 말을 듣고 싶어 한다.
TONE_BY_TURN = [
    (2, "**전문가 톤.** 아직 널 못 믿는 단계다. 실력으로 눌러라.\n"
        "   사주 근거를 앞세우고 어느 글자 때문인지 또렷하게 짚어라. 상대가 '어 맞네' 할 만한 걸 먼저 말해라.\n"
        "   위로·공감은 아직 넣지 마라. 담백하게, 사실만."),
    (4, "**풀어 주는 단계.** 두세 번 주고받아 믿음이 생겼다. 이제 사람 말로 바꿔라.\n"
        "   상대가 방금 털어놓은 고생을 **먼저 알아준 다음** 사주를 붙여라. 순서가 중요하다.\n"
        "   전문어는 한두 개까지만 쓰고, 쓰면 바로 뒤에 쉬운 말로 풀어라 (예: 편재 — 밖으로 벌리는 돈).\n"
        "   상대가 스스로 말하지 않은 걸 짚어 주면 제일 크게 움직인다. 단정하지 말고 '~했을 거야'로."),
    (99, "**거의 사람 대 사람.** 여기까지 온 건 들어주길 바라서다.\n"
         "   사주는 양념만. 새 풀이를 억지로 꺼내지 마라. 짧고 따뜻하게, 과장된 감정은 없이."),
]


def tone_for(turn):
    for upto, text in TONE_BY_TURN:
        if turn <= upto:
            return text
    return TONE_BY_TURN[-1][1]


# 홍보(스하리·프로필)는 **한 대화에 딱 한 번**만 한다 (2026-09-21 사장님).
# 10번을 주고받아도 중간에 한 번 했으면 그걸로 끝. 매번 하면 광고 계정으로 보인다.
PROMO_WORDS = ("스하리", "프로필", "스크랩", "리포스트", "팔로우", "복채")
리포스트말 = ("스하리", "스크랩", "리포스트", "복채", "팔로우")   # 1턴에 청하는 것
프로필말 = ("프로필", "인스타")            # 3~4턴에 안내하는 것.
# **"디엠" 은 여기 넣지 마라** (2026-09-25). 손님이 짝사랑 상대한테 디엠 보낸 얘기를 하는데
# 우리가 전에 프로필을 말했다는 이유로 "디엠" 이 통째로 막혀 답글이 세 번 반려됐다(@nujousmik).
# 디엠은 평범한 말이다. 막을 것은 우리 홍보 문구뿐이다

# 3~4회차 마무리에서 쓸 결. **매번 하나를 무작위로 골라** 프롬프트에 넣는다
# (목록을 통째로 보여 주면 AI 가 늘 첫 줄만 베껴서 말투가 굳는다 — 2026-09-23 실측).
# 사장님 지시: "스하리 달라"가 아니라 "리포스트 해주면 고맙겠다" 쪽으로.
PROMO_LINES = [
    "도움 됐으면 리포스트 한 번만 해주라, 그게 나한텐 제일 큰 복채다",
    "이런 글이 남한테도 닿았으면 해서 그런다, 리포스트 해주면 고맙다",
    "복채는 안 받는다, 대신 리포스트 하나면 충분하다",
    "괜찮았으면 리포스트 한 번, 그거면 나는 됐다",
    "나 돈 받고 하는 거 아니라 리포스트가 전부다, 해주면 고맙다",
    "읽고 도움 됐으면 리포스트만 눌러주라, 그거 하나가 크다",
    "값은 안 받는다, 네 손가락 한 번이면 된다 (리포스트)",
    "리포스트 한 번이면 나한텐 충분한 값이다, 부담 갖지 말고",
    "맞는 것 같으면 리포스트 해주라, 그거 보고 또 누가 온다",
    "돈 대신 리포스트 받는다, 그게 제일 고맙다",
]


def promo_done(row):
    """이 손님에게 이미 스하리·프로필을 청했나.

    **줄기 문자열을 보면 안 된다** (2026-09-25 사고). 줄기는 한 줄을 300자로 자르는데
    홍보 문구는 늘 글 **끝**에 붙는다. 답글이 300자를 넘으면 홍보 줄이 잘려 나가서
    "아직 안 했네" 하고 또 청했다. 최근 10일에 **16명**한테 두 번 이상 나갔고
    @pnu_n_me 는 45분 안에 세 번 받았다.

    그래서 collect() 가 **안 자른 원문**으로 미리 재 둔 값을 쓴다.
    같은 글 안에서 그 손님에게 단 내 답글을 전부 본다 — 줄기에 안 걸리는 옆가지도 잡는다.
    """
    if isinstance(row, dict) and "홍보함" in row:
        return bool(row["홍보함"])
    줄기 = row.get("chain", []) if isinstance(row, dict) else row       # 옛 호출 대비
    return any(line.startswith("나: ") and any(w in line for w in PROMO_WORDS) for line in 줄기)


def 사람표(y, m, d, hh, gender):
    """두 사람일 때 부르는 이름. "89년 10월 18일 신시생 남자" 꼴.

    섞여 담겨도 손님이 자기 생일을 보면 바로 안다 (2026-09-24 사장님 지시).
    시각을 모르면 시각을 빼고, 성별을 모르면 성별을 뺀다.
    """
    시 = ""
    if hh is not None and hh >= 0:
        지 = [k for k, v in BRANCH_HOUR.items() if abs(((hh - v) % 24 + 12) % 24 - 12) <= 1]
        시 = " " + (지[0] + "시") if 지 else " %d시" % hh
    성 = {"M": " 남자", "F": " 여자"}.get(gender or "", "")
    return "%d년 %d월 %d일%s생%s" % (y, m, d, 시, 성)


def 두사람표(row, facts):
    """엔진 표를 프롬프트에 넣을 글자로. 두 사람이면 둘을 이름표 붙여 나란히 놓는다 (2026-09-24).

    **누가 본인인지 고르지 않는다.** 고르면 틀리고, 틀리면 "내가 여자인데요" 소리를 듣는다.
    """
    if not facts:
        return "(생년월일을 안 줘서 사주를 못 뽑았다. 사주 얘기는 하지 말고, 생년월일을 청해라.)"
    if not row.get("facts2"):
        return json.dumps(facts, ensure_ascii=False, indent=1)
    return ("**두 사람 사주를 줬다. 둘 다 풀어 준다. 누가 본인인지 고르지 마라.**\n\n"
            "[첫째 — %s]\n%s\n\n[둘째 — %s]\n%s"
            % (row.get("who1", "앞에 적은 사람"), json.dumps(facts, ensure_ascii=False, indent=1),
               row.get("who2", "뒤에 적은 사람"), json.dumps(row["facts2"], ensure_ascii=False, indent=1)))


def write_reply(row, facts, missing, turn, fix=""):
    리포스트함 = bool(row.get("리포스트함"))
    프로필함 = bool(row.get("프로필함"))
    두사람 = bool(row.get("facts2"))
    if row.get("가볍게"):
        # 인사에는 짧게만 받는다. 홍보·빠진정보·마무리보다 이게 먼저다.
        # **금지어 목록은 여기도 줘야 한다** — 안 주면 쓰고 나서 세 번 반려되고 버려진다
        가벼운틀 = TURN_GUIDE["가볍게"] + (
            "\n   ★ **아래 말은 법으로 막힌 말이다. 한 글자도 쓰지 마라** (표시광고법·PG 심사):\n"
            "     %s\n"
            "     **그 글자가 들어간 어떤 말도 안 된다.**" % ", ".join(BANNED))
        return claude(WRITE_PROMPT.format(
            post=(row["post"].get("text") or "")[:400],
            chain="\n".join(row["chain"]) or "(없음)",
            user=row["reply"].get("username"),
            text=(row["reply"].get("text") or "")[:500],
            worry=row.get("worry") or "안 적음",
            facts="(인사에 짧게 받는 자리다. 사주 얘기는 하지 마라.)",
            missing="없음",
            turn=turn, turn_guide=가벼운틀, tone=tone_for(turn),
            fix=("\n## 다시 쓴다\n앞서 쓴 글이 이래서 반려됐다: **%s**\n같은 내용으로 그 부분만 고쳐서 다시 써라.\n" % fix) if fix else "",
        ), WRITE_SCHEMA, MODEL_WRITE, "너는 스레드에서 짧게 말 받는 사람이다. 지시한 JSON 하나만 출력한다.",
            부르는곳="가볍게")
    if turn >= LAST_TURN:
        guide = TURN_GUIDE["마무리"]              # 마지막 턴은 빠진 정보보다 닫는 게 먼저다
    elif missing:
        guide = TURN_GUIDE["빠짐"]
    elif turn >= PROMO_TURN and not 리포스트함:
        # 결을 매번 하나만 골라 넣는다. 목록째로 주면 AI 가 첫 줄만 베껴 말투가 굳는다
        guide = TURN_GUIDE["리포스트"].format(promo=random.choice(PROMO_LINES))
    elif turn >= PROFILE_TURN and not 프로필함:
        guide = TURN_GUIDE["유료"]
    else:
        guide = TURN_GUIDE["보통"]
    if row.get("같은날"):
        guide += ("\n   ★ **생년월일이 두 번 적혀 있는데 둘이 같은 날이다** (%s — 양력·음력으로 적은 것으로 보인다).\n"
                  "     그래서 사주가 글자까지 똑같다. **표는 한 사람 것만 준다. 한 사람 기준으로 풀어라.**\n"
                  "     · '상대' · '두 사람' · 궁합 · 관계 얘기를 꺼내지 마라. 아직 두 사람인지 모른다\n"
                  "     · 반대로 **한 사람이라고 단정하지도 마라.** 같은 날 같은 시에 태어난 두 사람도 있다\n"
                  "     · 풀이를 다 한 뒤 **끝에서 한 번만** 확인해라 — 본인 걸 양력·음력으로 두 번 적은 건지,\n"
                  "       아니면 진짜 다른 두 사람인지. 두 사람이면 사주가 같아서 이 풀이가 양쪽 다 맞는 말이다."
                  % row["같은날"])
    if 리포스트함 and turn < LAST_TURN:
        guide += ("\n   **이 손님에게는 이미 리포스트를 청했다. 다시 청하지 마라.**"
                  " 스하리·스크랩·하트·리포스트·팔로우·복채 라는 말을 아예 쓰지 마라.")
    if 프로필함 and turn < LAST_TURN:
        guide += ("\n   **이 손님에게는 이미 프로필을 안내했다. 다시 하지 마라.**"
                  " '프로필' 이라는 말을 아예 쓰지 마라.")
    # 금지어를 네 개만 적어 놨더니 AI 가 나머지를 모르고 썼다 (2026-09-24 @coco_eunstar:
    # "정확" 으로 세 번 연속 퇴짜 → 멀쩡한 풀이가 버려졌다). 목록 전체를 보여 준다.
    # BANNED 에서 뽑아 쓰니 목록이 바뀌어도 여기가 저절로 따라간다.
    guide += ("\n   ★ **아래 말은 법으로 막힌 말이다. 한 글자도 쓰지 마라** (표시광고법·PG 심사):\n"
              "     %s\n"
              "     **그 글자가 들어간 어떤 말도 안 된다.** '정확' 이 막히면 '정확히'·'정확한' 도 못 쓴다.\n"
              "     비슷한 뜻은 다른 말로 돌려라 (정확히 -> 또렷하게, 확실 -> 그럴 만해, 상담 -> 얘기)."
              % ", ".join(BANNED))
    if 두사람:
        guide = ("**사주를 두 사람 것 줬다(재회·궁합을 묻는 것이다). 둘 다 풀어 준다.**\n"
                 "   · 누가 본인인지 **고르지 마라.** 고르면 틀린다. 틀리면 '내가 여자인데요' 소리를 듣는다\n"
                 "   · **각 사람을 처음 부를 때 표에 적힌 이름표를 글자 그대로 한 번씩 쓴다.**\n"
                 "     (예: '89년 10월 18일 신시생 남자 쪽은 ~', '90년 4월 2일 묘시생 여자 쪽은 ~')\n"
                 "     날짜를 적어야 **혹시 내가 둘을 바꿔 읽었어도 손님이 바로 알아챈다.** 줄이거나 바꾸지 마라.\n"
                 "     두 번째부터는 '89년생 쪽' 처럼 짧게 불러도 된다. '너'·'상대'라고는 하지 마라\n"
                 "   · 한 사람에 두세 줄씩. 그 다음 **둘 사이에 뭐가 걸려 있는지** 한 덩어리로 (충·합·원진)\n"
                 "   · 짧게 써라. 두 사람이라 길어지기 쉬운데 **450자를 넘기면 안 된다**\n"
                 "   · 빠진 정보(시각·성별)를 먼저 청하지 마라. 있는 걸로 먼저 풀어 주고 궁금한 걸 마지막에 묻는다\n"
                 "   · 마지막은 질문으로 끝낸다.\n") + guide
    return claude(WRITE_PROMPT.format(
        post=(row["post"].get("text") or "")[:400],
        chain="\n".join(row["chain"]) or "(없음)",
        user=row["reply"].get("username"),
        text=(row["reply"].get("text") or "")[:500],
        worry=row.get("worry") or "안 적음",
        facts=두사람표(row, facts),
        missing=", ".join(missing) if missing else "없음",
        turn=turn, turn_guide=guide, tone=tone_for(turn),
        fix=("\n## 다시 쓴다\n앞서 쓴 글이 이래서 반려됐다: **%s**\n같은 내용으로 그 부분만 고쳐서 다시 써라.\n" % fix) if fix else "",
    ), WRITE_SCHEMA, MODEL_WRITE, "너는 만세력 표를 읽고 풀어 주는 사람이다. 지시한 JSON 하나만 출력한다.",
        부르는곳="풀이")


def tidy(text):
    """올리기 전 다듬기. 내용이 아니라 문장 부호 문제로 반려되는 걸 막는다.

    줄표(—)는 금지어라 들어가면 통째로 반려된다. 스레드하루치.py 도 같은 방식으로 쉼표로 바꾼다.
    """
    t = (text or "").strip()
    t = re.sub(r"\s*[—–―]\s*", ", ", t)        # "앞 — 뒤" → "앞, 뒤" (공백이 어정쩡하게 남지 않게)
    t = re.sub(r",\s*,", ",", t)
    t = re.sub(r"\s+,", ",", t)
    t = "\n".join(l.rstrip() for l in t.splitlines())
    return t.strip()


# 클로드가 딸꾹질할 때 뱉는 껍데기들. 짧은 답을 허용하면 이게 그대로 나갈 수 있다
껍데기말 = ("test", "reply", "test reply", "ok", "okay", "네", "예", "응", "알겠",
            "확인", "샘플", "sample", "답글", "네 알겠습니다")


def reply_ok(text, need_question=False, no_promo=False, 막을말=(), 짧게=False):
    """올려도 되는 글인지. 법적 금지어는 그대로 막는다.

    짧게=True 는 **인사에 한마디 받는 자리**다 (2026-09-25 사장님 지시).
    만세력 풀이가 아니라서 80자 규칙을 들이대면 멀쩡한 한마디가 버려진다.
    서아(@eslyn_yes)가 쓰는 "고맙긴, 아직 안 보여준 그림도 있는데" 는 18자다.
    대신 껍데기("ok", "네")는 따로 막는다 — 길이로 못 거르니 말로 거른다.
    """
    if not text or len(text) > 500:
        return "길이(%d)" % len(text or "")
    한글 = len(re.findall(r"[가-힣]", text))
    if 짧게:
        if 한글 < 6:
            return "너무 짧음(한글 %d자)" % 한글
        낮춤 = re.sub(r"[^0-9a-zA-Z가-힣]", "", text).lower()
        if 낮춤 in [re.sub(r"[^0-9a-zA-Z가-힣]", "", w).lower() for w in 껍데기말]:
            return "껍데기 글(%r)" % text[:20]
    else:
        # 클로드가 딸꾹질하면 "test reply" 같은 껍데기를 뱉는다. 2026-09-23 그게 손님 댓글에 그대로 나갔다.
        # 한 줄이면 아래에서 걸리지만 **여러 줄짜리 껍데기**는 안 걸린다 → 한글 글자 수로 본다.
        if 한글 < 80:
            return "껍데기 글(한글 %d자)" % 한글
        if len([l for l in text.splitlines() if l.strip()]) < 2:
            return "한 줄짜리"
    if need_question and not text.rstrip().endswith("?"):
        return "질문으로 안 끝남"
    # 2026-09-25: 막을 말을 턴마다 다르게 준다. 1턴에 리포스트를 청했어도
    # 3턴에는 프로필을 안내해야 하므로, 전부를 한꺼번에 막으면 안 된다
    막기 = tuple(막을말) if 막을말 else (PROMO_WORDS if no_promo else ())
    if 막기:
        hit = [w for w in 막기 if w in text]
        if hit:
            return "이미 한 안내 또 함 (%s)" % ", ".join(hit)
    for b in BANNED:
        if b in text:
            return "금지어 '%s'" % b
    if re.search(r"https?://|sajuarcade|#", text):
        return "링크·해시태그"
    return None


# ── 한 건 처리 ────────────────────────────────────────────────────
def handle(row, dry=False):
    """(라벨, 확신도, 이유, 답글문 or None, 보고사유 or None)"""
    ex = extract(row)
    if "__오류__" in ex:
        return "보류", 0, ex["__오류__"], None, ex["__오류__"]
    label, conf = ex.get("label", "보류"), int(ex.get("confidence") or 0)
    if label != "답함" or conf < CONFIDENCE:
        return label, conf, ex.get("reason", ""), None, "확신 부족" if label == "답함" else label

    y, m, d = int(ex.get("year") or 0), int(ex.get("month") or 0), int(ex.get("day") or 0)
    hh, mi = int(ex.get("hour", -1)), int(ex.get("minute", -1))
    gender, cal = ex.get("gender") or "", ex.get("calendar") or "solar"
    row["worry"] = ex.get("worry") or ""
    row["가볍게"] = bool(ex.get("light"))          # 인사면 짧게 한마디만 (2026-09-25)

    # 미성년은 **생년으로도, 말로도** 막는다. 생년이 없으면 "생년월일 알려줘"라고 되묻게 되는데
    # 그것부터가 미성년에게 말을 거는 일이다 (2026-09-21 사장님: "철벽 방어해야 하는데").
    if ex.get("minor"):
        return "미성년", conf, "미성년으로 보임 — 안 봄 (%s)" % ex.get("reason", "")[:60], None, "미성년(말로 드러남)"
    if y and y >= MINOR_BORN:
        return "미성년", conf, "%d년생 — 안 봄" % y, None, "미성년(%d년생)" % y

    facts, missing = None, []
    if y and m and d:
        try:
            j = engine_facts(y, m, d, hh, mi, gender, cal)
            facts = facts_digest(j, gender in ("M", "F"))
        except Exception as e:
            return "보류", conf, "엔진 실패: %s" % str(e)[:150], None, "엔진 실패"
        if not gender:
            missing.append("성별 (대운을 못 봄)")
        if hh is None or hh < 0:
            missing.append("태어난 시각")
        # ── 두 사람 사주를 줬으면 둘째도 뽑는다 (2026-09-24 사장님 지시 "둘 다 풀어준다").
        # 전에는 앞의 것만 풀었다가 "내가 여자인데요" 소리를 들었다. 누구 건지 고르지 않는 게 답이다.
        y2 = int(ex.get("year2") or 0)
        if (y2, int(ex.get("month2") or 0), int(ex.get("day2") or 0)) == (y, m, d):
            y2 = 0                    # 같은 사람을 둘로 잘못 뽑은 것 — 한 사람으로 본다
        if y2 and int(ex.get("month2") or 0) and int(ex.get("day2") or 0):
            if y2 >= MINOR_BORN:
                return "미성년", conf, "둘째가 %d년생 — 안 봄" % y2, None, "미성년(둘째 %d년생)" % y2
            try:
                j2 = engine_facts(y2, int(ex["month2"]), int(ex["day2"]),
                                  int(ex.get("hour2", -1)), int(ex.get("minute2", -1)),
                                  ex.get("gender2") or "", ex.get("calendar2") or "solar")
                # ── 두 값이 **같은 날**인지 본다 (2026-09-25 사장님 지시).
                # 날짜 숫자만 맞대면 못 잡는다. "890215 양 / 890110 음" 은 숫자가 달라도
                # 엔진을 돌리면 둘 다 1989-02-15 로 같은 날이다 (@17.s_l 실제 사례).
                # 그걸 모르고 궁합으로 단정해 "상대 고집" 같은 없는 말을 했다.
                #
                # **그렇다고 한 사람이라고 단정하지도 않는다.** 같은 날 같은 시에 태어난
                # 두 사람은 실제로 있다(쌍둥이 등). 사주가 같다 = 한 사람이다 는 틀린 말이다.
                # 그래서 풀이만 한 사람 기준으로 하고, 두 사람인지는 손님에게 묻는다.
                # 한 사람이었으면 처음부터 맞는 풀이고, 두 사람이었어도 사주가 같으니
                # 그 풀이가 양쪽 다 맞는 말이다. 어느 쪽이든 헛말이 안 나간다.
                # **양력 날짜만 맞댄다.** 네 기둥까지 맞대면 못 잡는다 —
                # 시각은 보통 한 번만 적어서 둘째는 시주가 비고, 그럼 기둥이 달라 보인다
                # (2026-09-25 @17.s_l 로 실측: 날짜는 같은데 기둥 비교에서 어긋났다).
                같은날 = bool(j2["result"].get("solarDate")) and                          j2["result"].get("solarDate") == j["result"].get("solarDate")
                if 같은날:
                    row["같은날"] = 사람표(y2, int(ex["month2"]), int(ex["day2"]),
                                          int(ex.get("hour2", -1)), ex.get("gender2"))
                    raise StopIteration                # 아래 두 사람 차림을 건너뛴다
                row["facts2"] = facts_digest(j2, (ex.get("gender2") or "") in ("M", "F"))
                # 이름표에 **생년월일·시각을 통째로** 넣는다 (2026-09-24 사장님 지시).
                # AI 가 두 사람 것을 섞어 담아도 검사로는 못 잡는다 — 손님이 자기 생일을 보면 바로 안다.
                row["who1"] = 사람표(y, m, d, hh, gender)
                row["who2"] = 사람표(y2, int(ex["month2"]), int(ex["day2"]),
                                   int(ex.get("hour2", -1)), ex.get("gender2"))
                missing = []          # 둘 다 풀 때는 빠진 것부터 청하지 않는다. 있는 걸로 먼저 풀어 준다
            except StopIteration:
                pass                                   # 같은 날 — 한 사람 기준으로 푼다
            except Exception as e:
                log_err("둘째 사주 엔진 실패(첫째만 풀이): %s" % str(e)[:120])
    elif y:
        missing.append("양력 월·일 (일주가 안 나와서 재물·배우자 자리를 못 봄)")
    # 생년 자체가 없으면 facts 없이 일반 답글 (사주 얘기 안 함)

    # 검사에 걸리면 **사유를 알려 주고 다시 쓰게 한다.** 한 번에 포기하면 멀쩡한 풀이가 버려진다
    # (2026-09-21 겪음: 줄표 하나, 물음표 하나 때문에 통째로 반려됨).
    # 마지막 턴은 **되묻지 않는다** (2026-09-25). 물어 놓고 문을 닫으면 손님이 씹힌 것이 된다
    # 인사에 받는 짧은 한마디도 되묻지 않는다 — 물으면 취조가 된다
    가볍게 = bool(row.get("가볍게"))
    need_q = (row["turn"] < LAST_TURN) and not 가볍게
    # 이미 한 안내만 골라서 막는다. 마지막 턴에는 프로필을 다시 안내해야 하니 안 막는다
    막을말 = ()
    if 가볍게:
        막을말 = PROMO_WORDS            # 인사 받는 자리에 홍보 붙이면 밉상이다
    elif row["turn"] < LAST_TURN:
        막을말 = ((리포스트말 if row.get("리포스트함") else ())
                  + (프로필말 if row.get("프로필함") else ()))
    fix, w, err = "", None, ""
    for _ in range(3):
        w = write_reply(row, facts, missing, row["turn"], fix=fix)
        if "__오류__" in w:
            # 일시적인 실패(네트워크·CLI 딸꾹질)는 그 자리에서 한 번 더 해 본다.
            # 로그인 만료처럼 손을 써야 하는 건 바로 넘긴다.
            err = w["__오류__"]
            if "로그인만료" in err:
                return "보류", conf, err, None, err
            continue
        text = tidy(w.get("reply"))
        bad = reply_ok(text, need_question=need_q, 막을말=막을말, 짧게=가볍게)
        note = "%s | %s" % (ex.get("reason", ""), w.get("note", ""))
        if not bad:
            return "답함", conf, (note + (" | 고쳐 씀" if fix else "")), text, None
        fix = bad
        if bad.startswith("금지어"):
            fix = (bad + " — **그 글자가 들어간 말을 통째로 빼고 다른 말로 바꿔 써라.** "
                   "지우기만 하지 말고 뜻이 통하게 다시 써라.")
    if w is None or "__오류__" in w:      # 세 번 다 호출 자체가 실패 → 다음 회차에 다시
        return "보류", conf, err or "작성 실패", None, err or "작성 실패"
    return "답함", conf, note, None, "답글문 " + fix + " (3번 고쳐도 안 됨)"


PII_KEEP_DAYS = 1       # 남의 생년월일·글은 이 날짜가 지나면 기록에서 지운다


def purge_pii():
    """기록 CSV 에서 **하루 지난 남의 개인정보를 지운다** (2026-09-21 사장님 지시).

    지우는 것: 상대가 쓴 글(생년월일시가 들어 있다), 우리가 보낸 답글문.
    남기는 것: 시각·상대 계정·라벨·확신도·처리 — 기준을 조정하려면 이건 있어야 한다.
    """
    # R2 에선 날짜별 파일이라 하루 지난 파일을 통째로 지운다 (답글창고.LOG_KEEP_DAYS)
    gone = STORE.오래된것_지우기()
    if gone:
        runlog("R2 에서 지난 기록 %d개 지움 (남의 생년월일 포함)" % len(gone))


def today_count():
    """오늘 실제로 올린 답글 수 (하루 상한 계산용). R2 의 오늘 기록에서 센다."""
    return sum(1 for r in STORE.기록_오늘() if r.get("처리") == "발행")


# ── 한 바퀴 ───────────────────────────────────────────────────────
def run(dry=False):
    vault = vault_open()
    tok, uid = vault.get("threads_token"), str(vault.get("threads_user_id") or "")
    if not tok:
        log_err("금고에 스레드 토큰 없음")
        return 1
    # 대기줄·상태는 R2 에서. PC 든 깃허브든 같은 것을 본다
    state = STORE.읽기("상태.json") or {"tg_offset": 0, "report_sent": "", "reports": {}}
    queue = STORE.읽기("대기.json") or []

    # 1) 사장님 텔레그램 답장
    if not dry:
        msgs, state["tg_offset"] = tg_updates(vault, state.get("tg_offset", 0))
        for rep_mid, txt in msgs:
            key = str(rep_mid)
            if key not in state.get("reports", {}):
                continue
            item, t = state["reports"][key], txt.strip()
            if re.match(r"^(무시|놔둬|패스|ㄴ|넘겨|버려)\s*$", t):
                mark_done(item["reply_id"], "", "")
                tg_send(vault, "🗑 안 답하고 넘겼어 (@%s)" % item["user"])
                del state["reports"][key]
                continue
            go = re.match(r"^(답해|ㄱㄱ|ㄱ|보내|올려|ok|오케이|ㅇㅋ)\s*$", t, re.I)
            body = tidy(item.get("draft", "") if go else t)
            if not body:
                tg_send(vault, "❌ 올릴 글이 없어. 글을 적어서 답장해줘")
                continue
            bad = reply_ok(body)
            if bad:
                tg_send(vault, "❌ 그 글은 못 올려 (%s)" % bad)
                continue
            due = now() + dt.timedelta(minutes=random.randint(DELAY_MIN, DELAY_MAX))
            queue.append({"reply_id": item["reply_id"], "user": item["user"], "text": body,
                          "due": due.strftime("%Y-%m-%d %H:%M:%S"), "by": "사장님"})
            tg_send(vault, "✅ 예약했어 (@%s, %s에 올라감)\n%s" % (item["user"], due.strftime("%H:%M"), body))
            del state["reports"][key]

    # 2) 대기줄 발행
    quota = reply_quota_left(tok, uid) if queue and not dry else None
    left, sent = [], 0
    started = time.time()
    for q in sorted(queue, key=lambda x: x["due"]):           # 오래 기다린 것부터
        if dry or q["due"] > now().strftime("%Y-%m-%d %H:%M:%S"):
            left.append(q)
            continue
        # 답글 사이 2분(publish 가 기다린다). 이 바퀴에서 기다린 게 4분을 넘으면 다음 바퀴로 넘긴다
        if time.time() - started + reply_gap_left() > PUBLISH_WAIT_MAX:
            left.append(q)
            continue
        if quota is not None and quota - sent <= META_RESERVE:
            left.append(q)                    # 메타 한도가 얼마 안 남음 → 내일로 미룬다
            if state.get("quota_alert") != now().strftime("%Y-%m-%d"):
                tg_send(vault, "🛑 스레드 답글 한도가 %d개밖에 안 남았어.\n"
                               "쇼츠 첫 답글(링크)이랑 손으로 다는 답글 몫으로 남겨 두고 멈출게.\n"
                               "대기 중인 %d건은 내일 올라가." % (quota - sent, len(queue) - sent))
                state["quota_alert"] = now().strftime("%Y-%m-%d")
            continue
        try:
            mid = publish(tok, uid, q["reply_id"], q["text"])
            mark_done(q["reply_id"], mid, q["text"])
            write_log([now().strftime("%Y-%m-%d %H:%M"), q["reply_id"], q.get("user", ""), "", "발행", "", q.get("by", ""), "발행", q["text"]])
            sent += 1
            runlog("발행 @%s ← %s" % (q.get("user"), q["text"][:60].replace("\n", " ")))
        except Exception as e:
            log_err("자동답글 발행 실패 %s: %s" % (q["reply_id"], e))
            tg_send(vault, "❌ 답글 발행 실패\n@%s\n%s" % (q.get("user"), str(e)[:300]))
    queue = left

    # 3) 새 답글
    try:
        rows = collect(tok, uid)
    except Exception as e:
        log_err("답글 수집 실패: %s" % e)
        if not dry:
            tg_send(vault, "❌ 스레드 답글 수집 실패\n%s" % str(e)[:300])
        return 1

    busy = {q["reply_id"] for q in queue} | {v["reply_id"] for v in state.get("reports", {}).values()}
    todo = [r for r in rows if r["reply"]["id"] not in busy]
    # 댓글이 몰리면 **오래 기다린 것부터**. 안 그러면 늦게 온 사람이 먼저 답을 받고
    # 먼저 쓴 사람은 계속 밀린다 (수집 순서는 글·대화 순서라 사실상 뒤죽박죽이다).
    todo.sort(key=lambda r: r["reply"].get("timestamp") or "")
    waiting = 0
    if len(todo) > MAX_PER_RUN:
        # 한 바퀴가 너무 길어지면 잠금이 '깨진 것'으로 간주돼 중복 발행이 난다 → 나눠서 한다.
        waiting = len(todo) - MAX_PER_RUN
        todo = todo[:MAX_PER_RUN]
        runlog("  댓글 몰림: %d건 더 있음. 이번엔 %d건만 하고 다음 바퀴에 이어 함" % (waiting, MAX_PER_RUN))

    auto, failed = 0, []          # failed = 기술적 실패(다음 회차 재시도)
    for r in todo:
        rid, user = r["reply"]["id"], (r["reply"].get("username") or "?")
        text = (r["reply"].get("text") or "").replace("\n", " ")[:200]
        why = prefilter(r)
        if why:
            runlog("  무시 @%s (%s)" % (user, why))
            if not dry:
                # 10번까지 주고받은 사람은 그냥 끊기면 아까우니 한 번은 알린다
                # (잘 풀리는 대화일수록 먼저 상한에 닿는다. 사장님이 손으로 이어 갈 수 있게)
                if r["used"] >= MAX_PER_PERSON and user not in state.get("capped", []):
                    tg_send(vault, "🔚 @%s 와 %d번 주고받아서 자동 답글은 여기까지야.\n\n%s\n\n%s\n\n더 이어 가려면 사장님이 직접 달아줘"
                            % (user, r["used"], text[:200], r["post"].get("permalink") or ""))
                    state.setdefault("capped", []).append(user)
                write_log([now().strftime("%Y-%m-%d %H:%M"), rid, user, text, "무시(규칙)", "", why, "무시", ""],
                          r["reply"].get("permalink") or "")
                mark_done(rid, "", "")
            continue

        label, conf, reason, reply, hold = handle(r, dry)
        # 판단 이유엔 생년월일이 들어 있다. 깃허브(공개 저장소) 실행 화면은 누구나 볼 수 있으니 거기선 안 찍는다.
        runlog("  @%s [%d턴] → %s(%d) %s" % (user, r["turn"], label, conf, reason[:70] if WHO == "PC" else "(이유는 R2 기록에)"))
        if dry:
            print("     " + (reply or "(안 올림: %s)" % hold).replace("\n", "\n     "))
            continue

        if reply:
            if today_count() + auto >= MAX_PER_DAY:
                # 조용히 넘기면 사장님이 모른다. 하루 한 번은 알린다.
                if state.get("cap_alert") != now().strftime("%Y-%m-%d"):
                    tg_send(vault, "🛑 오늘 자동 답글 %d개를 다 썼어(상한).\n남은 건 내일 이어서 올라가.\n\n"
                                   "더 올리려면 스레드자동답글.py 의 MAX_PER_DAY 를 올려줘" % MAX_PER_DAY)
                    state["cap_alert"] = now().strftime("%Y-%m-%d")
                write_log([now().strftime("%Y-%m-%d %H:%M"), rid, user, text, label, conf, "하루 상한", "내일로", reply])
                continue
            due = now() + dt.timedelta(minutes=random.randint(DELAY_MIN, DELAY_MAX))
            queue.append({"reply_id": rid, "user": user, "text": reply,
                          "due": due.strftime("%Y-%m-%d %H:%M:%S"), "by": "자동"})
            auto += 1
            write_log([now().strftime("%Y-%m-%d %H:%M"), rid, user, text, label, conf, reason, "예약 " + due.strftime("%H:%M"), reply])
        elif label == "미성년":
            # 미성년만 그대로 버린다 (만 14세 미만 개인정보보호법). 여긴 안 바뀐다
            write_log([now().strftime("%Y-%m-%d %H:%M"), rid, user, text, label, conf, reason, "무시", ""],
                      r["reply"].get("permalink") or "")
            mark_done(rid, "", "")
        elif label == "무시":
            # 2026-09-24 사장님 지시: **무시 폐지.** 버리지 않고 보류목록에 넣는다.
            # 6시간마다 도는 AI자동답변이 앞 대화를 놓고 다시 본다.
            # mark_done 은 그대로 한다 — 안 하면 본체가 5분마다 같은 댓글을 다시 판단해 토큰을 태운다.
            if not dry:
                STORE.보류_넣기(rid, {"user": user, "text": text, "reason": reason[:200],
                                      "turn": r["turn"], "때": now().strftime("%Y-%m-%d %H:%M"),
                                      "permalink": r["post"].get("permalink") or ""})
            write_log([now().strftime("%Y-%m-%d %H:%M"), rid, user, text, label, conf, reason, "보류목록", ""],
                      r["reply"].get("permalink") or "")
            mark_done(rid, "", "")
        elif label == "보류":
            # 기술적 실패(사용량 한도·시간 초과·엔진 오류)는 **판단이 아니다.**
            # 텔레그램으로 넘기면 사장님이 답할 때까지 그 댓글이 멈춰 버린다 → 다음 회차에 다시 시도한다.
            failed.append("@%s: %s" % (user, reason[:80]))
            write_log([now().strftime("%Y-%m-%d %H:%M"), rid, user, text, label, conf, reason, "재시도", ""])
        else:
            icon = {"동업자": "🕵️", "악의": "🚫"}.get(label, "⚠️")
            body = "%s 보류 — %s (확신 %d)\n\n내 글: %s\n@%s: %s\n\n이유: %s" % (
                icon, hold, conf, (r["post"].get("text") or "").replace("\n", " ")[:60], user, text, reason[:200])
            if r["post"].get("permalink"):
                body += "\n" + r["post"]["permalink"]
            body += "\n\n→ 답하려면 이 메시지에 글을 적어 답장 (안 할 거면 '무시')"
            mid = tg_send(vault, body)
            if mid:
                state.setdefault("reports", {})[str(mid)] = {"reply_id": rid, "user": user, "draft": "",
                                                             "link": r["reply"].get("permalink") or ""}
            write_log([now().strftime("%Y-%m-%d %H:%M"), rid, user, text, label, conf, "[%s] %s" % (hold, reason), "보고", ""],
                      r["reply"].get("permalink") or "")

    if not dry:
        STORE.쓰기("대기.json", queue)
        # 기술적 실패는 한 바퀴에 한 통만, 그것도 한 시간에 한 번까지만 알린다 (재시도되므로 급하지 않다)
        if failed and state.get("fail_alert", "") != now().strftime("%Y-%m-%d %H"):
            if any("로그인만료" in f for f in failed):
                tg_send(vault, "🔑 클로드 로그인이 풀렸어. 답글이 안 나가고 있어.\n\n"
                               "PC 터미널에서 claude 실행하고 /login 한 번 해줘.\n"
                               "그때까지 %d건이 밀려 있어 (없어지진 않고 계속 재시도해)" % len(failed))
            else:
                tg_send(vault, "⏳ %d건 처리 못 해서 다음 회차에 다시 시도해\n\n%s"
                        % (len(failed), "\n".join(failed[:5])))
            state["fail_alert"] = now().strftime("%Y-%m-%d %H")
        # 6시간마다 한눈 요약 (00·06·12·18시). 그 시각이 지난 첫 바퀴에 한 번만.
        slot = "%s-%02d" % (now().strftime("%Y-%m-%d"), now().hour // REPORT_EVERY_HOURS * REPORT_EVERY_HOURS)
        if state.get("report_sent") != slot:
            tg_send(vault, report_text(state, tok, uid), preview=False)
            state["report_sent"] = slot
            state["report_at"] = now().strftime("%Y-%m-%d %H:%M")     # 다음 요약은 이 뒤의 무시·보류만 링크로
            if now().hour < REPORT_EVERY_HOURS:      # 자정 회차에 하루치 정리
                state["capped"] = []                 # 상한 알림은 날마다 새로
                purge_pii()                          # 하루 지난 남의 생년월일 지우기
    state["waiting"] = waiting            # 요약에 보여 주려고 남긴다
    if not dry:
        STORE.쓰기("상태.json", state)
        if WHO == "PC":
            STORE.심장박동_찍기("PC")     # "나 살아있다" — 깃허브는 이걸 보고 물러난다
    runlog("새 답글 %d · 예약 %d · 발행 %d · 대기 %d%s%s" % (
        len(todo), auto, sent, len(queue),
        (" · 재시도 %d" % len(failed)) if failed else "",
        (" · 밀린 것 %d" % waiting) if waiting else ""))
    return 0




def insights(tok, uid):
    """계정 지표 + 최근 글별 성적. 실패해도 하루 요약은 나가야 하니 예외를 삼킨다(값만 None)."""
    acc, posts = {}, []
    try:
        for d in th_get(tok, uid + "/threads_insights",
                        metric="views,likes,replies,reposts,quotes,followers_count").get("data", []):
            tv = d.get("total_value") or {}
            acc[d["name"]] = tv.get("value") if tv else (d.get("values") or [{}])[-1].get("value")
    except Exception as e:
        log_err("계정 인사이트 실패: %s" % str(e)[:120])
    try:
        mine = [p for p in th_get_all(tok, uid + "/threads", fields="id,text,timestamp,is_reply", limit=100, max_pages=1)
                if not p.get("is_reply") and post_age_days(p) <= 7]
        for p in mine:
            try:
                m = {d["name"]: (d.get("values") or [{}])[0].get("value")
                     for d in th_get(tok, p["id"] + "/insights", metric="views,likes,replies,reposts").get("data", [])}
            except Exception:
                continue
            posts.append({"id": p["id"], "at": (p.get("timestamp") or "")[:16].replace("T", " "),
                          "훅": (p.get("text") or "").splitlines()[0][:40], **m})
    except Exception as e:
        log_err("글 인사이트 실패: %s" % str(e)[:120])
    return acc, posts


def save_score(acc, posts):
    """오늘 성적을 R2 에 쌓는다. 일주일쯤 모이면 잘 되는 띠·시간대·훅이 보인다."""
    STORE.성적_추가([{"잰시각": now().strftime("%Y-%m-%d %H:%M"), "글id": p["id"], "올린시각": p["at"], "훅": p["훅"],
                    "조회": p.get("views"), "좋아요": p.get("likes"), "답글": p.get("replies"),
                    "리포스트": p.get("reposts"), "그날팔로워": acc.get("followers_count")} for p in posts])


def posts_today():
    """오늘 올라간 스레드 **글**(답글 아님) 수. 예약표에서 센다."""
    key = now().strftime("%Y-%m-%d")
    try:
        import 쇼츠창고
        q = 쇼츠창고.열기().예약표읽기()        # R2 창고 shorts/ (2026-09-25). 저장소엔 이제 예약표가 없다
    except Exception as e:
        print("예약표를 못 읽음(%s) → 오늘 글 수는 0으로" % type(e).__name__)
        q = []
    out = {}
    for x in q:
        if (x.get("publish_at") or "").startswith(key) and x.get("threads_text") and x.get("threads_status") == "게시":
            k = x.get("threads_kind") or "띠"
            out[k] = out.get(k, 0) + 1
    return out


def report_text(state, tok=None, uid=None):
    """6시간마다 보내는 한눈 요약 (2026-09-21 사장님 지시)."""
    n = {"발행": 0, "무시": 0, "보고": 0, "예약": 0, "재시도": 0}
    for r in STORE.기록_오늘():
        act = r.get("처리", "")
        if act.startswith("예약"):
            n["예약"] += 1
        elif act == "보류목록":        # 분류기가 '무시'라 한 것. 2026-09-24 부터 버리지 않고 보류목록에 쌓는다
            n["보고"] += 1
        elif act in n:
            n[act] += 1

    ps = posts_today()
    out = ["📊 %s %02d시" % (now().strftime("%m/%d"), now().hour),
           "",
           "── 오늘 (자정부터)",
           "글 %d개%s" % (sum(ps.values()),
                         (" (" + " · ".join("%s %d" % (k, v) for k, v in ps.items()) + ")") if ps else ""),
           "답글 %d개" % n["발행"],
           "무시 %d · 보류 %d%s" % (n["무시"], n["보고"], (" · 재시도 %d" % n["재시도"]) if n["재시도"] else "")]

    q = STORE.읽기("대기.json") or []
    if q or state.get("reports") or state.get("waiting"):
        out += ["", "── 지금"]
        if q:
            out.append("올라갈 차례 %d건 (%s)" % (len(q), ", ".join(x["due"][11:16] for x in sorted(q, key=lambda y: y["due"])[:4])))
        if state.get("waiting"):
            out.append("아직 못 본 댓글 %d건 (다음 바퀴부터 차례로)" % state["waiting"])
        if state.get("reports"):
            out.append("내 답장 기다리는 것 %d건" % len(state["reports"]))
            for item in list(state["reports"].values())[:LINK_MAX]:
                if not item.get("link") and tok:
                    try:                # 한 번 받은 링크는 state 에 남겨 다음 요약 땐 안 묻는다
                        item["link"] = th_get(tok, item["reply_id"], fields="permalink").get("permalink") or ""
                    except Exception:
                        pass
                out.append("@%s  %s" % (item.get("user") or "?", item.get("link") or "(링크 못 받음)"))
            if len(state["reports"]) > LINK_MAX:
                out.append("… 외 %d건" % (len(state["reports"]) - LINK_MAX))
        left = MAX_PER_DAY - n["발행"]
        if left <= 5:
            out.append("⚠️ 오늘 올릴 수 있는 답글 %d개 남음 (상한 %d)" % (max(left, 0), MAX_PER_DAY))

    if tok:
        acc, posts = insights(tok, uid)
        if acc:
            prev = state.get("last_followers")
            d = ("  (%+d)" % (acc["followers_count"] - prev)) if prev is not None and acc.get("followers_count") is not None else ""
            out += ["", "── 계정",
                    "팔로워 %s%s" % (acc.get("followers_count", "?"), d),
                    "조회 %s · 좋아요 %s · 답글 %s · 리포스트 %s"
                    % (acc.get("views", "?"), acc.get("likes", "?"), acc.get("replies", "?"), acc.get("reposts", "?"))]
            if acc.get("followers_count") is not None:
                state["last_followers"] = acc["followers_count"]
        if posts:
            save_score(acc, posts)
            top = sorted(posts, key=lambda p: -(p.get("replies") or 0))[:3]
            out += ["", "── 일주일 중 답글 많은 글"]
            out += ["%s 답글%s 조회%s  %s" % (p["at"][5:], p.get("replies", "?"), p.get("views", "?"), p["훅"][:22])
                    for p in top]
    out += 걸린것_링크(state, tok)
    return "\n".join(out)


LINK_MAX = 10                   # 요약에 무시·보류 링크를 각각 이만큼까지만 (텔레그램 한 통 4,000자)


def 걸린것_링크(state, tok=None):
    """지난 요약 뒤에 무시·보류된 댓글을 링크로 (2026-09-25 사장님 지시).
    00시 요약은 어제 18시 뒤 것도 봐야 하니 어제 기록까지 읽는다 (어제 파일은 요약 **뒤에** 지운다)."""
    since = state.get("report_at") or (now() - dt.timedelta(hours=REPORT_EVERY_HOURS)).strftime("%Y-%m-%d %H:%M")
    rows = []
    for day in sorted({since[:10], now().strftime("%Y-%m-%d")}):
        rows += STORE.읽기("기록/%s.json" % day) or []
    rows = [r for r in rows if (r.get("시각") or "") >= since]
    out = []
    for name, acts in (("무시", ("무시",)), ("보류", ("보고", "보류목록"))):
        got = sorted([r for r in rows if r.get("처리") in acts], key=lambda r: r.get("시각") or "", reverse=True)
        if not got:
            continue
        out += ["", "── %s %d건 (지난 요약 뒤)" % (name, len(got))]
        for r in got[:LINK_MAX]:
            link = r.get("링크") or ""
            if not link and tok and r.get("답글ID"):
                try:                    # 링크를 안 적던 때의 기록 → 스레드에 물어본다
                    link = th_get(tok, r["답글ID"], fields="permalink").get("permalink") or ""
                except Exception:
                    link = ""
            why = re.sub(r"^\[[^\]]*\]\s*", "", r.get("이유") or "")[:30]
            out.append("@%s 「%s」 %s\n%s" % (r.get("상대") or "?", (r.get("상대글") or "")[:20], why,
                                           link or "(링크 못 받음)"))
        if len(got) > LINK_MAX:
            out.append("… 외 %d건" % (len(got) - LINK_MAX))
    return out


def check():
    queue, state = STORE.읽기("대기.json") or [], STORE.읽기("상태.json") or {}
    hb = STORE.심장박동_지난분()
    print("PC 심장박동: %s" % ("%.0f분 전" % hb if hb < 10 ** 5 else "없음"))
    print("대기줄 %d건" % len(queue))
    for q in queue:
        print("  %s  @%s  %s" % (q["due"], q.get("user"), q["text"][:50].replace("\n", " ")))
    print("미결정 보류 %d건 / 오늘 발행 %d (상한 %d)" % (len(state.get("reports", {})), today_count(), MAX_PER_DAY))


def test_one(text):
    """댓글 한 줄로 추출→엔진→풀이만 돌려 본다. 발행 안 함."""
    row = {"post": {"text": "(시험)"}, "reply": {"text": text, "username": "테스트", "id": "0"},
           "used": 0, "turn": 1, "chain": ["@테스트: " + text]}
    label, conf, reason, reply, hold = handle(row, dry=True)
    print("라벨 %s(%d) — %s" % (label, conf, reason))
    print("-" * 50)
    print(reply or "(안 올림: %s)" % hold)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--test", metavar="댓글")
    a = ap.parse_args()
    if a.test:
        test_one(a.test); return 0        # 창고 없이 됨 (판단·풀이만)

    # R2 창고. 못 열면 **아무것도 안 한다** — 로컬로 대충 돌리면 PC·깃허브가 어긋나 중복이 난다.
    global STORE
    try:
        STORE = 답글창고.창고()
        STORE.읽기("상태.json")          # 실제로 닿는지 한 번 확인
    except Exception as e:
        log_err("R2 창고를 못 열어 이번 바퀴 건너뜀: %s" % str(e)[:120])
        return 1
    if a.check:
        check(); return 0
    if a.dry_run:
        return run(dry=True)              # 아무것도 안 올리니 잠금 필요 없음

    # 깃허브는 **PC 가 죽었을 때만** 나선다. PC 가 20분 안에 살아 있었으면 그냥 물러난다.
    if WHO == "깃허브":
        quiet = STORE.심장박동_지난분()
        if quiet < HEARTBEAT_MAX_MIN:
            runlog("PC 가 %.0f분 전에 살아 있었음 → 깃허브는 물러남" % quiet)
            return 0
        runlog("PC 가 %s → 깃허브가 대신 나섬" % ("한 번도 안 보임" if quiet > 10 ** 5 else "%.0f분째 조용함" % quiet))

    # 겹쳐 돌면 같은 답글이 두 번 올라간다 → 한 번에 하나만 (잠금도 R2 라 PC·깃허브가 같이 본다)
    got, held = STORE.잠금_잡기(WHO, stale_min=LOCK_STALE_MIN)
    if not got:
        runlog("이미 도는 중(%s, %s 시작) → 이번 바퀴 건너뜀" % ((held or {}).get("who"), (held or {}).get("started")))
        return 0
    try:
        return run(dry=False)
    finally:
        STORE.잠금_풀기()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        log_err("스레드자동답글 실패: %s" % e)
        sys.exit(1)
