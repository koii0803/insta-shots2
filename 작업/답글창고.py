# -*- coding: utf-8 -*-
"""스레드 자동답글의 **공용 창고** — R2 에 둔다 (2026-09-21 사장님 지시 "기록은 R2 로").

왜 R2 인가: PC 와 깃허브 액션이 **같은 것을 봐야** 같은 댓글에 두 번 답하지 않는다.
저장소(git)에 두면 매 바퀴 커밋·푸시가 필요하고 충돌이 난다. 그리고 남의 생년월일을 공개 저장소에 올리면 안 된다.

창고 안 (전부 threads-reply/ 아래):
    대기.json      발행을 기다리는 답글 (시각·상대·글)
    상태.json      텔레그램 위치, 요약 보낸 시각, 보류 목록 …
    답한것.json    이미 답한 댓글 ID (최근 30일치만 유지)
    잠금.json      지금 누가 돌고 있나 (pid·시작 시각·PC냐 깃허브냐)
    심장박동.json  PC 가 마지막으로 돈 시각 — 깃허브는 이걸 보고 PC 가 살아 있는지 판단한다
    기록/YYYY-MM-DD.json   그날 판단 기록. 남의 생년월일이 들어 있어 **다음 날 지운다**
    성적/YYYY-MM-DD.json   그날 글별 조회·답글 수

R2 는 파일마다 '마지막에 쓴 사람이 이긴다'. 진짜 잠금은 안 되지만,
잠금을 쓰고 잠깐 뒤 **다시 읽어 내 것인지 확인**하면 실용적으로 충분하다 (R2 는 쓰자마자 읽힌다).
거기에 심장박동 20분 여유까지 있으니 PC 와 깃허브가 같은 순간에 시작할 일은 사실상 없다.

R2 가 안 되면 **아무것도 안 한다**(그 바퀴 건너뜀). 로컬로 대충 돌리면 양쪽이 어긋나 중복이 난다.
"""
import os
import json
import time
import datetime as dt

import boto3
from botocore.exceptions import ClientError

PREFIX = "threads-reply/"
DONE_KEEP_DAYS = 30        # 답한 것 기록은 이만큼만. 더 오래된 글은 어차피 안 본다(POST_AGE_DAYS 7)

# ── 잠그기 (2026-09-25 사장님 지시 "구멍 막아") ──
# 이 버킷은 r2.dev 공개 버킷이다. 주소만 알면 누구나 읽는다. 기록/날짜.json 엔 손님 생년월일이 있다.
# 그래서 심장박동·잠금 빼고 전부 **암호로 잠가서** 올린다. 열쇠는 R2 비밀 열쇠에서 뽑는다
# (PC 도 깃허브도 이미 갖고 있는 값이라 새 Secret 이 안 생긴다). 잠긴 파일은 "enc1:" 로 시작한다.
# 안 잠긴 옛 파일도 읽힌다 (읽을 땐 둘 다, 쓸 땐 늘 잠근다). `python 답글창고.py --잠그기` 가 옛것을 한 번에 잠근다.
암호화안함 = ("심장박동.json", "잠금.json")
잠금표시 = "enc1:"


def _열쇠():
    import hashlib
    비밀 = _env("R2_SECRET_ACCESS_KEY")
    if not 비밀:
        raise RuntimeError("R2_SECRET_ACCESS_KEY 가 없어서 창고 열쇠를 못 만든다")
    return hashlib.sha256(("threads-reply|" + 비밀).encode("utf-8")).digest()


def 잠그기(글):
    import base64
    from nacl.secret import SecretBox          # pynacl. 금고.py 와 같은 꾸러미
    from nacl.utils import random as 난수
    암호 = SecretBox(_열쇠()).encrypt(글.encode("utf-8"), 난수(SecretBox.NONCE_SIZE))
    return 잠금표시 + base64.b64encode(bytes(암호)).decode("ascii")


def 풀기(본문):
    import base64
    from nacl.secret import SecretBox
    return SecretBox(_열쇠()).decrypt(base64.b64decode(본문[len(잠금표시):].strip())).decode("utf-8")
LOG_KEEP_DAYS = 1          # 판단 기록(남의 생년월일)은 이만큼 지나면 지운다
SCORE_KEEP_DAYS = 90       # 글 성적은 오래 둬도 개인정보가 없다


def _env(name):
    """환경변수 → 없으면 PC 의 config.user_env (PC 에서만 있다)."""
    v = os.environ.get(name, "").strip()
    if v:
        return v
    try:
        import config
        return config.user_env(name) or ""
    except Exception:
        return ""


class 창고:
    def __init__(self):
        acct, key, sec, bucket = (_env("CLOUDFLARE_ACCOUNT_ID_2"), _env("R2_ACCESS_KEY_ID"),
                                  _env("R2_SECRET_ACCESS_KEY"), _env("R2_BUCKET"))
        if not all((acct, key, sec, bucket)):
            raise RuntimeError("R2 접근값이 없다 (CLOUDFLARE_ACCOUNT_ID_2 / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_BUCKET)")
        self.bucket = bucket
        self.s3 = boto3.client("s3", endpoint_url="https://%s.r2.cloudflarestorage.com" % acct,
                               aws_access_key_id=key, aws_secret_access_key=sec, region_name="auto")

    # ── 기본 읽기·쓰기 ─────────────────────────────────────────
    def 읽기(self, name, default=None):
        """없으면 default. 깨진 JSON 이면 예외(조용히 넘기지 않는다 — 대기줄이 비어 버린다)."""
        try:
            body = self.s3.get_object(Bucket=self.bucket, Key=PREFIX + name)["Body"].read()
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return default
            raise
        글 = body.decode("utf-8")
        if 글.startswith(잠금표시):
            글 = 풀기(글)                    # 열쇠가 다르면 여기서 터진다. 조용히 빈 것으로 안 넘긴다
        return json.loads(글)

    def 쓰기(self, name, data):
        글 = json.dumps(data, ensure_ascii=False, indent=1)
        올릴것 = 글 if name in 암호화안함 else 잠그기(글)
        self.s3.put_object(Bucket=self.bucket, Key=PREFIX + name,
                           Body=올릴것.encode("utf-8"),
                           ContentType="text/plain; charset=utf-8")

    def 잠겼나(self, name):
        """(잠김, 없음, 열림)"""
        try:
            몸 = self.s3.get_object(Bucket=self.bucket, Key=PREFIX + name)["Body"].read(16)
        except ClientError:
            return "없음"
        return "잠김" if 몸.startswith(잠금표시.encode()) else "열림"

    def 지우기(self, name):
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=PREFIX + name)
        except ClientError:
            pass

    def 목록(self, sub=""):
        """sub 아래 파일 이름들 (PREFIX 뗀 것)."""
        out, token = [], None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": PREFIX + sub}
            if token:
                kw["ContinuationToken"] = token
            r = self.s3.list_objects_v2(**kw)
            out += [o["Key"][len(PREFIX):] for o in r.get("Contents", [])]
            if not r.get("IsTruncated"):
                return out
            token = r.get("NextContinuationToken")

    # ── 잠금 ─────────────────────────────────────────────────
    def 잠금_잡기(self, who, stale_min=60):
        """(잡았나, 누가 잡고 있나). 쓰고 나서 다시 읽어 내 것인지 확인한다."""
        cur = self.읽기("잠금.json")
        if cur:
            try:
                started = dt.datetime.strptime(cur["started"], "%Y-%m-%d %H:%M:%S")
                if (dt.datetime.now() - started).total_seconds() < stale_min * 60:
                    return False, cur
            except Exception:
                pass                                  # 깨진 잠금은 가져간다
        mine = {"who": who, "pid": os.getpid(), "started": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "nonce": "%d-%d" % (os.getpid(), int(time.time() * 1000))}
        self.쓰기("잠금.json", mine)
        time.sleep(1.5)
        back = self.읽기("잠금.json") or {}
        if back.get("nonce") != mine["nonce"]:
            return False, back                        # 같은 순간에 누가 덮어씀 → 양보
        return True, None

    def 잠금_풀기(self):
        self.지우기("잠금.json")

    # ── 심장박동 (PC 가 살아 있다는 표시) ──────────────────────
    def 심장박동_찍기(self, who="PC"):
        self.쓰기("심장박동.json", {"who": who, "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")})

    def 심장박동_지난분(self):
        """마지막 심장박동이 몇 분 전인가. 한 번도 없으면 아주 큰 수."""
        hb = self.읽기("심장박동.json")
        if not hb:
            return 10 ** 6
        try:
            at = dt.datetime.strptime(hb["at"], "%Y-%m-%d %H:%M:%S")
            return (dt.datetime.now() - at).total_seconds() / 60
        except Exception:
            return 10 ** 6

    # ── 답한 것 (중복 방지의 핵심) ──────────────────────────────
    def 답한것_읽기(self):
        """{reply_id: 날짜} → set 으로 돌려준다."""
        return set((self.읽기("답한것.json") or {}).keys())

    def 답한것_추가(self, reply_id):
        d = self.읽기("답한것.json") or {}
        d[reply_id] = dt.datetime.now().strftime("%Y-%m-%d")
        cutoff = (dt.datetime.now() - dt.timedelta(days=DONE_KEEP_DAYS)).strftime("%Y-%m-%d")
        d = {k: v for k, v in d.items() if v >= cutoff}
        self.쓰기("답한것.json", d)

    # ── 판단 기록 (개인정보 → 하루 뒤 삭제) ────────────────────
    def 기록_추가(self, row):
        key = "기록/%s.json" % dt.datetime.now().strftime("%Y-%m-%d")
        rows = self.읽기(key) or []
        rows.append(row)
        self.쓰기(key, rows)

    def 기록_오늘(self):
        return self.읽기("기록/%s.json" % dt.datetime.now().strftime("%Y-%m-%d")) or []

    def 보류_넣기(self, rid, row):
        """본체가 "이건 내가 못 정하겠다" 한 댓글. 6시간마다 도는 AI자동답변이 꺼내 간다.

        2026-09-24 사장님 지시로 **'무시' 라벨을 없앴다.** 전에는 분류기가 무시라고 하면
        그대로 버리고 '답한 것'으로 찍었는데, 봇이 물어 놓고 그 답을 버리는 일이 열 건 났다
        (@kmj241 '한텀걸리는 자리예요', @elegancejh '웅 있어....' 등).
        이제 버리지 않고 여기 쌓아 둔다."""
        cur = self.읽기("보류목록.json") or {}
        cur[rid] = row
        self.쓰기("보류목록.json", cur)

    def 보류_목록(self):
        return self.읽기("보류목록.json") or {}

    def 보류_빼기(self, rids):
        cur = self.읽기("보류목록.json") or {}
        for r in rids:
            cur.pop(r, None)
        self.쓰기("보류목록.json", cur)

    def 손대지마_목록(self):
        """자동 답글을 아예 달지 않을 사람들 (2026-09-25 사장님 지시).

        손님이 디엠으로 넘어갔는데 봇이 스레드에서 계속 말을 걸면 겹친다
        (@nujousmik: "메세지 좀 봐주세요" 라는데 봇이 스레드로 또 물었다).
        여기 든 사람은 본체도 AI자동답변도 손대지 않는다. 사장님이 직접 한다."""
        return set(self.읽기("손대지마.json") or [])

    def 손대지마_넣기(self, 이름들):
        cur = self.손대지마_목록() | set(이름들)
        self.쓰기("손대지마.json", sorted(cur))
        return cur

    def 손대지마_빼기(self, 이름들):
        cur = self.손대지마_목록() - set(이름들)
        self.쓰기("손대지마.json", sorted(cur))
        return cur

    def 토큰_적기(self, row):
        """AI 한 번 부를 때마다 토큰·값을 적는다 (2026-09-24 사장님 지시: 기록은 클라우드로).

        **안 지운다.** 남의 생년월일이 없어서 하루 뒤 삭제 대상이 아니다
        (오래된것_지우기 는 기록/ 과 성적/ 만 본다).
        PC 든 깃허브든 같은 파일에 쌓이니 어디서 얼마나 썼는지 한자리에서 보인다."""
        key = "토큰/%s.json" % dt.datetime.now().strftime("%Y-%m-%d")
        rows = self.읽기(key) or []
        rows.append(row)
        self.쓰기(key, rows)

    def 토큰_오늘(self):
        return self.읽기("토큰/%s.json" % dt.datetime.now().strftime("%Y-%m-%d")) or []

    def 성적_추가(self, rows):
        key = "성적/%s.json" % dt.datetime.now().strftime("%Y-%m-%d")
        cur = self.읽기(key) or []
        self.쓰기(key, cur + rows)

    def 오래된것_지우기(self):
        """하루 지난 판단 기록(남의 생년월일)과 오래된 성적을 지운다. 지운 파일 이름들을 돌려준다."""
        gone = []
        today = dt.datetime.now().date()
        for name in self.목록("기록/"):
            try:
                d = dt.datetime.strptime(name[len("기록/"):-5], "%Y-%m-%d").date()
            except Exception:
                continue
            if (today - d).days >= LOG_KEEP_DAYS:
                self.지우기(name); gone.append(name)
        for name in self.목록("성적/"):
            try:
                d = dt.datetime.strptime(name[len("성적/"):-5], "%Y-%m-%d").date()
            except Exception:
                continue
            if (today - d).days >= SCORE_KEEP_DAYS:
                self.지우기(name); gone.append(name)
        return gone


# ── 명령줄 ─────────────────────────────────────────────
def _명령줄():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    c = 창고()
    if "--잠그기" in sys.argv:
        got, held = c.잠금_잡기("잠그기", stale_min=60)
        if not got:
            print("지금 %s 가 돌고 있다. 잠시 뒤 다시" % (held or {}).get("who"))
            return 1
        try:
            n = 0
            for name in c.목록():
                if name in 암호화안함 or name.endswith("/") or c.잠겼나(name) != "열림":
                    continue
                data = c.읽기(name)
                c.쓰기(name, data)
                print("  %-28s %s" % (name, "잠금 OK" if c.잠겼나(name) == "잠김" and c.읽기(name) == data else "!! 다르다"))
                n += 1
            print("%d개 잠갔다" % n)
        finally:
            c.잠금_풀기()
    열린것 = 0
    for name in c.목록():
        if name.endswith("/"):
            continue
        상태 = "공개(개인정보 없음)" if name in 암호화안함 else c.잠겼나(name)
        열린것 += 상태 == "열림"
        print("  %-28s %s" % (name, 상태))
    if 열린것:
        print("\n안 잠긴 파일 %d개. python 답글창고.py --잠그기" % 열린것)
    return 1 if 열린것 else 0


if __name__ == "__main__":
    raise SystemExit(_명령줄())
