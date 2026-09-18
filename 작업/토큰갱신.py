# -*- coding: utf-8 -*-
"""깃허브 액션이 매주 돌리는 60일 토큰 자동 갱신. 사용자가 손댈 일 없음. PAT 없음, Secrets 새 값 없음.

  1) 금고(토큰.enc)를 Secrets 의 IG_ACCESS_TOKEN 으로 열어 60일 사용자 토큰 + 앱 시크릿을 꺼낸다
  2) fb_exchange_token 으로 새 60일 토큰을 받는다 (만료가 60일로 다시 늘어남)
  3) debug_token 으로 유효·권한 확인, /me/accounts 로 hulit → @luck.arcade 붙어 있는지 확인
  4) 새 토큰을 금고에 다시 넣고 커밋. 토큰상태.json 에 만료 시각만 적는다(값 없음)
어느 단계든 실패하면 금고는 안 건드리고 종료코드 1 → 액션 실패 → 깃허브가 이메일.
토큰 값은 로그에 찍지 않는다.
"""
import os
import sys
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import 금고

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "토큰상태.json"
GRAPH = "https://graph.facebook.com/v26.0/"
KST = ZoneInfo("Asia/Seoul")
APP_ID = "1731062281302338"
PAGE_ID = "1339892089198082"          # hulit
IG_USER_ID = "17841476293738782"      # @luck.arcade
IG_USERNAME = "luck.arcade"
KEY = os.environ.get("IG_ACCESS_TOKEN", "").strip()

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def die(msg):
    print("[실패]", msg)
    sys.exit(1)


def graph(path, **params):
    url = GRAPH + path + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8", "replace")).get("error", {})
        except Exception:
            err = {}
        die("그래프 %s: code %s sub %s %s" % (path, err.get("code"), err.get("error_subcode"), err.get("message")))
    except Exception as e:
        die("전송 실패 %s: %s" % (path, e))


def threads_get(path, **params):
    """스레드 API GET. 실패면 예외(호출 쪽에서 잡는다)"""
    url = "https://graph.threads.net/" + path + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            err = json.loads(body).get("error", {})
            raise RuntimeError("code %s %s" % (err.get("code"), err.get("message")))
        except ValueError:
            raise RuntimeError("HTTP %s %s" % (e.code, body[:200]))


def kst(ts):
    return datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%d %H:%M") if ts else "없음"


def main():
    if not KEY:
        die("IG_ACCESS_TOKEN(금고 열쇠) 비어 있음")
    if not 금고.VAULT.exists():
        die("토큰.enc 없음. PC 에서 python ig_token.py 로 만든다")
    try:
        v = 금고.load(KEY)
    except Exception as e:
        die("금고를 못 열음(열쇠 불일치? PC 열쇠 태그와 비교: %s): %s" % (금고.key_tag(KEY), type(e).__name__))
    print("금고 열림 (열쇠 태그 %s, 이전 만료 %s)" % (금고.key_tag(KEY), kst(v.get("expires_at"))))

    # 2) 60일 연장
    j = graph("oauth/access_token", grant_type="fb_exchange_token", client_id=APP_ID,
              client_secret=v["app_secret"], fb_exchange_token=v["user_token"])
    new = j.get("access_token")
    if not new:
        die("새 토큰이 안 옴")

    # 3) 확인
    d = graph("debug_token", input_token=new, access_token=new).get("data", {})
    if not d.get("is_valid") or d.get("type") != "USER":
        die("새 토큰 확인 실패: %s" % {k: d.get(k) for k in ("type", "is_valid", "expires_at")})
    need = {"instagram_basic", "instagram_content_publish", "pages_show_list"}
    missing = need - set(d.get("scopes") or [])
    if missing:
        die("권한 부족: %s" % ", ".join(sorted(missing)))
    pages = graph("me/accounts", access_token=new, fields="id,name,instagram_business_account{id,username}").get("data", [])
    hit = [p for p in pages if p.get("id") == PAGE_ID]
    ig = (hit[0].get("instagram_business_account") if hit else None) or {}
    if ig.get("id") != IG_USER_ID or ig.get("username") != IG_USERNAME:
        die("hulit → @%s 연결 확인 실패: %s" % (IG_USERNAME, [(p.get("id"), p.get("name")) for p in pages]))
    exp = d.get("expires_at") or 0
    print("새 60일 토큰: 만료 %s, data_access %s, @%s" % (kst(exp), kst(d.get("data_access_expires_at")), IG_USERNAME))

    # 4) 스레드 토큰 연장 (금고에 있을 때만. 실패해도 인스타 쪽은 저장한다)
    th_state = "없음"
    if v.get("threads_token"):
        try:
            tj = threads_get("refresh_access_token", grant_type="th_refresh_token", access_token=v["threads_token"])
            if tj.get("access_token"):
                v["threads_token"] = tj["access_token"]
                v["threads_expires_at"] = int(time.time()) + int(tj.get("expires_in", 0))
                me = threads_get("me", fields="id,username", access_token=v["threads_token"])
                v["threads_username"] = me.get("username", v.get("threads_username"))
                th_state = "@%s, 만료 %s" % (v["threads_username"], kst(v["threads_expires_at"]))
                print("스레드 토큰 연장: %s" % th_state)
            else:
                th_state = "연장 실패: %s" % tj
                print("스레드 토큰 연장 실패(인스타는 계속): %s" % tj)
        except Exception as e:
            th_state = "연장 실패: %s" % e
            print("스레드 토큰 연장 실패(인스타는 계속): %s" % e)

    # 4-b) 카카오 refresh_token 연장 (금고에 있을 때만). refresh 로 access 를 받으면 만료 30일 안일 때 새 refresh 가 같이 온다
    kk_state = "없음"
    if v.get("kakao_refresh_token") and v.get("kakao_client_secret"):
        try:
            data = urllib.parse.urlencode({"grant_type": "refresh_token", "client_id": "5ef3d1fd0874a38dc6b62453503218a0",
                                           "client_secret": v["kakao_client_secret"], "refresh_token": v["kakao_refresh_token"]}).encode()
            with urllib.request.urlopen(urllib.request.Request("https://kauth.kakao.com/oauth/token", data), timeout=30) as r:
                kj = json.load(r)
            if kj.get("refresh_token"):
                v["kakao_refresh_token"] = kj["refresh_token"]
                v["kakao_refresh_expires_at"] = int(time.time()) + int(kj.get("refresh_token_expires_in", 0))
                kk_state = "refresh 갱신, 만료 %s" % kst(v["kakao_refresh_expires_at"])
            else:
                kk_state = "아직 유효(만료 %s)" % kst(v.get("kakao_refresh_expires_at"))
            print("카카오: %s" % kk_state)
        except Exception as e:
            kk_state = "연장 실패: %s" % e
            print("카카오 연장 실패(다른 건 계속): %s" % e)

    # 4-c) 유튜브 refresh_token 살아 있는지 (금고에 있을 때만). 구글 refresh_token 은 만료가 없어 갱신은 없고, 액세스 토큰만 받아 본다
    yt_state = "없음"
    if v.get("youtube_refresh_token"):
        try:
            data = urllib.parse.urlencode({"grant_type": "refresh_token", "client_id": v["youtube_client_id"],
                                           "client_secret": v["youtube_client_secret"], "refresh_token": v["youtube_refresh_token"]}).encode()
            with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data), timeout=30) as r:
                at = json.load(r).get("access_token", "")
            req = urllib.request.Request("https://www.googleapis.com/youtube/v3/channels?part=id,snippet&mine=true",
                                         headers={"Authorization": "Bearer " + at})
            with urllib.request.urlopen(req, timeout=30) as r:
                items = json.load(r).get("items") or []
            if items and items[0].get("id") == v.get("youtube_channel_id"):
                yt_state = "%s 정상" % items[0]["snippet"].get("title", "")
            else:
                yt_state = "채널 불일치: %s" % [(i.get("id"), i.get("snippet", {}).get("title")) for i in items]
            print("유튜브: %s" % yt_state)
        except urllib.error.HTTPError as e:
            if e.code == 403 and at:
                yt_state = "토큰 정상(업로드 권한만, 채널 조회 생략)"      # refresh 는 됐고 channels.list 만 권한 부족
            else:
                yt_state = "확인 실패(PC 에서 python youtube_token.py): HTTP %s" % e.code
            print("유튜브: %s" % yt_state)
        except Exception as e:
            yt_state = "확인 실패(PC 에서 python youtube_token.py): %s" % str(e)[:120]
            print("유튜브 토큰 확인 실패(다른 건 계속): %s" % e)

    # 5) 금고 갱신 + 상태
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    v.update({"user_token": new, "expires_at": exp, "updated": now})
    금고.save(KEY, v)
    STATE.write_text(json.dumps({"갱신": now, "만료": kst(exp), "data_access": kst(d.get("data_access_expires_at")),
                                 "인스타": "@" + IG_USERNAME, "스레드": th_state, "카카오": kk_state, "유튜브": yt_state}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("금고·토큰상태.json 갱신. 끝.")


if __name__ == "__main__":
    main()
