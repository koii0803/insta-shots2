# 사주 아케이드 릴스 예약표

인스타 릴스 자동 게시의 **예약표만** 있는 저장소. 영상은 여기 없고 Cloudflare R2(공개 버킷)에 있다.

- `쇼츠예약.json` — 예약표. 한 건 = id, 영상 주소(R2), 캡션, 예약 시각, 상태(대기·게시·실패), 유튜브 주소. 액션이 `ig_container_id`·`ig_media_id`·`posted_at`·`attempts`·`last_error`를 덧붙인다.
- `작업/쇼츠발행.py` — 깃허브 액션이 돌리는 발행 스크립트. 토큰 검사 → 시간 지난 "대기" 건을 메타 그래프 API(컨테이너 → 상태 확인 → 게시)로 인스타 @luck.arcade 에 직접 올린다. 이어서 스레드(@paljaoppa, 글만)와 페북 페이지 릴스(hulit, 2026-09-18 추가. 사용자 토큰에 pages_manage_posts·publish_video 가 있을 때만).
- `.github/workflows/shorts-publish.yml` — 매시 정각 cron + 수동 실행. 깃허브가 정각 실행을 몇 시간 미루는 일이 흔하다(의도적으로 그대로 둠).
- `발행기록.txt` / `오류기록.txt` — 액션이 남기는 기록.

토큰은 저장소에 없다. Settings → Secrets and variables → Actions 의 `IG_USER_ID`, `IG_ACCESS_TOKEN`(만료 없는 페이지 토큰)만 쓴다.
토큰이 죽으면 액션이 실패하고 깃허브가 이메일로 알린다. PC 의 `유튜브업로더/ig_token.py` 로 다시 만든다.

자세한 건 PC 의 스킬 `사주쇼츠업로드자동화`.
