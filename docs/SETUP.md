# 설치와 WordPress 인증

## 1. 로컬 환경

VS Code에서 저장소 폴더를 열고 통합 터미널을 실행합니다. 모든 명령은 저장소 루트 기준입니다. Python 3.9 이상을 사용하고 가능하면 3.11 이상을 선택하세요.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

기존 운영 폴더에서 실행 중이면 새 가상환경이나 `.env`를 덮어쓰지 말고 기존 파일을 사용하세요.

## 2. 대상 블로그

현재 사이트 주소는 환경변수로 바뀌지 않습니다. 다른 WordPress.com 사이트를 대상으로 운영한다면 다음 두 파일의 SITE 값을 동일하게 수정하세요.

- `blog_core.py`: `SITE = 'your-site.wordpress.com'`
- `wordpress_draft_test.py`: `SITE = "your-site.wordpress.com"`

`blog_core.py`의 BASE와 허용 출처 목록에는 SITE 값이 반영됩니다. 자동화 프롬프트의 사이트 주소도 같은 값으로 바꾸세요. 다른 사이트로 옮길 때 기존 토큰과 상태 파일을 재사용하지 말고 별도의 폴더에서 재인증하세요.

## 3. OAuth 앱 등록과 .env

WordPress.com의 OAuth 애플리케이션을 준비하고 등록된 redirect URI를 `http://localhost:8080/callback/`로 맞춥니다. Client ID와 Client Secret은 본인의 앱 값을 사용합니다. [WordPress OAuth 공식 문서](https://developer.wordpress.com/docs/oauth2/)

```dotenv
WP_CLIENT_ID=본인의_Client_ID
WP_CLIENT_SECRET=본인의_Client_Secret
```

`.env.example`은 공개용 빈 설정입니다. `.env`는 Git에 포함하지 않습니다. 코드에는 기존 개발 Client ID 기본값이 남아 있으므로 `.env`의 WP_CLIENT_ID를 명시하는 것이 필요합니다. Client ID는 비밀 토큰이 아니지만 타인의 앱과 본인의 Secret을 섞지 마세요.

선택적으로 WP_ACCESS_TOKEN 환경변수를 제공할 수 있습니다. 이 경우 로컬 토큰 파일보다 우선합니다. 셸 명령에 토큰을 직접 적거나 로그에 출력하지 마세요.

## 4. 인증과 확인

```bash
.venv/bin/python blog.py auth
.venv/bin/python blog.py doctor
.venv/bin/python blog.py categories
```

auth는 브라우저에서 WordPress에 로그인하고 지정한 사이트 접근을 승인하는 절차입니다. 로컬 callback 서버가 8080 포트를 사용합니다. 포트 충돌이면 해당 포트의 프로그램을 정리하고 재실행하세요.

토큰은 `.secrets/wordpress-token.json`에 저장됩니다. 디렉터리는 700, 파일은 600 권한을 적용합니다. 파일 내용은 평문이므로 인증 파일을 공유하지 마세요. 자동 갱신은 가정하지 않으며 만료 시 재인증합니다.

원고의 category는 실제 WordPress 카테고리 이름과 정확히 일치해야 합니다. 자동 원고의 기본 이름은 `IT 소식·분석`이며, WordPress 관리자에서 같은 카테고리를 준비하거나 `run_scheduled.build_article`의 이름을 본인의 카테고리로 변경하세요.

## 5. 수동 요청 정책

`automation-policy.json`의 기본 모드는 manual_request / manual_only입니다. 정기 자동화는 등록하지 않으며 사용자 요청에 따라 blog.py 수동 경로로 발행합니다.

Codex에서 이 저장소를 열고 [Codex 사용법](CODEX.md)에 따라 수동 포스팅을 요청하세요. 루트 AGENTS.md의 마침표 단축 요청도 적용할 수 있습니다. 새 저장소에는 기존 예약 작업이나 인증 정보가 포함되지 않습니다.
