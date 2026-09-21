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
        return json.loads(body.decode("utf-8"))

    def 쓰기(self, name, data):
        self.s3.put_object(Bucket=self.bucket, Key=PREFIX + name,
                           Body=json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"),
                           ContentType="application/json; charset=utf-8")

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
