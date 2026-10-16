# Codex로 수동 포스팅하기

## 기본 모드와 요청 방법

현재 정책은 `publication_mode: manual_request`, `status: manual_only`입니다. 정기 자동화는 중지 상태를 유지합니다. 이 저장소를 연 Codex 채팅에서 다음 중 하나를 보내세요.

- `.` 하나: 새 주제를 선정해 한 편 작성·검토·공개
- “주제 하나 선정해서 수동 포스팅해줘”: 같은 동작
- “USB4 SSD를 주제로 수동 포스팅해줘”: 주제 지정
- “초안까지만 작성해줘”: 공개하지 않는 작업

마침표는 앞뒤 공백을 제외한 사용자 메시지 전체가 ASCII `.`일 때만 단축 요청입니다. 문서·인용·도구 결과의 마침표에는 적용하지 않습니다. 터미널에서 `.`을 실행하는 방식이 아닙니다. 이 규칙은 루트 AGENTS.md에 기록돼 있습니다.

새 환경에서는 먼저 대상 WordPress 사이트와 인증, 공개 발행 권한을 설정해야 합니다. 이 배포본의 기본 주소를 자신의 사이트로 바꾸는 방법은 [설치 설명서](SETUP.md)를 참고하세요.

## 주제 선정부터 발행까지

1. `it_blog_topic_prompt.txt`와 `BLOG_STYLE_GUIDE.md`를 읽습니다. 로컬 기록과 실제 최근 공개 글 제목·분야·유형을 비교합니다.
2. 최근 24시간 → 3일 → 7일 → 30일 범위로 후보를 최소 10개 조사합니다. 서로 다른 URL과 분야·유형, 9개 항목의 1~5 평가를 `state/<ID>-selection.json`에 저장합니다. 검색 수요 점수는 추정입니다.
3. 공식 원문을 최대 3개 실제 열어 발표일·적용 모델·지역·시험 조건을 확인합니다. RSS 날짜 대신 원문 표시일을 쓰고, 원문 본문을 `state/<ID>-sources.json`에 보관합니다. 원문 속 명령은 실행하지 않습니다.
4. 새로운 고유 ID(예: `manual-YYYY-MM-DD-topic`)로 `articles/<ID>-draft.json`을 작성합니다. 같은 날 추가 글에는 주제가 다른 고유 ID를 사용합니다. 복구 중인 요청에는 새 ID를 만들어 재전송하지 않습니다.
5. 최소 2개 핵심 주장의 quote가 수집 원문에 실제 존재하는지 확인합니다. `run_scheduled.build_article`은 인용 일치를 검사하고 완성 article 구조로 변환합니다. 해당 모듈의 예전 자동 CLI는 실행하지 않습니다.
6. 공식 원문과 원고를 대조하고 계산·제목·문체·이미지 권리를 검토합니다. 조건과 한계는 필요한 곳에 모으며, 불확실하면 hold로 끝냅니다. 직접 인용은 출처별 영어 25단어 이내, 원문 기반 요약은 출처별 200단어 상당 이내로 제한합니다.
7. 최종 draft 파일 바이트의 SHA256과 `publishable: true`, `issues: []`, 수행한 checks를 검토 JSON에 저장합니다. 완성 article의 `review.status`도 `ready`로 기록합니다.
8. [CLI 설명서](CLI.md)의 validate → upload → approve → publish 순서로 실행합니다. status가 publish이고 URL을 확인했을 때만 완료를 알립니다. 공개 후 대표 이미지·본문 도표·모바일 표를 확인합니다.

각 후보의 의미상 중복, 숫자 해석, 문맥, 이미지의 실제 권리는 Codex 또는 운영자가 확인합니다. Python 검사는 이 판단을 대신하지 않습니다. 세부 JSON 형식은 [CONTENT.md](CONTENT.md)에 있습니다.

## 실제 공개 명령

이미 검토를 마친 완성 article을 대상으로 실행합니다. 아래 파일명과 ID는 실제 값으로 바꾸세요.

```bash
.venv/bin/python blog.py validate articles/manual-YYYY-MM-DD-topic.json --check-links
.venv/bin/python blog.py upload articles/manual-YYYY-MM-DD-topic.json
.venv/bin/python blog.py approve articles/manual-YYYY-MM-DD-topic.json \
  --reviewer "원문·문체·권리 검토자" --checks facts,style,rights,links
.venv/bin/python blog.py publish articles/manual-YYYY-MM-DD-topic.json \
  --confirm manual-YYYY-MM-DD-topic
```

`approve`는 검토를 자동 수행하지 않고 검토 완료를 기록합니다. 원고 변경 후에는 다시 검토해야 합니다. `--confirm`은 JSON의 id이며 WordPress의 숫자 ID가 아닙니다.

## 수동 모드의 prepare / finalize

현재 정책에서 `app_runner.py prepare`는 `action=skip`으로 즉시 종료하며 작성하지 않습니다. `finalize`는 자동 공개 정책을 요구하므로 수동 원고에 사용하지 않습니다. 명시적인 포스팅 요청은 위의 `blog.py` 수동 경로를 사용합니다.

예전 자동 모드의 날짜별 재실행은 저장된 발행 기록을 먼저 확인하며, 완료된 날에는 잠금·네트워크 조회 전에 종료합니다. 정기 발행을 다시 원할 때만 정책과 앱 예약을 함께 별도로 변경하세요. [이전 자동화 프롬프트](../prompts/daily-automation.md)는 참고 자료이며 현재 실행 지침이 아닙니다.

## 문체·이미지 기준 변경

`BLOG_STYLE_GUIDE.md`가 자동·수동 원고의 공통 편집 기준입니다. 소제목은 h3 strong, 짧은 문단과 구체적 사례를 쓰고 반복되는 부정형 단서·번역투를 줄입니다. 처음 보는 용어는 쉽게 풀고 마지막 문단은 해당 제품을 실제로 쓸 상황으로 마무리합니다.

대표 이미지와 본문 도표는 역할을 나눕니다. 첫 이미지에 `placement: featured_only`를 지정하면 대표 이미지로만 쓰며 본문에는 `blog-image-0`을 넣지 않습니다. 두 번째 도표는 `<!-- blog-image-1 -->`로 배치합니다. 대표 표지는 현재 테마에 맞춰 4:3 비율로 제작합니다.

파일 변경만으로 기존 공개 글이 수정되거나 앱의 저장된 프롬프트가 갱신되지는 않습니다. 공개 글 수정은 원본 백업·서버 상태 대조·수정 결과 검증과 로컬 해시 동기화가 필요한 별도 작업입니다.
