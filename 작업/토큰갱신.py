# -*- coding: utf-8 -*-
"""깃허브 액션이 매주 돌리는 인스타 토큰 자동 갱신. 사용자가 직접 만질 일 없음.

  1) Secrets 의 FB_USER_TOKEN(60일 사용자 토큰)을 새 60일 토큰으로 바꾼다 (앱 ID + 앱 시크릿, fb_exchange_token)
  2) 새 토큰으로 /me/accounts → hulit 페이지의 access_token = 페이지 토큰
  3) debug_token 으로 PAGE·유효·@luck.arcade 확인
  4) 깃허브 Secrets FB_USER_TOKEN·IG_ACCESS_TOKEN 을 스스로 다시 쓴다 (GH_PAT, PyNaCl sealed box)
  5) 토큰상태.json 에 갱신 시각·사용자 토큰 만료 시각만 적는다 (토큰 값은 절대 안 적음)
어느 단계든 실패하면 Secrets 는 안 건드리고 종료코드 1 → 액션 실패 → 깃허브가 이메일.
토큰 값은 로그에도 찍지 않는다.
"""
import os
import sys
import json
import base64
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "토큰상태.json"
GRAPH = "https://graph.facebook.com/v26.0/"
GH_API = "https://api.github.com"
KST = ZoneInfo("Asia/Seoul")

APP_ID = os.environ.get("META_APP_ID", "1731062281302338").strip()
APP_SECRET = os.environ.get("META_APP_SECRET", "").strip()
USER_TOKEN = os.environ.get("FB_USER_TOKEN", "").strip()
GH_PAT = os.environ.get("GH_PAT", "").strip()
REPO = os.environ.get("GITHUB_REPOSITORY", "koii0803/insta-shots2")
PAGE_ID = "1339892089198082"          # hulit
IG_USER_ID = "17841476293738782"      # @luck.arcade
IG_USERNAME = "luck.arcade"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def die(msg):
    print("[실패]", msg)
    sys.exit(1)


def http(method, url, data=None, headers=None):
    req = urllib.request.Request(url, data, headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8")
            return r.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body[:300]}


def graph(path, **params):
    st, j = http("GET", GRAPH + path + "?" + urllib.parse.urlencode(params))
    if "error" in j:
        e = j["error"]
        die("그래프 %s: code %s sub %s %s" % (path, e.get("code"), e.get("error_subcode"), e.get("message")))
    return j


def gh(method, path, body=None):
    h = {"Authorization": "Bearer " + GH_PAT, "Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "saju-shorts"}
    data = json.dumps(body).encode() if body is not None else None
    if data:
        h["Content-Type"] = "application/json"
    st, j = http(method, GH_API + path, data, h)
    if st >= 300:
        die("깃허브 %s %s → %s %s" % (method, path, st, j))
    return j


def set_secret(name, value, key):
    from nacl import encoding, public
    pk = public.PublicKey(key["key"].encode(), encoding.Base64Encoder())
    enc = base64.b64encode(public.SealedBox(pk).encrypt(value.encode())).decode()
    gh("PUT", "/repos/%s/actions/secrets/%s" % (REPO, name), {"encrypted_value": enc, "key_id": key["key_id"]})
    print("Secrets %s 갱신" % name)


def main():
    missing = [k for k, v in (("META_APP_SECRET", APP_SECRET), ("FB_USER_TOKEN", USER_TOKEN), ("GH_PAT", GH_PAT)) if not v]
    if missing:
        die("Secrets 비어 있음: %s (PC에서 python ig_token.py --auto 로 넣는다)" % ", ".join(missing))

    # 1) 60일 토큰 연장
    j = graph("oauth/access_token", grant_type="fb_exchange_token", client_id=APP_ID,
              client_secret=APP_SECRET, fb_exchange_token=USER_TOKEN)
    new_user = j.get("access_token")
    if not new_user:
        die("새 사용자 토큰이 안 옴: %s" % j)
    d = graph("debug_token", input_token=new_user, access_token=new_user).get("data", {})
    if not d.get("is_valid"):
        die("새 사용자 토큰이 유효하지 않음")
    exp = d.get("expires_at") or 0
    exp_s = datetime.fromtimestamp(exp, KST).strftime("%Y-%m-%d %H:%M") if exp else "없음"
    print("① 사용자 토큰 연장: 만료 %s, data_access %s" % (
        exp_s, datetime.fromtimestamp(d["data_access_expires_at"], KST).strftime("%Y-%m-%d") if d.get("data_access_expires_at") else "-"))

    # 2) 페이지 토큰
    pages = graph("me/accounts", access_token=new_user, fields="id,name,access_token,instagram_business_account{id,username}").get("data", [])
    hit = [p for p in pages if p.get("id") == PAGE_ID]
    if not hit:
        die("페이지 hulit(%s) 이 목록에 없음: %s" % (PAGE_ID, [(p.get("id"), p.get("name")) for p in pages]))
    ig = hit[0].get("instagram_business_account") or {}
    if ig.get("id") != IG_USER_ID or ig.get("username") != IG_USERNAME:
        die("hulit 에 붙은 인스타가 @%s 가 아님: %s" % (IG_USERNAME, ig))
    page_tok = hit[0].get("access_token")
    if not page_tok:
        die("페이지 access_token 비어 있음")

    # 3) 확인
    pd = graph("debug_token", input_token=page_tok, access_token=page_tok).get("data", {})
    if not pd.get("is_valid") or pd.get("type") != "PAGE":
        die("페이지 토큰 확인 실패: %s" % {k: pd.get(k) for k in ("type", "is_valid", "expires_at")})
    u = graph(IG_USER_ID, fields="username", access_token=page_tok)
    if u.get("username") != IG_USERNAME:
        die("IG_USER_ID 가 @%s 가 아님: %s" % (IG_USERNAME, u))
    print("② 페이지 토큰: PAGE, 유효, expires_at=%s, @%s" % (pd.get("expires_at"), u.get("username")))

    # 4) Secrets 다시 쓰기
    key = gh("GET", "/repos/%s/actions/secrets/public-key" % REPO)
    set_secret("FB_USER_TOKEN", new_user, key)
    set_secret("IG_ACCESS_TOKEN", page_tok, key)

    # 5) 상태 기록 (값 없음)
    STATE.write_text(json.dumps({
        "갱신": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "사용자토큰만료": exp_s,
        "data_access_expires": datetime.fromtimestamp(d["data_access_expires_at"], KST).strftime("%Y-%m-%d") if d.get("data_access_expires_at") else None,
        "페이지토큰": "만료 없음" if not pd.get("expires_at") else datetime.fromtimestamp(pd["expires_at"], KST).strftime("%Y-%m-%d %H:%M"),
        "인스타": "@" + IG_USERNAME,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("③ 토큰상태.json 기록. 끝.")


if __name__ == "__main__":
    main()
