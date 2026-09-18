# -*- coding: utf-8 -*-
"""깃허브 액션이 3시간마다 돌리는 스레드 답글 알림. 사용자가 직접 만질 일 없음.

하는 일:
  0) 금고(토큰.enc)를 Secrets 의 IG_ACCESS_TOKEN 으로 열어 스레드 토큰 + 카카오 refresh_token 을 꺼낸다.
  1) 내 최근 글 15개 → 답글 → 내가 아직 답 안 단 것 (내 답글이 달린 것·이미 알린 것 제외)
  2) 새 답글이 있으면 카카오톡 "나에게 보내기"로 [내 글 / 상대 글 / AI 답 초안 / 답글ID] 묶어서 한 통
  3) 알린 답글 ID 는 답글알림기록.json 에 남겨 커밋 (다시 안 보냄)
카카오 access_token 은 매번 refresh_token 으로 새로 받는다(6시간짜리). refresh_token 자체 연장은 token-refresh 가 매주.
답글 다는 일은 여기서 안 한다 — 사장님이 카톡 보고 정하면 PC 에서 python 스레드답글찾기.py --reply.
로컬 시험: python 작업/답글알림.py --dry-run (카톡 안 보냄, 기록 안 남김)
"""
import os
import re
import sys
import json
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEEN = ROOT / "답글알림기록.json"
LOG_ERR = ROOT / "오류기록.txt"
VAULT_KEY = os.environ.get("IG_ACCESS_TOKEN", "").strip()
DRY = "--dry-run" in sys.argv
THREADS = "https://graph.threads.net/v1.0/"
KAKAO_REST_KEY = "5ef3d1fd0874a38dc6b62453503218a0"
ME = "paljaoppa"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def http(method, url, data=None, headers=None):
    body = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            return e.code, {}


def th_get(tok, path, **params):
    params["access_token"] = tok
    st, j = http("GET", THREADS + path + "?" + urllib.parse.urlencode(params))
    if st != 200:
        raise RuntimeError("스레드 %s %s: %s" % (path, st, (j.get("error") or {}).get("message")))
    return j


def kakao_access(refresh, secret):
    st, j = http("POST", "https://kauth.kakao.com/oauth/token", {
        "grant_type": "refresh_token", "client_id": KAKAO_REST_KEY, "client_secret": secret, "refresh_token": refresh})
    if st != 200 or "access_token" not in j:
        raise RuntimeError("카카오 토큰 %s: %s %s" % (st, j.get("error"), j.get("error_description")))
    return j["access_token"], j.get("refresh_token")     # 만료 30일 안이면 새 refresh_token 도 온다


def kakao_memo(access, text, link):
    tpl = {"object_type": "text", "text": text[:2000], "link": {"web_url": link, "mobile_web_url": link}}
    st, j = http("POST", "https://kapi.kakao.com/v2/api/talk/memo/default/send",
                 {"template_object": json.dumps(tpl, ensure_ascii=False)}, {"Authorization": "Bearer " + access})
    if st != 200:
        raise RuntimeError("카톡 보내기 %s: %s" % (st, j))


def draft(text):
    """답 초안. PC 스레드답글찾기.reply_draft() 와 같은 규칙."""
    t = text or ""
    if re.search(r"(19|20)\d{2}", t) or "년생" in t or "생년월일" in t:
        return "고마워. 근데 나 봐주는 사람 아니야ㅋㅋ 표만 뽑아주는 데야. 프로필 링크에서 네 년생 넣으면 30초에 나와"
    if any(w in t for w in ("별명", "가입", "했어", "했음", "넣었")):
        return "확인했어. 00시에 넣어 줌. 고마워"
    if any(w in t for w in ("사기", "AI", "GPT", "봇", "광고")):
        return "그런가? 알려줘서 고마워. 나 사람이 봐주는 것도 AI가 지어내는 것도 아니고 그냥 만세력 표 뽑아주는 거야"
    if "?" in t or "왜" in t or "어떻게" in t:
        return "좋은 질문. 나도 정확히는 몰라서 찾아보고 답할게"
    return "고마워. 읽었어"


def main():
    if not VAULT_KEY:
        print("IG_ACCESS_TOKEN 없음"); return 1
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import 금고
    v = 금고.load(VAULT_KEY)
    tok, uid = v.get("threads_token"), str(v.get("threads_user_id") or "")
    if not tok:
        print("스레드 토큰 없음"); return 1
    seen = set(json.loads(SEEN.read_text(encoding="utf-8"))) if SEEN.exists() else set()

    posts = [p for p in th_get(tok, uid + "/threads", fields="id,text,permalink,is_reply", limit=15).get("data", []) if not p.get("is_reply")]
    new = []
    for p in posts:
        reps = th_get(tok, p["id"] + "/replies", fields="id,text,username,timestamp,has_replies", reverse="false").get("data", [])
        for r in reps:
            if r.get("username") == ME or r["id"] in seen:
                continue
            if r.get("has_replies") and any(x.get("username") == ME for x in th_get(tok, r["id"] + "/replies", fields="id,username").get("data", [])):
                seen.add(r["id"]); continue
            new.append((p, r))
    if not new:
        print("새 답글 없음"); return 0

    lines = ["팔자오빠 답글 %d개" % len(new), ""]
    for i, (p, r) in enumerate(new, 1):
        lines += ["[%d] 내 글: %s" % (i, (p.get("text") or "").replace("\n", " ")[:30]),
                  "@%s: %s" % (r.get("username"), (r.get("text") or "").replace("\n", " ")[:120]),
                  "→ 초안: " + draft(r.get("text")),
                  "ID " + r["id"], ""]
    lines.append("답하려면: 'N번 ㄱ' 또는 고친 글")
    text = "\n".join(lines)
    print(text)
    if DRY:
        print("[dry-run] 카톡 안 보냄, 기록 안 남김"); return 0

    refresh, secret = v.get("kakao_refresh_token"), v.get("kakao_client_secret")
    if not refresh or not secret:
        print("카카오 토큰 없음 → PC 에서 python kakao_token.py"); return 1
    access, new_refresh = kakao_access(refresh, secret)
    kakao_memo(access, text, new[0][0].get("permalink") or "https://www.threads.com/@" + ME)
    if new_refresh and new_refresh != refresh:
        v["kakao_refresh_token"] = new_refresh
        금고.save(VAULT_KEY, v)
        print("카카오 refresh_token 갱신됨 (금고 저장)")
    seen |= {r["id"] for _, r in new}
    SEEN.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=0), encoding="utf-8")
    print("카톡 보냄 %d개" % len(new))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        msg = "%s 답글알림 실패: %s" % (__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"), e)
        print(msg)
        if not DRY:
            with open(LOG_ERR, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        sys.exit(1)
