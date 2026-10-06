# GitHub 공개 및 업로드 안내

## 무엇을 올리나요?

제공된 github-ready 폴더의 내용이 공개 배포본입니다. 운영 폴더 전체를 그대로 업로드하지 마세요.

포함: Python 소스, requirements.txt, 테스트, README·설명서, 빈 .env.example, 일반화한 발행 정책, 주제 기준, 자동화 프롬프트 예시, 필요한 역사적 테스트 자료와 직접 제작 도표.

제외: .env, .secrets, WordPress 토큰, state, data, 로그, 가상환경, 개인 원고·사진, 실제 앱 자동화 설정, 컴퓨터의 개인 실행 경로.

.gitignore는 새로 추가되는 로컬 인증과 운영 원고를 제외합니다. 이미 Git에 등록된 파일을 자동으로 삭제하거나 과거 커밋에서 비밀을 제거하지는 않습니다.

## 업로드

아래 명령은 공개 배포본 폴더에서 실행합니다. YOUR_ACCOUNT와 YOUR_REPOSITORY는 실제 값으로 바꾸세요. 새로 만든 빈 저장소에 처음 업로드할 때의 절차입니다.

```bash
git init -b main
git status --short --untracked-files=all
git add .
git diff --cached --name-only
git diff --cached
```

위 목록과 내용을 확인한 뒤:

```bash
git commit -m "Document Codex and Python WordPress workflow"
git remote add origin https://github.com/YOUR_ACCOUNT/YOUR_REPOSITORY.git
git push -u origin main
```

GitHub에 빈 저장소를 만든 경우의 예시입니다. 기존 저장소에 올릴 때는 기존 브랜치와 이력을 확인하고 force push하지 마세요. git commit에서 사용자 이름·이메일 설정이 필요할 수 있습니다. 본인의 GitHub 인증 방식을 사용하고 토큰을 URL에 넣지 마세요.

GitHub 웹 업로드를 사용한다면 ZIP 자체 대신 압축을 풀어 내부 파일을 올리세요. 숨김 파일 .gitignore와 .env.example도 포함해야 합니다. 실제 .env는 포함하지 않습니다.

## 게시 전 확인

- .env.example의 Secret과 Token 값이 비어 있는지
- .secrets, state, 로그, 가상환경이 목록에 없는지
- 개인 파일 경로·비공개 원고·무단 외부 이미지가 없는지
- 대상 블로그 상수가 공개된 데모 주소라는 점을 README가 설명하는지
- 테스트 67개가 통과하는지

공개 Client ID와 기본 블로그 주소는 비밀 토큰이 아니며 소스에 기본값으로 남아 있습니다. 사용하는 사람은 자신의 사이트와 OAuth 앱을 설정해야 합니다.

## 라이선스

프로젝트 공개 라이선스는 아직 지정하지 않았습니다. README 공개와 다른 사람의 코드 재사용 허용 범위는 별개입니다. 운영자가 MIT, Apache-2.0 등 원하는 라이선스를 결정하면 LICENSE를 추가할 수 있습니다. 외부 이미지 이용 조건은 소스 코드 라이선스와 별도로 확인합니다.

## 저장소를 복제하면 자동화도 생기나요?

아닙니다. GitHub에는 코드와 문서만 있습니다. 각 사용자 컴퓨터에서 WordPress 인증, 사이트 설정, Codex 앱 자동화 등록을 해야 합니다. 예약 예시 프롬프트의 PROJECT_DIR와 블로그 주소를 자신의 값으로 수정하세요.
