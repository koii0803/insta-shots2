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
확신 = 70              # 이 아래면 안 단다. 애매하면 조용한 쪽이 낫다

# 한때 본체 확신 문턱(85)을 낮춰 봤는데, 그건 원인이 아니었다 (2026-09-24).
# 진짜 원인은 대화 줄기가 앞에서 잘려 생년월일이 사라진 것이었고 build_chain 을 고쳤다.
# 문턱은 본체 것 그대로 쓴다 — 낮추면 사주 없이 지어낸 답이 나갈 수 있다.
한바퀴상한 = 12        # 한 번에 이만큼만. 우르르 안 나가게 (2026-09-24 무시 폐지로 보류가 늘어 5 -> 12)


# ── AI 에게 묻는 딱 두 갈래 ────────────────────────────────────────
# ⚠️ 칸 이름은 **영문만 된다.** 한글로 적으면 서버가 통째로 거절한다 (2026-09-24 실측):
#    400 tools.0.custom.input_schema.properties:
#        Property keys should match pattern ^[a-zA-Z0-9_.-]{1,64}$
#    그러면 stderr 는 비고 stdout 에만 까닭이 실려서, 본체 기준으로는
#    "claude 실행 실패: " 하고 이유가 빈 채로 남는다. 한참 헤맸다.
SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["continue", "done"]},
        "conf": {"type": "integer"},
        "why": {"type": "string"},
    },
    "required": ["verdict", "conf", "why"],
}

SYS = "너는 대화가 이어지는 중인지 끝났는지만 가른다. 지시한 JSON 하나만 출력한다."

틀 = """스레드 계정 @paljaoppa(팔자오빠) 사주 상담 대화다.
마지막 댓글이 너무 짧아서 기계가 못 읽는다. 앞 대화를 보고 갈라라.

[지금까지 오간 말]
%s

[방금 달린 짧은 댓글]
@%s: %s

**이어짐** — 대화를 이어 가야 한다
  · **사주 재료를 새로 줬다. 이건 무조건 이어짐이다.**
    성별("여자" "남자" "여자야") · 태어난 시간("새벽 3시" "시간 모름")
    · 띠("돼지띠" "🐷띠") · 생년월일 · 양음력
    앞 풀이에 이미 그 말이 나왔더라도 **중복이 아니다.**
    성별을 모르면 대운을 순행·역행으로 못 갈라서 아예 빼고 풀었기 때문에,
    이제야 풀 수 있게 된 것이다. 시간·띠도 마찬가지로 새로 볼 자리가 생긴다.
  · 내가 앞에서 물은 것에 이 사람이 답했다 (예: "남자야 여자야" -> "여자")
  · 짧지만 새로 묻는 것이 있다 (예: "언제?" "왜?")
  · 앞 풀이에 대한 반응이라 받아 줄 말이 있다 (예: "맞아" "아닌데" "없지ㅋ")

**끝남** — 답하지 않는다
  · 고맙다는 인사, 웃음, 감탄사뿐이다 (예: "감사합니다" "ㅎㅎ" "오")
  · 앞에서 대화가 마무리됐고 덧붙일 것이 없다
    (단, **사주 재료를 준 것은 여기 해당 안 된다.** 위를 먼저 본다)
  · 무슨 말인지 앞 대화를 봐도 모르겠다

**애매하면 끝남으로 둔다.** 잘못 달면 이상한 놈이 되고, 안 달면 그냥 조용한 것뿐이다.

verdict 는 이어짐이면 continue, 끝남이면 done.
conf 는 0~100. why 는 한 줄로 까닭."""


def 갈라보기(row):
    """(판단, 확신, 까닭). 오류면 ('끝남', 0, 이유) — 막히면 안 다는 쪽으로."""
    out = 봇.claude(
        틀 % (chr(10).join(row["chain"]) or "(없음)",
              row["reply"].get("username") or "?",
              (row["reply"].get("text") or "").strip()),
        SCHEMA, 봇.MODEL_EXTRACT, SYS, timeout=120, 부르는곳="AI자동답변")
    if "__오류__" in out:
        return "끝남", 0, out["__오류__"]
    판단 = "이어짐" if (out.get("verdict") or "done") == "continue" else "끝남"
    return 판단, int(out.get("conf") or 0), (out.get("why") or "")[:120]


# ── 한 바퀴 ────────────────────────────────────────────────────────
def 주울것(tok, uid, 본것):
    """본체가 못 정하고 넘긴 것만 골라 온다. 두 갈래다.

    1) **짧아서** 본체가 AI 를 부르지도 못한 것 (MIN_LEN 이하)
    2) **보류목록** — 본체 분류기가 "못 정하겠다" 한 것
       (2026-09-24 사장님 지시로 '무시' 라벨을 없앴다. 전에는 그냥 버렸다)

    긴 것 중에 본체가 답한 것은 여기 안 온다. 본체 몫은 손 안 댄다.
    """
    봇.load_done = lambda: 본것          # 본체 목록 말고 내 목록으로 본다
    보류 = 봇.STORE.보류_목록()
    골라진것, 걸린보류 = [], []
    for r in 봇.collect(tok, uid, deep=True):
        rid = r["reply"]["id"]
        까닭 = 봇.prefilter(r)
        if rid in 보류:
            골라진것.append(r); 걸린보류.append(rid); continue
        if 까닭 and 까닭.startswith("너무 짧음"):
            골라진것.append(r)
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
        if not 글:
            봇.runlog("     답글 못 만듦: %s (%s %d)" % (보류 or 라벨, 라벨, c2))
            continue                       # 본것에 안 넣는다 — 다음 바퀴에 다시 해 본다

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
