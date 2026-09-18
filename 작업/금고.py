# -*- coding: utf-8 -*-
"""토큰 금고 — 60일 페이스북 토큰과 앱 시크릿을 저장소 안 `토큰.enc` 에 암호화해 둔다.

열쇠 = 깃허브 Secrets 에 이미 있는 IG_ACCESS_TOKEN(만료 없는 페이지 토큰)의 SHA-256.
그래서 Secrets 에 새 값을 넣을 필요도, 깃허브 PAT 도 필요 없다. 저장소는 공개지만 열쇠 없이는 못 연다.
PC(ig_token.py)는 ~/.saju_meta_tokens.json 의 같은 페이지 토큰으로 잠그고, 액션(토큰갱신.py·쇼츠발행.py)은 Secrets 값으로 연다.

안 내용(JSON): app_secret, user_token(60일), expires_at(유닉스 초), updated(KST 문자열)
"""
import json
import base64
import hashlib
from pathlib import Path

from nacl.secret import SecretBox
from nacl.utils import random as nacl_random

VAULT = Path(__file__).resolve().parent.parent / "토큰.enc"


def key_from(page_token: str) -> bytes:
    return hashlib.sha256(page_token.strip().encode("utf-8")).digest()


def key_tag(page_token: str) -> str:
    """열쇠가 같은지 맞춰 보는 용도. 앞 8자리만. 값은 유추 못 함."""
    return hashlib.sha256(key_from(page_token)).hexdigest()[:8]


def save(page_token: str, data: dict, path: Path = VAULT):
    box = SecretBox(key_from(page_token))
    nonce = nacl_random(SecretBox.NONCE_SIZE)
    ct = box.encrypt(json.dumps(data, ensure_ascii=False).encode("utf-8"), nonce)
    path.write_text(base64.b64encode(ct).decode("ascii") + "\n", encoding="utf-8")


def load(page_token: str, path: Path = VAULT) -> dict:
    raw = base64.b64decode(path.read_text(encoding="utf-8").strip())
    box = SecretBox(key_from(page_token))
    return json.loads(box.decrypt(raw).decode("utf-8"))
