# -*- coding: utf-8 -*-
"""AI 자동답변 — 짧아서 버려진 댓글을 AI 가 다시 보고 답한다 (2026-09-24 사장님 지시).

    6시간마다 돈다. 이름은 사장님이 정했다.

왜 만들었나
    본체(스레드자동답글.py)는 MIN_LEN=3 이하를 **AI 를 부르기도 전에** 버린다.
    그런데 본체는 매 답글을 질문으로 끝낸다("마지막은 질문으로 끝낸다").
    그래서 봇이 "남자야 여자야" 물어 놓고, 손님이 "여자" 라고 답하면
    **자기가 물어 놓고 그 대답을 버린다.**

    2026-09-21~24 사흘 동안 무시된 댓글 7건이 전부 이것이었다.
        @eunwoo.fit 2자 · @puni3836 2자 · @wonyoung____ 3자
        @coco_eunstar_... 3자 · @ggayoungee 2자 · @kk_yn 2자 · @sunho.baeg 1자
    이모지·링크·상한으로 걸린 건 0건이다.

    "여자" 두 글자가 대답인지 헛소리인지는 **앞 대화를 봐야** 안다.
    파이썬은 그걸 못 한다. 그래서 AI 한테 물어본다.

무엇을 하나
    1. 본체와 똑같이 긁는다
    2. **짧아서 버려질 것만** 고른다 (긴 것은 본체 몫, 손 안 댄다)
    3. AI 한테 딱 두 갈래만 묻는다 — 끝난 얘기냐, 이어지는 얘기냐
    4. 이어지는 것만 본체의 handle() 로 답글을 만들어 올린다

본체를 한 글자도 안 고친다
    본체는 이 댓글들을 이미 '답한 것'으로 찍어 버렸다. 그래서 다시 안 집는다.
    둘이 같은 댓글을 집을 일이 없다. 그래도 **같은 잠금**을 잡아서 동시에 안 돈다.

2026-09-27 바뀜 (사장님: "파이썬이 무시한 댓글은 앞단을 같이 AI 한테 토스")
    짧은 댓글은 **본체가 그 자리(5분 바퀴)에서** 앞단(내 글 + 오간 말)을 붙여 AI 에게 묻는다
    (스레드자동답글.짧은댓글판단). 여기서 6시간씩 기다리게 할 까닭이 없어졌다.
    이제 여기는 **보류목록**(본체 분류기가 못 정한 것)만 본다. 판단은 본체 것을 같이 쓴다.

    python AI자동답변6시간.py             # 한 바퀴
    python AI자동답변6시간.py --dry-run    # 판단·초안만. 안 올림
    python AI자동답변6시간.py --check      # 지금 뭐가 걸려 있나만
"""
import os
import re
import sys
import json
import random
import argparse
import datetime as dt
from pathlib import Path

HERE = Path(__file__).resolve().parent            # 쇼츠저장소/작업
# 순서가 중요하다. 유튜브업로더에도 **같은 이름의 껍데기**(스레드자동답글.py)가 있어서
# 그쪽이 앞에 오면 껍데기가 자기를 무한히 다시 부른다(RecursionError, 2026-09-24 겪음).
sys.path.insert(0, str(HERE.parent.parent))       # 유튜브업로더 (config.py 가 여기)
sys.path.insert(0, str(HERE))                     # 작업 — 진짜 기계가 여기. 반드시 앞에

import 답글창고
import 스레드자동답글 as 봇

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 이 프로그램만 쓰는 창고 자리. 본체 것(답한것.json·대기.json)은 건드리지 않는다
내가본것_이름 = "AI자동답변_본것.json"
옛이름 = "짧은답글_본것.json"        # 2026-09-24 이름 바꾸기 전 것. 한 번은 이어받는다

# 한때 본체 확신 문턱(85)을 낮춰 봤는데, 그건 원인이 아니었다 (2026-09-24).
# 진짜 원인은 대화 줄기가 앞에서 잘려 생년월일이 사라진 것이었고 build_chain 을 고쳤다.
# 문턱은 본체 것 그대로 쓴다 — 낮추면 사주 없이 지어낸 답이 나갈 수 있다.
한바퀴상한 = 12        # 한 번에 이만큼만. 우르르 안 나가게 (2026-09-24 무시 폐지로 보류가 늘어 5 -> 12)


# ── AI 에게 묻는 딱 두 갈래 — 본체 것을 같이 쓴다 (2026-09-27, 틀은 스레드자동답글.짧은판단_틀) ──
확신 = 봇.짧은판단확신


def 갈라보기(row):
    """(판단, 확신, 까닭). 오류면 ('끝남', 0, 이유) — 막히면 안 다는 쪽으로."""
    return 봇.짧은댓글판단(row, 부르는곳="AI자동답변")


# ── 한 바퀴 ────────────────────────────────────────────────────────
def 주울것(tok, uid, 본것):
    """본체가 못 정하고 넘긴 것만 골라 온다.

    **보류목록** — 본체 분류기가 "못 정하겠다" 한 것
       (2026-09-24 사장님 지시로 '무시' 라벨을 없앴다. 전에는 그냥 버렸다)
    (짧은 댓글은 2026-09-27 부터 본체가 그 자리에서 AI 로 가른다. 여기 안 온다)

    긴 것 중에 본체가 답한 것은 여기 안 온다. 본체 몫은 손 안 댄다.
    """
    봇.load_done = lambda: 본것          # 본체 목록 말고 내 목록으로 본다
    보류 = 봇.STORE.보류_목록()
    손대지마 = 봇.STORE.손대지마_목록()      # 사장님이 직접 챙기는 사람 (2026-09-25)
    # 본체 대기줄에 답이 걸려 있는 사람도 prefilter 가 알게 (딴 글 대기 중이면 무시)
    봇.대기중손님.clear()
    for q in 봇.STORE.읽기("대기.json") or []:
        if q.get("user"):
            봇.대기중손님.setdefault(q["user"], set()).add(q.get("post") or "")
    골라진것, 걸린보류 = [], []
    for r in 봇.collect(tok, uid, deep=True):
        rid = r["reply"]["id"]
        if (r["reply"].get("username") or "") in 손대지마:
            걸린보류.append(rid)             # 보류목록에 있었으면 거기서도 빠지게
            continue
        까닭 = 봇.prefilter(r)
        # 글마다 다는 사람 (2026-09-27 사장님: 무시). 보류목록에 있던 것이라도 딴 글에서 이미 봐줬으면 안 단다.
        #   전에는 보류에 있던 A 글 댓글을, B 글에서 풀어 준 뒤에 여기서 또 풀어 줄 수 있었다
        #   걸린보류에 안 넣으니 아래 '사라짐' 으로 보류목록에서도 빠진다 (일주일 뒤 뒤늦게 답하는 일 없게)
        if 까닭 and ("이미 봐줌" in 까닭 or "딴 글에서" in 까닭):
            continue
        if rid in 보류:
            골라진것.append(r); 걸린보류.append(rid); continue
        # 짧은 댓글은 본체가 5분 바퀴에서 이미 AI 로 갈랐다 (2026-09-27). 여기서 또 안 본다
    # 보류목록에 있는데 대화에서 사라진 것(손님이 지움 등)은 목록에서 뺀다
    사라짐 = [k for k in 보류 if k not in 걸린보류]
    if 사라짐:
        봇.STORE.보류_빼기(사라짐)
        봇.runlog("AI자동답변: 보류목록에서 사라진 것 %d건 치움" % len(사라짐))
    return 골라진것


def 한바퀴(dry=False, 보기만=False):
    금고 = 봇.vault_open()
    tok, uid = 금고.get("threads_token"), str(금고.get("threads_user_id") or "")
    if not tok:
        봇.log_err("금고에 스레드 토큰 없음")
        return 1

    본것 = set(봇.STORE.읽기(내가본것_이름) or 봇.STORE.읽기(옛이름) or [])
    줄 = 주울것(tok, uid, 본것)
    if not 줄:
        봇.runlog("AI자동답변: 넘어온 것 없음")
        return 0

    봇.runlog("AI자동답변: 본체가 넘긴 것 %d건 (짧은 것 + 보류목록)" % len(줄))
    if 보기만:
        for r in 줄:
            print("@%s [%d턴] %r" % (r["reply"].get("username"), r["turn"],
                                     (r["reply"].get("text") or "").strip()))
        return 0

    올림 = 0
    for r in 줄[:한바퀴상한]:
        rid = r["reply"]["id"]
        누구 = r["reply"].get("username") or "?"
        말 = (r["reply"].get("text") or "").strip()
        판단, conf, 까닭 = 갈라보기(r)
        봇.runlog("  @%s [%d턴] %r -> %s(%d) %s" % (누구, r["turn"], 말, 판단, conf, 까닭[:60]))

        if 판단 != "이어짐" or conf < 확신:
            if not dry:
                본것.add(rid)
                봇.STORE.보류_빼기([rid])      # 끝난 얘기로 봤으니 목록에서 뺀다
            continue

        라벨, c2, 이유, 글, 보류 = 봇.handle(r, dry)
        if 라벨 in ("함정", "악의"):        # 2026-09-26 절대 무시. 다시 보지도 않는다(토큰 아낌)
            봇.runlog("     무시: %s" % 이유[:60])
            if not dry:
                본것.add(rid)
                봇.STORE.보류_빼기([rid])
            continue
        if not 글:
            # 다음 바퀴에 다시 해 보되 **두 번까지만** (2026-09-27 사장님: 같은 걸 계속 집어 AI 가 보면 토큰 샌다).
            #   전엔 본것에 안 넣고 끝이라, 답글을 못 만드는 댓글은 6시간마다 판단·작성을 영원히 되풀이했다
            if not dry:
                목록 = 봇.STORE.보류_목록()
                시도 = int((목록.get(rid) or {}).get("시도") or 0) + 1
                if 시도 >= 2:
                    본것.add(rid)
                    봇.STORE.보류_빼기([rid])
                    봇.runlog("     답글 못 만듦 %d번째 → 그만 봄: %s (%s %d)" % (시도, 보류 or 라벨, 라벨, c2))
                    continue
                if rid in 목록:
                    봇.STORE.보류_넣기(rid, dict(목록[rid], 시도=시도))
            봇.runlog("     답글 못 만듦: %s (%s %d) — 다음 바퀴에 한 번 더" % (보류 or 라벨, 라벨, c2))
            continue

        글 = 봇.tidy(글)
        나쁨 = 봇.reply_ok(글)
        if 나쁨:
            봇.runlog("     못 올림: %s" % 나쁨)
            continue

        if dry:
            print("     " + 글.replace(chr(10), chr(10) + "     "))
            continue

        try:
            내글 = 봇.publish(tok, uid, rid, 글)
        except Exception as e:
            봇.log_err("AI자동답변 발행 실패 @%s: %s" % (누구, str(e)[:120]))
            continue
        본것.add(rid)
        봇.STORE.보류_빼기([rid])
        봇.STORE.쓰기(내가본것_이름, sorted(본것))   # **올리자마자** 적는다.
        # 끝에 몰아서 적으면 중간에 죽었을 때 올린 것이 안 적혀 다음 바퀴에 또 올라간다
        봇.mark_done(rid, 내글, 글)
        try:
            봇.STORE.푼사람_적기(누구, 봇.now().strftime("%Y-%m-%d"))   # 본체처럼 — 딴 글에 또 오면 7일 무시
        except Exception:
            pass
        봇.write_log([봇.now().strftime("%Y-%m-%d %H:%M"), rid, 누구, 말,
                      "AI자동답변", str(conf), 까닭, "발행", 글])
        봇.runlog("     올림 @%s <- %s" % (누구, 글.replace(chr(10), " ")[:60]))
        올림 += 1

    if not dry:
        봇.STORE.쓰기(내가본것_이름, sorted(본것))
    봇.runlog("AI자동답변: 올림 %d건" % 올림)
    return 0


def main():
    ap = argparse.ArgumentParser(description="짧아서 버려진 댓글 줍기")
    ap.add_argument("--dry-run", action="store_true", help="판단·초안만. 안 올림")
    ap.add_argument("--check", action="store_true", help="지금 뭐가 걸려 있나만")
    a = ap.parse_args()

    try:
        봇.STORE = 답글창고.창고()
        봇.STORE.읽기("상태.json")
    except Exception as e:
        봇.log_err("AI자동답변: R2 창고를 못 열어 건너뜀: %s" % str(e)[:120])
        return 1

    if a.check:
        return 한바퀴(dry=True, 보기만=True)
    if a.dry_run:
        return 한바퀴(dry=True)

    # 본체와 **같은 잠금**. 겹쳐 돌면 같은 댓글에 답이 두 번 나간다
    잡음, 쥔것 = 봇.STORE.잠금_잡기("AI자동답변", stale_min=봇.LOCK_STALE_MIN)
    if not 잡음:
        봇.runlog("AI자동답변: 본체가 도는 중(%s) -> 건너뜀" % (쥔것 or {}).get("who"))
        return 0
    try:
        return 한바퀴(dry=False)
    finally:
        봇.STORE.잠금_풀기()


if __name__ == "__main__":
    sys.exit(main())
