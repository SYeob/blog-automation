#!/usr/bin/env python3
"""Python 3.9+: WordPress.com OAuth + one draft. Requires python-dotenv.

Client Secret may be stored as plaintext in the script-adjacent .env.
Existing environment variables take precedence. Access tokens are not saved.
Run on your own computer: python3 wordpress_draft_test.py
Registered redirect URI must be http://localhost:8080/callback/
"""
import getpass
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parent / ".env"
DEFAULT_CLIENT_ID = "149833"
SITE = "syeob.wordpress.com"
REDIRECT = "http://localhost:8080/callback/"
BASE = "https://public-api.wordpress.com"
SLUG = "yeob-api-draft-connection-test"


def load_credentials():
    load_dotenv(dotenv_path=ENV_FILE, override=False)
    client_id = os.environ.get("WP_CLIENT_ID", DEFAULT_CLIENT_ID).strip()
    if not client_id:
        raise RuntimeError("WP_CLIENT_ID가 비어 있습니다.")
    secret = os.environ.get("WP_CLIENT_SECRET", "").strip()
    if not secret:
        if not sys.stdin.isatty():
            raise RuntimeError("WP_CLIENT_SECRET이 없습니다. 프로젝트 .env 또는 환경변수에 설정하세요.")
        secret = getpass.getpass("WordPress 앱의 Client Secret을 붙여넣고 Enter: ").strip()
    if not secret:
        raise RuntimeError("Client Secret이 비어 있습니다.")
    return client_id, secret


def request_json(url, data=None, token=None):
    headers = {"Accept": "application/json", "User-Agent": "YeobDraftTest/1.0"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not print response bodies: authentication errors may contain secrets.
        raise RuntimeError("WordPress API HTTP 오류: " + str(exc.code)) from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("네트워크 오류입니다. 글 목록을 확인한 뒤 다시 실행하세요.") from None


def authenticate(return_response=False):
    client_id, secret = load_credentials()
    state = secrets.token_urlsafe(32)
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log callback URLs containing authorization codes.

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            valid = (parsed.path == "/callback/" and
                     secrets.compare_digest(query.get("state", [""])[0], state))
            if not valid:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Invalid callback. Return to the terminal.")
                return
            if "error" in query:
                result["error"] = True
            elif query.get("code"):
                result["code"] = query["code"][0]
            else:
                self.send_response(400)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write("인증 응답을 받았습니다. 터미널로 돌아가세요. 이 창은 닫아도 됩니다.".encode())

    try:
        server = HTTPServer(("127.0.0.1", 8080), Callback)
    except OSError:
        raise RuntimeError("8080 포트가 사용 중입니다. 해당 프로그램을 종료하고 다시 실행하세요.") from None
    with server:
        url = BASE + "/oauth2/authorize?" + urllib.parse.urlencode({
            "client_id": client_id, "redirect_uri": REDIRECT,
            "response_type": "code", "blog": SITE, "state": state,
        })
        print("\n브라우저에서 syeob.wordpress.com 접근 권한을 확인하고 승인해 주세요.")
        print("브라우저가 열리지 않으면 아래 주소를 직접 여세요:\n" + url)
        webbrowser.open(url)
        server.timeout = 1
        deadline = time.monotonic() + 300
        while not result and time.monotonic() < deadline:
            server.handle_request()
        if result.get("error"):
            raise RuntimeError("인증이 거절되었습니다. 글은 생성하지 않았습니다.")
        if not result.get("code"):
            raise RuntimeError("인증 대기 시간이 지났습니다. 다시 실행해 주세요.")
        response = request_json(BASE + "/oauth2/token", {
            "client_id": client_id, "client_secret": secret,
            "redirect_uri": REDIRECT, "code": result["code"],
            "grant_type": "authorization_code",
        })
        token = response.get("access_token")
        if not token:
            raise RuntimeError("인증 토큰을 받지 못했습니다.")
        return response if return_response else token


def main():
    print("대상: " + SITE)
    print("테스트 글 1편을 초안으로 저장합니다. 공개 발행하지 않습니다.")
    print("설정은 환경변수 → 스크립트 폴더의 .env 순으로 읽습니다.")
    print("Secret이 없으면 대화형 실행에서만 숨김 입력을 요청합니다.")
    token = authenticate()
    root = BASE + "/rest/v1.1/sites/" + SITE
    site = request_json(root, token=token)
    if urllib.parse.urlsplit(site.get("URL", "")).hostname != SITE:
        raise RuntimeError("대상 사이트 확인에 실패했습니다. 작업을 중단합니다.")
    existing = request_json(root + "/posts/?" + urllib.parse.urlencode({
        "slug": SLUG, "status": "any", "number": 10,
    }), token=token)
    for post in existing.get("posts", []):
        if post.get("slug") == SLUG:
            print("이미 테스트 글이 있습니다. 중복 생성하지 않았습니다.")
            print("글 ID:", post.get("ID"), "상태:", post.get("status"))
            return
    print("인증 성공. 테스트 초안을 저장합니다.")
    post = request_json(root + "/posts/new", {
        "title": "[연결 테스트] 자동 포스팅 초안 저장",
        "content": "<p>WordPress.com API로 저장한 테스트 초안입니다.</p>"
                   "<p>한글 본문과 초안 저장이 정상적으로 동작하는지 확인합니다.</p>",
        "status": "draft", "slug": SLUG,
    }, token=token)
    post_id = post.get("ID")
    if not post_id:
        raise RuntimeError("저장 결과가 불명확합니다. 관리자 글 목록을 확인해 주세요.")
    verified = request_json(root + "/posts/" + str(post_id), token=token)
    if verified.get("status") != "draft":
        raise RuntimeError("반환된 상태가 draft가 아닙니다. 관리자에서 확인해 주세요.")
    print("성공: 테스트 글이 초안으로 저장된 것을 재확인했습니다.")
    print("글 ID:", post_id)
    print("관리자 → 글 → 임시글(초안)에서 확인해 주세요.")
    print("액세스 토큰은 파일에 저장하지 않았습니다. .env의 Secret은 평문 설정입니다.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n사용자가 작업을 중단했습니다.")
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            print("\n오류:", str(exc))
        else:
            print("\n오류 유형:", type(exc).__name__, "— 비밀값 보호를 위해 상세 응답은 생략합니다.")
        raise SystemExit(1)
