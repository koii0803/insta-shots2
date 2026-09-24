# -*- coding: utf-8 -*-
"""쇼츠·스레드 **예약표와 기록을 R2 에 둔다** (2026-09-25 사장님 지시 "기록은 깃허브에 안 올린다. 클라우드로").

    python 쇼츠창고.py --예약표          예약표 보기
    python 쇼츠창고.py --목록            창고 안 파일 (잠겼나까지)
    python 쇼츠창고.py --보기 오류기록.txt  파일 하나 (기록은 뒤 40줄)
    python 쇼츠창고.py --소재 "한 줄"     사람 글 소재 한 줄 넣기 (스레드소재.txt)
    python 쇼츠창고.py --옮기기          저장소의 옛 파일들을 R2 로 (한 번만. 있으면 안 덮어쓴다)

왜
    전에는 예약표(쇼츠예약.json)·발행기록·오류기록을 깃허브에 커밋했다. PC 와 액션이 서로 커밋하다
    충돌이 났고(2026-09-22 같은 영상 두 번 올라감), 기록은 계속 자라 저장소가 찼다.
    이제 깃허브엔 **코드만** 있다. 예약표·기록은 전부 여기(R2 `shorts/`)다. PC 와 액션이 같은 것을 본다.

창고 안 (전부 shorts/ 아래)
    예약표.json          옛 쇼츠예약.json. 인스타·스레드·페북·유튜브 대기 건
    발행기록.txt         액션이 올린 것 (뒤 3000줄)
    오류기록.txt         액션이 남긴 오류 (뒤 3000줄)
    스레드글기록.jsonl   예약표에 들어간 스레드 글 (중복 검사용)
    스레드하루치기록.json  하루치를 오늘 만들었나
    스레드링크기록.json   마지막 링크 답글 시각
    몰림경고.json        하루 3편 경고를 언제 보냈나
    페북댓글띠.json      페북 댓글 띠 세기 결과
    토큰상태.json        토큰 만료 시각 (값 없음)
    스레드소재.txt       사람 글 소재 (한 줄에 하나)
    잠금.json            지금 누가 예약표를 고치고 있나

잠금
    PC(등록·옮기기·정리)와 액션(발행·하루치)이 같은 예약표를 고친다. **잠금을 잡고 읽고 고치고 쓴다.**
    액션은 발행하는 동안 내내 잡는다(길면 20분). PC 는 90초까지 기다리고 그래도 안 되면 멈춘다.
    30분 넘게 잡힌 잠금은 죽은 것으로 보고 뺏는다.

암호
    이 버킷은 공개 버킷이다. 잠금 빼고 전부 잠가서(enc1) 올린다. 열쇠는 답글창고와 같은 R2 비밀 열쇠에서 뽑는다.
    답글창고.py(팔자오빠 답글 창고 threads-reply/)와 **접두어가 다르다.** 서로 안 섞인다.

boto3·pynacl 은 파이썬 꾸러미다.
"""
import io
import json
import os
import sys
import time
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import 답글창고                       # 같은 폴더. 잠그기·풀기·_env 만 빌린다

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

접두어 = "shorts/"
예약표이름 = "예약표.json"
암호화안함 = ("잠금.json",)
줄수한도 = {"발행기록.txt": 3000, "오류기록.txt": 3000}
저장소 = Path(__file__).resolve().parent.parent
옮길것 = {"쇼츠예약.json": 예약표이름, "발행기록.txt": "발행기록.txt", "오류기록.txt": "오류기록.txt",
          "스레드글기록.jsonl": "스레드글기록.jsonl", "스레드하루치기록.json": "스레드하루치기록.json",
          "스레드링크기록.json": "스레드링크기록.json", "몰림경고.json": "몰림경고.json",
          "페북댓글띠.json": "페북댓글띠.json", "토큰상태.json": "토큰상태.json", "스레드소재.txt": "스레드소재.txt"}


def _열쇠():
    import hashlib
    비밀 = 답글창고._env("R2_SECRET_ACCESS_KEY")
    if not 비밀:
        raise RuntimeError("R2_SECRET_ACCESS_KEY 가 없어서 창고 열쇠를 못 만든다")
    return hashlib.sha256(("shorts|" + 비밀).encode("utf-8")).digest()


def 잠그기(글):
    import base64
    from nacl.secret import SecretBox
    from nacl.utils import random as 난수
    암호 = SecretBox(_열쇠()).encrypt(글.encode("utf-8"), 난수(SecretBox.NONCE_SIZE))
    return 답글창고.잠금표시 + base64.b64encode(bytes(암호)).decode("ascii")


def 풀기(본문):
    import base64
    from nacl.secret import SecretBox
    return SecretBox(_열쇠()).decrypt(base64.b64decode(본문[len(답글창고.잠금표시):].strip())).decode("utf-8")


class 창고:
    def __init__(self):
        import boto3
        from botocore.exceptions import ClientError
        acct, key, sec, bucket = (답글창고._env("CLOUDFLARE_ACCOUNT_ID_2"), 답글창고._env("R2_ACCESS_KEY_ID"),
                                  답글창고._env("R2_SECRET_ACCESS_KEY"), 답글창고._env("R2_BUCKET"))
        if not all((acct, key, sec, bucket)):
            raise RuntimeError("R2 접근값이 없다 (CLOUDFLARE_ACCOUNT_ID_2 / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_BUCKET)")
        self._ClientError = ClientError
        self.bucket = bucket
        self.s3 = boto3.client("s3", endpoint_url="https://%s.r2.cloudflarestorage.com" % acct,
                               aws_access_key_id=key, aws_secret_access_key=sec, region_name="auto")

    # ── 글 ──
    def 글읽기(self, 이름, 기본=None):
        try:
            몸 = self.s3.get_object(Bucket=self.bucket, Key=접두어 + 이름)["Body"].read()
        except self._ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return 기본
            raise
        글 = 몸.decode("utf-8")
        if 글.startswith(답글창고.잠금표시):
            글 = 풀기(글)              # 열쇠가 다르면 여기서 터진다. 조용히 빈 것으로 안 넘긴다
        return 글

    def 글쓰기(self, 이름, 글):
        올릴것 = 글 if 이름 in 암호화안함 else 잠그기(글)
        self.s3.put_object(Bucket=self.bucket, Key=접두어 + 이름, Body=올릴것.encode("utf-8"),
                           ContentType="text/plain; charset=utf-8")

    def 붙이기(self, 이름, 줄):
        글 = self.글읽기(이름, "") or ""
        if 글 and not 글.endswith("\n"):
            글 += "\n"
        글 += 줄.rstrip("\n") + "\n"
        한도 = 줄수한도.get(이름)
        if 한도:
            줄들 = 글.splitlines()
            if len(줄들) > 한도:
                글 = "\n".join(줄들[-한도:]) + "\n"
        self.글쓰기(이름, 글)

    def 줄들(self, 이름):
        나온것 = []
        for line in (self.글읽기(이름, "") or "").splitlines():
            line = line.strip()
            if line:
                try:
                    나온것.append(json.loads(line))
                except Exception:
                    pass
        return 나온것

    # ── JSON ──
    def 읽기(self, 이름, 기본=None):
        글 = self.글읽기(이름)
        if 글 is None or not 글.strip():
            return 기본
        return json.loads(글)

    def 쓰기(self, 이름, 자료):
        self.글쓰기(이름, json.dumps(자료, ensure_ascii=False, indent=1) + "\n")

    def 상태적기(self, 이름, 바꿀것):
        """JSON 파일의 몇 칸만 고친다 (토큰상태.json 같은 것)."""
        d = self.읽기(이름) or {}
        d.update(바꿀것)
        self.쓰기(이름, d)

    def 지우기(self, 이름):
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=접두어 + 이름)
        except self._ClientError:
            pass

    def 목록(self):
        나온것, 다음 = [], None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": 접두어}
            if 다음:
                kw["ContinuationToken"] = 다음
            r = self.s3.list_objects_v2(**kw)
            나온것 += [(o["Key"][len(접두어):], o["Size"]) for o in r.get("Contents", [])]
            if not r.get("IsTruncated"):
                return 나온것
            다음 = r.get("NextContinuationToken")

    def 잠겼나(self, 이름):
        try:
            몸 = self.s3.get_object(Bucket=self.bucket, Key=접두어 + 이름)["Body"].read(16)
        except self._ClientError:
            return "없음"
        return "잠김" if 몸.startswith(답글창고.잠금표시.encode()) else "열림"

    # ── 예약표 ──
    def 예약표읽기(self):
        return self.읽기(예약표이름, []) or []

    def 예약표쓰기(self, q):
        self.쓰기(예약표이름, q)

    # ── 잠금 ──
    def 잠금_잡기(self, 누구, 기다림초=90, 죽은분=30):
        """잡으면 True. 기다려도 못 잡으면 False. 쓰고 나서 다시 읽어 내 것인지 확인한다."""
        끝 = time.time() + 기다림초
        while True:
            현재 = self.읽기("잠금.json")
            잡혀있나 = False
            if 현재:
                try:
                    시작 = dt.datetime.strptime(현재["시작"], "%Y-%m-%d %H:%M:%S")
                    잡혀있나 = (dt.datetime.now() - 시작).total_seconds() < 죽은분 * 60
                except Exception:
                    잡혀있나 = False
            if not 잡혀있나:
                내것 = {"누구": 누구, "pid": os.getpid(), "시작": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "표": "%d-%d" % (os.getpid(), int(time.time() * 1000))}
                self.쓰기("잠금.json", 내것)
                time.sleep(1.5)
                if (self.읽기("잠금.json") or {}).get("표") == 내것["표"]:
                    return True
            if time.time() > 끝:
                print("예약표가 잠겨 있다: %s (%s 부터)" % ((현재 or {}).get("누구"), (현재 or {}).get("시작")))
                return False
            time.sleep(5)

    def 잠금_풀기(self):
        self.지우기("잠금.json")


_열린것 = None


def 열기():
    global _열린것
    if _열린것 is None:
        _열린것 = 창고()
    return _열린것


def 예약표고치기(함수, 누구="PC", 기다림초=90):
    """잠그고 → 읽고 → 함수(표) → 쓰고 → 푼다. 못 잠그면 False (아무것도 안 고친다)."""
    c = 열기()
    if not c.잠금_잡기(누구, 기다림초):
        return False
    try:
        표 = c.예약표읽기()
        새것 = 함수(표)
        if 새것 is None:
            새것 = 표
        c.예약표쓰기(새것)
        return True
    finally:
        c.잠금_풀기()


# ── 명령줄 ──
def 예약표보기():
    q = 열기().예약표읽기()
    if not q:
        print("예약표 비어 있음")
        return 0
    for it in sorted(q, key=lambda x: x.get("publish_at", "")):
        print("%s  %-32s 인스타 %-3s 스레드 %-3s 페북 %-3s 유튜브 %-3s %s" % (
            it.get("publish_at"), it.get("id"), it.get("status", "-"), it.get("threads_status", "-"),
            it.get("fb_status", "-"), it.get("youtube_status", "-"), (it.get("last_error") or it.get("youtube_error") or "")[:60]))
    print("모두 %d건" % len(q))
    return 0


def 목록():
    c = 열기()
    열린것 = 0
    for 이름, 크기 in c.목록():
        상태 = "공개(개인정보 없음)" if 이름 in 암호화안함 else c.잠겼나(이름)
        열린것 += 상태 == "열림"
        print("  %-22s %8.1fKB  %s" % (이름, 크기 / 1024.0, 상태))
    if 열린것:
        print("\n안 잠긴 파일 %d개" % 열린것)
    return 1 if 열린것 else 0


def 보기(이름):
    글 = 열기().글읽기(이름)
    if 글 is None:
        print("없다: %s" % 이름)
        return 1
    줄들 = 글.splitlines()
    if 이름.endswith((".txt", ".jsonl")) and len(줄들) > 40:
        print("(뒤 40줄 / 전체 %d줄)" % len(줄들))
        줄들 = 줄들[-40:]
    print("\n".join(줄들))
    return 0


def 소재넣기(줄):
    열기().붙이기("스레드소재.txt", 줄.strip())
    print("넣었다. 지금 소재:")
    return 보기("스레드소재.txt")


def 옮기기():
    c = 열기()
    if not c.잠금_잡기("옮기기", 기다림초=120):
        return 1
    try:
        올림 = 건너뜀 = 0
        실패 = []
        for 파일, 이름 in 옮길것.items():
            p = 저장소 / 파일
            if not p.exists():
                continue
            if c.글읽기(이름) is not None:
                print("  %-22s R2 에 이미 있다. 안 덮어쓴다" % 이름)
                건너뜀 += 1
                continue
            글 = io.open(p, encoding="utf-8-sig").read()
            한도 = 줄수한도.get(이름)
            if 한도:
                글 = "\n".join(글.splitlines()[-한도:]) + "\n"
            c.글쓰기(이름, 글)
            if c.글읽기(이름) == 글:
                print("  %-22s 올림 %6.1fKB · 대조 OK" % (이름, len(글.encode("utf-8")) / 1024.0))
                올림 += 1
            else:
                print("  %-22s 되읽은 게 다르다!" % 이름)
                실패.append(이름)
        print("\n올림 %d · 건너뜀 %d · 실패 %d" % (올림, 건너뜀, len(실패)))
        return 1 if 실패 else 0
    finally:
        c.잠금_풀기()


def main():
    import argparse
    ap = argparse.ArgumentParser(description="쇼츠·스레드 예약표 창고 (R2)")
    ap.add_argument("--예약표", action="store_true")
    ap.add_argument("--목록", action="store_true")
    ap.add_argument("--보기", metavar="이름")
    ap.add_argument("--소재", metavar="한줄", help="사람 글 소재 넣기")
    ap.add_argument("--옮기기", action="store_true")
    a = ap.parse_args()
    if a.예약표:
        return 예약표보기()
    if a.목록:
        return 목록()
    if a.보기:
        return 보기(a.보기)
    if a.소재:
        return 소재넣기(a.소재)
    if a.옮기기:
        return 옮기기()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
