# VS Code와 Python CLI 사용법

VS Code에서 저장소를 열고 통합 터미널을 사용합니다. 명령은 macOS/Linux 셸 기준이며 아래 원고 파일과 ID는 예시입니다. 실제 파일이 있어야 합니다.

## 상태와 도움말

```bash
.venv/bin/python blog.py --help
.venv/bin/python blog.py doctor
.venv/bin/python blog.py status
.venv/bin/python blog.py categories
.venv/bin/python app_runner.py --help
```

doctor는 WordPress 인증·대상 사이트를 조회하고, status는 로컬 상태를 보여줍니다. status만으로 서버의 현재 공개 상태가 보장되지는 않습니다.

## 수동 원고 발행

[원고 규격](CONTENT.md)에 맞는 완성 article JSON을 `articles/manual-extra.json`에 준비합니다. 예를 들어 id가 `manual-extra-2026-10-06`이면 아래 순서로 처리합니다.

```bash
.venv/bin/python blog.py validate articles/manual-extra.json --check-links
.venv/bin/python blog.py preview articles/manual-extra.json
.venv/bin/python blog.py upload articles/manual-extra.json
.venv/bin/python blog.py approve articles/manual-extra.json \
  --reviewer "운영자" --checks facts,style,rights,links
.venv/bin/python blog.py publish articles/manual-extra.json \
  --confirm manual-extra-2026-10-06
```

- validate: HTML·주장/출처 매핑·날짜·이미지 권리 기록을 검사합니다. 링크 조회는 내용 사실 검토를 대신하지 않습니다.
- preview: 로컬 HTML을 저장합니다. 이 미리보기는 이전 단순 스타일을 쓰므로 공개 페이지의 최신 스타일과 완전히 같지 않습니다. 실제 공개 후 레이아웃도 확인하세요.
- upload: WordPress 초안을 저장합니다. 글이 공개되지는 않습니다.
- approve: 운영자가 수행한 사실·스타일·권리·링크 검토의 완료를 기록합니다. 자동으로 기사 내용을 검토하는 명령이 아닙니다.
- publish: 승인 해시와 원고 ID가 일치할 때 공개합니다. 원고를 변경하면 다시 검토해야 합니다.

`--confirm`은 JSON의 id 값이며 파일명이나 WordPress 글 숫자 ID가 아닙니다. 수동 명령은 자동화의 하루 1편 제한을 적용하지 않습니다. 추가 글에는 기존 글과 다른 고유 ID를 쓰고 복구 중에는 새 ID를 만들지 마세요.

### 예약 발행

```bash
.venv/bin/python blog.py publish articles/manual-extra.json \
  --confirm manual-extra-2026-10-06 --at "YYYY-MM-DDT09:00:00+09:00"
```

실제 미래 시각으로 교체하세요. 과거 시각은 차단합니다. 서버에 예약 저장이 성공하면 이후 공개 시점은 WordPress가 처리하며 원고 작성 자동화와 별개의 기능입니다. 반환 상태는 future이며 이미 공개했다고 표현하면 안 됩니다.

## 자동 원고 파이프라인

```bash
.venv/bin/python app_runner.py prepare
```

이 명령은 조사 지침과 파일 경로를 반환합니다. AI 작성을 직접 실행하지 않습니다. Codex가 후보·원문·원고·검토 기록을 준비한 뒤:

```bash
.venv/bin/python app_runner.py finalize \
  articles/it-news-YYYY-MM-DD-draft.json \
  articles/it-news-YYYY-MM-DD-review.json
```

같은 날짜의 재실행은 이미 발행된 글을 재사용합니다. 수동 추가 글에는 이 경로를 사용하지 마세요.

## 기타 명령

| 명령 | 용도와 범위 |
|---|---|
| news | 등록된 공식 RSS 후보 수집. 광범위한 10개 주제 조사 대체 아님 |
| brief | 후보에서 미검증 원고 틀 생성. 그대로 업로드 불가 |
| compose | 검증된 evidence JSON으로 원고 조립. AI 조사·작성 아님 |
| auth | OAuth 인증 및 로컬 토큰 저장 |

```bash
.venv/bin/python blog.py news --days 7
.venv/bin/python blog.py compose articles/evidence.example.json \
  --output articles/my-composed-draft.json
```

예시 evidence는 역사적 자료라 최신 뉴스 검사에서 날짜 제한으로 거절될 수 있습니다. compose에도 실제 근거와 날짜를 새로 확인해 넣어야 합니다.

## 지원되지 않는 가정

- Python만 실행하면 AI가 현재 기준으로 원고까지 완성한다는 가정
- 예전 run_scheduled.py가 현재 앱 자동화와 동등하다는 가정
- GitHub에 올리면 Codex 자동화가 자동 등록된다는 가정
- 테스트 통과가 원고의 모든 사실을 보증한다는 가정
