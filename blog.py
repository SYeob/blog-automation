#!/usr/bin/env python3
"""Korean IT blog workflow. Run --help for commands."""
import argparse
import html
import json
from pathlib import Path
import sys

from blog_core import (ROOT, SITE, TOKEN_FILE, AuthError, Store, WordPress, Workflow,
                       WorkflowError, article_hash, atomic_json, locked, load_token,
                       now, read_json, save_token, validate_article)
import news_sources
import article_writer
import automation_guard
import wordpress_draft_test


def parser():
    p = argparse.ArgumentParser(description='WordPress.com IT 블로그: 기본 초안, 검토 후 명시적 발행')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('auth', help='브라우저 OAuth 인증 후 토큰을 로컬 비밀 파일에 저장')
    sub.add_parser('doctor', help='인증과 사이트 연결 상태 확인')
    sub.add_parser('categories', help='실제 카테고리 ID·이름·슬러그 조회')
    sub.add_parser('status', help='원고별 로컬 처리 상태 확인')
    n = sub.add_parser('news', help='공식 RSS/Atom에서 최근 뉴스 후보 수집')
    n.add_argument('--providers', default='samsung,apple,playstation,google,microsoft')
    n.add_argument('--days', type=int, choices=range(1,15), default=14, metavar='1..14')
    n.add_argument('--output', type=Path, default=ROOT / 'data' / 'news-candidates.json')
    b = sub.add_parser('brief', help='뉴스 후보에서 검토용 원고 틀 생성')
    b.add_argument('candidate_id')
    b.add_argument('--id', required=True)
    b.add_argument('--candidates', type=Path, default=ROOT / 'data' / 'news-candidates.json')
    b.add_argument('--output', type=Path, required=True)
    comp = sub.add_parser('compose', help='검증된 근거 패킷을 한국어 구조의 원고로 조립 (유료 API 없음)')
    comp.add_argument('evidence', type=Path)
    comp.add_argument('--output', type=Path, required=True)
    for name, description in [('validate','원고·근거·HTML·이미지 권리 검사'), ('preview','로컬 HTML 미리보기'), ('upload','원고를 초안으로 저장 또는 기존 초안 재사용'), ('approve','검토한 초안과 원고 해시에 승인 기록'), ('publish','검토 승인된 초안만 공개 발행 또는 예약')]:
        cmd = sub.add_parser(name, help=description)
        cmd.add_argument('article', type=Path)
        if name == 'validate':
            cmd.add_argument('--check-links', action='store_true', help='출처 URL의 네트워크 조회까지 검사')
        if name == 'preview':
            cmd.add_argument('--output', type=Path)
        if name == 'approve':
            cmd.add_argument('--reviewer', required=True)
            cmd.add_argument('--checks', required=True, help='facts,style,rights,links')
        if name == 'publish':
            cmd.add_argument('--automated', action='store_true', help='자동 운영 정책·실행 요일·당일 원고 검사')
            cmd.add_argument('--confirm', required=True, help='발행할 원고 id를 정확히 입력')
            cmd.add_argument('--at', help='예: 2026-10-06T09:00:00+09:00 (Asia/Seoul)')
    return p


def api():
    return WordPress(load_token())


def article_file(path):
    return read_json(path), Path(path).resolve().parent


def preview(article, base_dir, output):
    validate_article(article, base_dir, check_fresh=False)
    body = article['content_html']
    for image in article.get('images', []):
        from blog_core import resolve_image
        uri = resolve_image(base_dir, image['path']).as_uri()
        body += '<figure><img src="' + html.escape(uri, quote=True) + '" alt="' + html.escape(image['alt'], quote=True) + '"><figcaption>' + html.escape(image['caption'] + ' ' + image.get('attribution', '')) + '</figcaption></figure>'
    document = '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + html.escape(article['title']) + '</title><style>body{max-width:780px;margin:48px auto;padding:0 24px;color:#202730;font:17px/1.85 system-ui,sans-serif}h1{font-size:32px;line-height:1.45}h2{margin-top:36px;font-size:24px}table{width:100%;border-collapse:collapse;font-size:15px}th,td{border:1px solid #ccd3db;padding:12px;text-align:left}th{background:#f0f3f7}a{color:#1757b8}img{max-width:100%}.meta{color:#647080;font-size:14px}code{background:#eef2f6;padding:2px 5px}figcaption{font-size:14px;color:#647080}</style><h1>' + html.escape(article['title']) + '</h1><p class="meta">공개 자료 기반 분석 · 초안 · 검토 필요</p>' + body + '</html>'
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding='utf-8')
    print('미리보기 저장:', output)


def run(args):
    if args.command == 'auth':
        with locked():
            response = wordpress_draft_test.authenticate(return_response=True)
            client = WordPress(response['access_token'])
            site = client.verify_site()
            if response.get('blog_id') and int(response['blog_id']) != int(site['ID']):
                raise AuthError('발급 토큰의 사이트가 대상 사이트와 다릅니다.')
            metadata = save_token(response)
            print('인증 성공. 토큰은 .secrets/wordpress-token.json에 권한 600으로 평문 저장했습니다.')
            print('응답에 유효기간 있음:', bool(metadata['expires_at']), '/ refresh token 있음:', metadata['has_refresh_token'])
            print('만료·권한 오류 시 재인증하며, 자동 갱신 지원을 가정하지 않습니다.')
        return
    if args.command == 'news':
        names = args.providers.split(',')
        if any(n not in news_sources.FEEDS for n in names):
            raise WorkflowError('뉴스 제공자는 samsung,apple,playstation,google,microsoft 중 선택하세요.')
        result = news_sources.collect(names, args.days)
        atomic_json(args.output, result)
        print('뉴스 후보:', len(result['candidates']), '개 / 조회 실패:', ','.join(result['failed_providers']) or '없음')
        print('저장:', args.output)
        for candidate in result['candidates'][:10]:
            print(candidate['id'], candidate['published_at'], candidate['title'])
        if not result['candidates']:
            raise WorkflowError('확인 가능한 최신 후보가 없습니다. 출처를 확인하세요.')
        return
    if args.command == 'brief':
        candidates = read_json(args.candidates)['candidates']
        choices = [c for c in candidates if c['id'] == args.candidate_id]
        if len(choices) != 1:
            raise WorkflowError('뉴스 후보 id를 확인하세요.')
        if args.output.exists():
            raise WorkflowError('기존 원고 파일을 덮어쓰지 않습니다. 다른 출력 경로를 사용하세요.')
        atomic_json(args.output, news_sources.brief(choices[0], args.id))
        print('검토용 원고 틀 저장:', args.output, '(미검증 상태이므로 업로드 불가)')
        return
    if args.command == 'compose':
        if args.output.exists():
            raise WorkflowError('기존 원고를 덮어쓰지 않습니다. 새 출력 경로를 사용하세요.')
        packet = read_json(args.evidence)
        if args.output.resolve().parent != args.evidence.resolve().parent and packet.get('images'):
            raise WorkflowError('이미지 경로를 보존하도록 근거 패킷과 같은 폴더에 출력하세요.')
        result = article_writer.compose(packet, args.evidence.resolve().parent)
        atomic_json(args.output, result)
        print('검증된 근거에서 원고 생성:', args.output, '/ 검토 필요')
        return
    if args.command == 'doctor':
        info = api().verify_site()
        print('WordPress 연결 정상 / 대상:', SITE, '/ 사이트 ID:', info['ID'])
        print('인증:', '환경변수 또는 로컬 토큰 파일', '/ 기본 업로드 상태: draft')
        return
    if args.command == 'categories':
        client = api()
        client.verify_site()
        result = client.categories()
        atomic_json(ROOT / 'data' / 'categories.json', result)
        for item in result:
            print(item['ID'], html.unescape(item['name']), '/', item['slug'])
        return
    if args.command == 'status':
        store = Store()
        for key, record in store.data['posts'].items():
            print(key, record['stage'], '글 ID:', record.get('post_id', '확인 중'), '검토 승인:', bool(record.get('approval')))
        if not store.data['posts']:
            print('아직 처리한 원고가 없습니다.')
        return
    article, base_dir = article_file(args.article)
    if args.command == 'validate':
        validate_article(article, base_dir)
        if args.check_links:
            from blog_core import CheckHTML, safe_url, ALLOWED_DOMAINS
            checker = CheckHTML()
            checker.feed(article['content_html'])
            for url in set(checker.links):
                safe_url(url, ALLOWED_DOMAINS)
                news_sources.fetch(url)
            print('공식 출처 링크 조회 통과 (사실 검증은 별도 검토 필요)')
        print('원고 구조·근거 매핑·HTML·권리 정보 검사 통과 / 내용 해시:', article_hash(article, base_dir)[:12])
        return
    if args.command == 'preview':
        preview(article, base_dir, args.output or args.article.with_suffix('.preview.html'))
        return
    with locked():
        workflow = Workflow(api(), Store())
        if args.command == 'upload':
            post, created = workflow.upload(article, base_dir)
            print('초안 저장·복구 완료' if created else '기존 게시물 재사용, 쓰기 요청 없음')
            print('글 ID:', post['ID'], '/ 상태:', post['status'])
        elif args.command == 'approve':
            workflow.approve(article, base_dir, args.reviewer, args.checks.split(','))
            print('검토 승인 기록 완료. 아직 공개 발행하지 않았습니다.')
        elif args.command == 'publish':
            if args.automated:
                automation_guard.publication_guard(article)
            post, changed = workflow.publish(article, base_dir, args.confirm, args.at)
            print('발행 상태 확인:', post['status'], '/ 글 ID:', post['ID'], '/ 새 요청:', changed)


def main():
    args = parser().parse_args()
    try:
        run(args)
    except KeyboardInterrupt:
        print('\n사용자가 중단했습니다. 다음 실행에서 상태 기록을 먼저 대조합니다.', file=sys.stderr)
        return 130
    except (WorkflowError, RuntimeError) as exc:
        print('오류:', str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print('오류 유형:', type(exc).__name__, '— 비밀값 보호를 위해 상세 응답을 생략합니다.', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
