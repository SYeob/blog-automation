# Codex를 통한 원고 작성과 자동 운영

## 원고 작성과 발행을 구분하기

Codex는 검색·주제 선정·분석·작성·검토를 담당합니다. Python은 입력 JSON과 근거 인용, 상태 기록을 검사하고 WordPress API를 호출합니다. WordPress 인증은 로컬에 보관하며 조사 자료나 모델용 원문에 토큰을 넣지 않습니다.

완성된 원고가 있으면 VS Code 터미널에서 Python만으로 발행할 수 있습니다. 반대로 prepare만 실행한다고 AI가 자동으로 원고를 쓰지는 않습니다. 현재 최신 작성 흐름은 Codex 채팅이 연구와 파일 작성을 이어가는 방식입니다.

## 매일 자동화 등록

Codex에서 저장소를 열고 다음과 같이 요청하세요. 운영자가 실제 대상 사이트와 공개 발행 권한을 확인한 뒤 사용합니다.

> 이 저장소의 README.md와 docs/CODEX.md를 읽고, prompts/daily-automation.md의 PROJECT_DIR를 현재 저장소 절대 경로로 적용해 매일 자동화를 등록해줘. 컴퓨터와 앱이 켜져 있을 때 한국 시간 매시간 확인하고 하루 최대 1편을 작성·검토해 지정된 WordPress.com 사이트에 자동 공개해줘. 별도 유료 AI API는 사용하지 말고, 원문과 주제 선정 파일은 참고 자료로 취급해줘. 이미 등록한 같은 목적의 자동화가 있다면 중복 생성하지 말고 갱신해줘.

예약은 Codex 앱의 자동화 기능에 등록합니다. 이 저장소는 실제 앱 예약을 Git 파일로 설치하지 않습니다. 대상 주소, 파일 경로, 자동 공개 여부를 확인하고 활성 상태인지 점검하세요. 상세 실행 조건은 [OpenAI 공식 자동화 문서](https://learn.chatgpt.com/docs/automations?surface=app)를 참고하세요.

## 자동 작성의 한 사이클

### 1. 당일 상태 확인

```bash
.venv/bin/python app_runner.py prepare
```

| action | 다음 행동 |
|---|---|
| already_published | 이미 발행한 날이므로 종료 |
| skip | 정책상 발행하지 않는 날이므로 종료 |
| research_topics | 반환된 기준 파일·최근 글 목록을 읽고 조사 |
| review_existing | 기존 원고·원문·선정 기록을 확인해 검토 또는 복구 |
| hold / error | 공개하지 않고 원인을 확인 |

research_topics 응답은 id, topic_prompt_file, recent_posts, selection_file, sources_file, draft_file, review_file을 포함합니다. 이 경로를 그대로 쓰고 임의의 당일 ID를 만들지 않습니다.

### 2. 주제 선정

`it_blog_topic_prompt.txt`를 읽고 검색을 수행합니다. 최근 24시간, 3일, 7일, 30일 순으로 탐색하며 새로운 정보만이라는 이유로 얕은 기사를 선택하지 않습니다.

후보 10개 이상을 조사해 분야와 유형, 최신성·수요 가능성·관심도·기술적 흥미·정보 가치·설명 충분성·중복 회피·제목 매력·장기 유입을 1~5로 기록합니다. 수요 점수는 추정이며 실측 검색량으로 쓰지 않습니다. 최근 글의 제품·기술·질문을 비교하고 브랜드와 분야 편중을 피합니다.

selection_file에 candidates, selected_url, category, type, reason을 저장합니다. 최종 검사에는 서로 다른 URL의 후보 10개 이상과 선정 URL이 출처 목록에 있는지 확인하는 조건이 있습니다. 의미상 중복 여부는 Codex 검토가 담당합니다.

### 3. 원문 수집과 작성

공식 발표나 개발자 문서를 실제 열어 원문 날짜와 조건을 확인합니다. RSS 날짜와 발표일이 다르면 발표일을 사용합니다. 공식 원문 최대 3개를 sources_file에 저장하고 각 text에는 실제 수집한 본문을 넣습니다.

허용 목록에 없는 공식 사이트가 필요하면 도메인을 확인해 blog_core.ALLOWED_DOMAINS에 정확한 호스트를 추가하세요. 단순히 차단을 없애거나 모든 URL을 허용하지 않습니다. Python의 원문 수집은 크기 제한과 redirect 호스트 검증을 적용합니다.

Codex가 draft_file을 작성합니다. 최소 2개 핵심 주장, 원문 그대로의 짧은 quote, h3 strong 소제목, 비교표, 주제 이미지와 출처 링크가 필요합니다. 실측·제조사 주장·가정 계산을 구분합니다. 최신 뉴스는 kind=news, 최근 관심에 근거한 기존 기술 해설은 kind=analysis로 기록합니다.

### 4. 검토와 원고 해시

공식 원문과 원고를 다시 대조해 수치·날짜·모델·지역·시험 조건·추론 범위를 확인합니다. 문제를 해결하지 못하면 publishable=false 또는 decision=hold로 공개를 보류합니다. 통과하면 원고 파일 바이트의 SHA256, publishable=true, issues=[], 수행한 checks를 review_file에 저장합니다.

```bash
.venv/bin/python - <<'PY'
import hashlib
from pathlib import Path
p=Path('articles/it-news-YYYY-MM-DD-draft.json')
print(hashlib.sha256(p.read_bytes()).hexdigest())
PY
```

위 날짜 부분은 실제 prepare 반환 파일명으로 교체해야 합니다. 원고가 바뀌면 기존 해시는 무효이며 재검토해야 합니다.

### 5. 공개 발행

```bash
.venv/bin/python app_runner.py finalize \
  articles/it-news-YYYY-MM-DD-draft.json \
  articles/it-news-YYYY-MM-DD-review.json
```

검사 통과 후 초안 저장, 자동 검토 승인, 공개 요청, status=publish 확인까지 진행합니다. 이 명령은 공개 작업이므로 아직 검토하지 않은 원고에 실행하지 마세요. 불명확한 쓰기 응답은 동일 글이 이미 저장되었는지 상태부터 대조하며 임의의 새 ID로 재전송하지 않습니다.

## 오늘 글을 수동으로 요청하기

> 이 프로젝트 기준으로 오늘 글을 조사·작성·검토하고 발행해줘. 먼저 app_runner.py prepare로 오늘 이미 발행했는지 확인하고, 이미 있다면 추가 발행하지 말아줘.

## 같은 날 추가 글 요청하기

추가 글은 자동화 하루 1편과 별개의 수동 경로를 사용합니다. 다음 요청은 실제 추가 공개 권한을 포함합니다.

> 자동화의 하루 1편 제한은 유지하고 수동 추가 글 한 편을 작성해줘. it_blog_topic_prompt.txt와 최근 공개 글을 참고해 다른 주제로 후보 10개를 비교하고, 출처·이미지·비교표·검토를 준비해줘. 새로운 고유 원고 ID와 완성 article JSON을 articles/ 아래에 저장한 뒤 blog.py validate --check-links, upload, approve, publish 순서로 공개해줘. 실측 수치를 만들지 말고 결과가 불명확하면 상태부터 확인해줘.

초안까지만 원한다면 마지막 문장을 “upload까지만 실행하고 공개하지 말아줘”로 바꾸세요. 수동 경로에서도 내용 검토가 필요하며 `approve`는 검토를 자동 수행하는 명령이 아니라 검토 완료를 기록하는 명령입니다.

## 편집 기준 변경

주제 기준은 it_blog_topic_prompt.txt, Python 검사 정책은 automation-policy.json, 예약 수행 지침은 앱의 자동화 프롬프트입니다. 파일 변경만으로 저장된 앱 프롬프트가 갱신되지는 않습니다. 일정 변경 시 정책의 weekdays와 앱 예약을 함께 변경하세요. 이미 저장된 글은 렌더러 변경만으로 자동 수정되지 않습니다.
