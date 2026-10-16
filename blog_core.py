"""Small WordPress.com workflow; draft by default, no automatic POST retries."""
import contextlib
import datetime as dt
import fcntl
import hashlib
import html
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
SITE = 'syeob.wordpress.com'
BASE = 'https://public-api.wordpress.com/rest/v1.1/sites/' + SITE
KST = ZoneInfo('Asia/Seoul')
TOKEN_FILE = ROOT / '.secrets' / 'wordpress-token.json'
STATE_FILE = ROOT / 'state' / 'workflow.json'
ALLOWED_DOMAINS = {SITE, 'www.qualcomm.com', 'deepmind.google', 'support.google.com', 'blog.google', 'research.google', 'blogs.microsoft.com',
                   'news.microsoft.com', 'www.apple.com', 'developer.wordpress.com',
                   'github.blog', 'blogs.windows.com', 'www.microsoft.com', 'learn.microsoft.com', 'www.beatsbydre.com',
                   'www.hyundai.com', 'www.hyundai.news',  # Hyundai Europe links to this official newsroom.
                   'www.playstation.com',  # Official PlayStation hardware support.
                   'news.samsungsemiconductor.com', 'news.samsung.com', 'www.samsung.com',
                   'blog.playstation.com', 'www.garmin.com', 'www.garmin.com.sg', 'www8.garmin.com', 'www.nvidia.com', 'nvidia.custhelp.com', 'www.nintendo.com', 'www.kioxia.com', 'kr.kioxia.com'}

class WorkflowError(RuntimeError):
    pass

class UncertainWrite(WorkflowError):
    pass

class AuthError(WorkflowError):
    pass


def now():
    return dt.datetime.now(KST)


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(value).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tmp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as out:
            os.fchmod(out.fileno(), 0o600)
            json.dump(value, out, ensure_ascii=False, indent=2)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise WorkflowError('JSON 파일을 읽을 수 없습니다. 경로와 형식을 확인하세요.') from None


@contextlib.contextmanager
def locked(root=ROOT):
    directory = Path(root) / 'state'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.workflow.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise WorkflowError('다른 작업이 실행 중입니다. 완료 후 다시 실행하세요.') from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class Store:
    def __init__(self, path=STATE_FILE):
        self.path = Path(path)
        self.data = read_json(path) if self.path.exists() else {'version': 1, 'site': SITE, 'posts': {}, 'media': {}}
        if self.data.get('version') != 1 or self.data.get('site') != SITE:
            raise WorkflowError('상태 파일의 버전 또는 대상 사이트가 다릅니다.')

    def save(self):
        atomic_json(self.path, self.data)


def save_token(response, path=TOKEN_FILE):
    token = response.get('access_token')
    if not isinstance(token, str) or not token.strip():
        raise AuthError('인증 토큰을 받지 못했습니다.')
    record = {'access_token': token, 'site': SITE, 'saved_at': now().isoformat()}
    # Expiration comes only from the actual token response, never an assumption.
    expires = response.get('expires_in')
    if expires is not None:
        try:
            seconds = float(expires)
            if seconds > 0:
                record['expires_at'] = (now() + dt.timedelta(seconds=seconds)).isoformat()
        except (ValueError, TypeError, OverflowError):
            raise AuthError('토큰 유효기간 응답이 올바르지 않습니다.') from None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    atomic_json(path, record)
    return {'expires_at': record.get('expires_at'), 'has_refresh_token': bool(response.get('refresh_token'))}


def load_token(path=TOKEN_FILE):
    load_dotenv(ROOT / '.env', override=False)
    token = os.environ.get('WP_ACCESS_TOKEN', '').strip()
    if token:
        return token
    path = Path(path)
    if not path.exists():
        raise AuthError('인증이 필요합니다. blog.py auth를 먼저 실행하세요.')
    if path.stat().st_mode & 0o077:
        raise AuthError('토큰 파일 권한을 600으로 설정하세요.')
    record = read_json(path)
    if record.get('site') != SITE:
        raise AuthError('저장된 토큰의 대상 사이트가 다릅니다.')
    if record.get('expires_at'):
        try:
            if dt.datetime.fromisoformat(record['expires_at']) <= now():
                raise AuthError('토큰이 만료되었습니다. blog.py auth로 다시 인증하세요.')
        except (ValueError, TypeError):
            raise AuthError('토큰 유효기간을 확인할 수 없습니다. 다시 인증하세요.') from None
    if not record.get('access_token'):
        raise AuthError('토큰이 없습니다. 다시 인증하세요.')
    return record['access_token']


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class WordPress:
    def __init__(self, token):
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(self, path='', data=None, raw=None, content_type=None):
        url = BASE + path
        headers = {'Accept': 'application/json', 'User-Agent': 'YeobBlogAutomation/1.0',
                   'Authorization': 'Bearer ' + self.token}
        body = raw
        writing = data is not None or raw is not None
        if data is not None:
            body = urllib.parse.urlencode(data).encode()
            content_type = 'application/x-www-form-urlencoded'
        if content_type:
            headers['Content-Type'] = content_type
        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            with self.opener.open(req, timeout=30) as response:
                result = json.load(response)
                if not isinstance(result, dict):
                    raise ValueError()
                return result
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise AuthError('WordPress 인증 또는 권한 오류입니다. 재인증 후 다시 실행하세요.') from None
            if writing and exc.code >= 500:
                raise UncertainWrite('쓰기 응답이 불명확합니다. 상태를 대조하기 전에는 재전송하지 않습니다.') from None
            raise WorkflowError('WordPress API HTTP 오류: ' + str(exc.code)) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            if writing:
                raise UncertainWrite('쓰기 결과가 불명확합니다. 다시 실행해 실제 생성 여부를 먼저 대조하세요.') from None
            raise WorkflowError('WordPress 조회에 실패했습니다. 네트워크 상태를 확인하세요.') from None

    def verify_site(self):
        info = self.call()
        if urllib.parse.urlsplit(info.get('URL', '')).hostname != SITE:
            raise WorkflowError('대상 사이트 확인에 실패했습니다.')
        return info

    def categories(self):
        result = []
        for page in range(1, 101):
            batch = self.call('/categories/?' + urllib.parse.urlencode({'number': 1000, 'page': page}))['categories']
            result.extend(batch)
            if len(batch) < 1000:
                return result
        raise WorkflowError('카테고리 조회 범위를 초과했습니다.')

    def post(self, post_id):
        return self.call('/posts/' + str(int(post_id)) + '?context=edit')

    def find_post(self, slug):
        posts = self.call('/posts/?' + urllib.parse.urlencode({'slug': slug, 'status': 'any', 'number': 100, 'context': 'edit'})).get('posts', [])
        exact = [p for p in posts if p.get('slug') == slug]
        if len(exact) > 1:
            raise WorkflowError('동일한 원고 식별자가 여러 게시물에 있습니다. 관리자에서 확인하세요.')
        return exact[0] if exact else None

    def find_media(self, title):
        for page in range(1, 101):
            result = self.call('/media/?' + urllib.parse.urlencode({'search': title, 'number': 100, 'page': page, 'context': 'edit'}))
            batch = result.get('media', [])
            matches = [m for m in batch if html.unescape(m.get('title', '')) == title]
            if len(matches) > 1:
                raise WorkflowError('동일 해시의 미디어가 여러 개 있습니다. 관리자에서 확인하세요.')
            if matches:
                return matches[0]
            if len(batch) < 100:
                return None
        raise WorkflowError('미디어 조회 범위를 초과했습니다.')

    def upload_media(self, data, title, alt, caption):
        boundary = 'Yeob' + secrets.token_hex(16)
        parts = []
        for name, value in {'attrs[0][title]': title, 'attrs[0][alt]': alt, 'attrs[0][caption]': caption}.items():
            parts.append(('--' + boundary + '\r\nContent-Disposition: form-data; name="' + name + '"\r\n\r\n' + value + '\r\n').encode())
        parts.append(('--' + boundary + '\r\nContent-Disposition: form-data; name="media[]"; filename="' + title + '.jpg"\r\nContent-Type: image/jpeg\r\n\r\n').encode() + data + b'\r\n')
        parts.append(('--' + boundary + '--\r\n').encode())
        result = self.call('/media/new', raw=b''.join(parts), content_type='multipart/form-data; boundary=' + boundary)
        if result.get('errors') or result.get('media_errors') or len(result.get('media', [])) != 1:
            raise UncertainWrite('미디어 업로드 결과를 확인할 수 없습니다. 재실행 시 먼저 대조합니다.')
        return result['media'][0]


ALLOWED_TAGS = {'p', 'h2', 'h3', 'ul', 'ol', 'li', 'a', 'strong', 'em', 'code', 'pre',
                'blockquote', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'br', 'hr', 'figure', 'figcaption'}
VOID_TAGS = {'br', 'hr'}


def safe_url(value, allowed=None):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise WorkflowError('출처·링크는 사용자 인증 정보가 없는 HTTPS 주소여야 합니다.')
    if allowed is not None and parsed.hostname not in allowed:
        raise WorkflowError('허용된 공식 출처 도메인이 아닙니다.')
    return value


class CheckHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.links = []
        self.headings = 0

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS:
            raise WorkflowError('원고 HTML에 지원하지 않는 태그가 있습니다: ' + tag)
        allowed = {'href', 'title', 'rel'} if tag == 'a' else {'scope', 'colspan', 'rowspan'} if tag in {'th', 'td'} else set()
        for key, value in attrs:
            if key not in allowed or value is None:
                raise WorkflowError('허용되지 않은 HTML 속성이 있습니다.')
            if key == 'href':
                safe_url(value)
                self.links.append(value)
        if tag in {'h2','h3'}:
            self.headings += 1
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in VOID_TAGS or not self.stack or self.stack.pop() != tag:
            raise WorkflowError('HTML 태그의 열기·닫기가 일치하지 않습니다.')

    def handle_decl(self, decl):
        raise WorkflowError('원고에 HTML 문서 선언을 넣을 수 없습니다.')

    def handle_pi(self, data):
        raise WorkflowError('원고에 처리 명령을 넣을 수 없습니다.')


def date_value(value, label):
    try:
        return dt.date.fromisoformat(value)
    except (ValueError, TypeError):
        raise WorkflowError(label + ' 날짜는 YYYY-MM-DD 형식이어야 합니다.') from None


def validate_article(article, base_dir, check_fresh=True):
    if not isinstance(article, dict):
        raise WorkflowError('원고는 JSON 객체여야 합니다.')
    for key in ('id', 'title', 'content_html', 'category'):
        if not isinstance(article.get(key), str) or not article[key].strip():
            raise WorkflowError('원고 필수 문자열이 없습니다: ' + key)
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,79}', article['id']):
        raise WorkflowError('원고 id는 영문 소문자·숫자·하이픈 3~80자입니다.')
    if '<' in article['title'] or '>' in article['title']:
        raise WorkflowError('제목은 HTML이 없는 일반 텍스트여야 합니다.')
    if not (5 <= len(article['title']) <= 100) or len(article['content_html']) < 200:
        raise WorkflowError('제목 또는 본문 길이를 확인하세요.')
    if len(article['content_html']) > 150000:
        raise WorkflowError('원고가 너무 큽니다.')
    checker = CheckHTML()
    checker.feed(article['content_html'])
    checker.close()
    if checker.stack or checker.headings < 1:
        raise WorkflowError('본문 태그 또는 h2/h3 제목을 확인하세요.')
    sources = article.get('sources')
    if not isinstance(sources, list) or not sources:
        raise WorkflowError('최소 1개 출처가 필요합니다.')
    ids = set()
    fresh_news = False
    for source in sources:
        for key in ('id', 'url', 'title', 'retrieved_at'):
            if not isinstance(source.get(key), str) or not source[key].strip():
                raise WorkflowError('출처 필수 정보가 없습니다: ' + key)
        if source['id'] in ids:
            raise WorkflowError('출처 id가 중복되었습니다.')
        ids.add(source['id'])
        safe_url(source['url'], ALLOWED_DOMAINS)
        fetched = date_value(source['retrieved_at'], '수집일')
        published = date_value(source['published_at'], '발표일') if source.get('published_at') else None
        if fetched > now().date() or (published and published > now().date()):
            raise WorkflowError('미래 날짜의 출처를 사용할 수 없습니다.')
        if source['url'] not in checker.links:
            raise WorkflowError('본문에서 출처 링크를 찾을 수 없습니다.')
        if article.get('kind') == 'news' and check_fresh:
            if not published or (now().date() - fetched).days > 2:
                raise WorkflowError('뉴스 출처의 수집일이 오래되었거나 발표일이 없습니다. 다시 검증하세요.')
            if source.get('role', 'news') == 'news':
                if (now().date() - published).days > 14:
                    raise WorkflowError('뉴스의 주요 발표가 14일보다 오래되었습니다. 배경 자료와 최신 발표를 구분하세요.')
                fresh_news = True
    if article.get('kind') == 'news' and check_fresh and not fresh_news:
        raise WorkflowError('최근 14일 내 주요 발표 출처가 필요합니다.')
    claims = article.get('claims')
    if not isinstance(claims, list) or not claims:
        raise WorkflowError('주장별 근거 기록이 필요합니다.')
    for claim in claims:
        if not claim.get('text') or not claim.get('source_ids') or any(s not in ids for s in claim['source_ids']):
            raise WorkflowError('주장과 출처 매핑을 확인하세요.')
        if claim.get('verification') != 'verified':
            raise WorkflowError('확인되지 않은 주장이 있습니다. 원고를 보류합니다.')
    if article.get('unresolved'):
        raise WorkflowError('해결되지 않은 사실 확인 항목이 있습니다.')
    images = article.get('images', [])
    if not isinstance(images, list):
        raise WorkflowError('images는 목록이어야 합니다.')
    markers=re.findall(r'<!-- blog-image-(\d+) -->',article['content_html'])
    if len(markers)!=len(set(markers)) or any(int(i)>=len(images) for i in markers):
        raise WorkflowError('이미지 위치 표시는 실제 이미지 번호와 일치하고 중복되지 않아야 합니다.')
    if len(images) > 3:
        raise WorkflowError('원고당 이미지는 최대 3개입니다.')
    for image_index, image in enumerate(images):
        placement = image.get('placement', 'body')
        if placement not in {'body', 'featured_only'}:
            raise WorkflowError('이미지 placement는 body 또는 featured_only여야 합니다.')
        if placement == 'featured_only' and (image_index != 0 or '0' in markers):
            raise WorkflowError('대표 전용 이미지는 첫 번째 항목이며 본문 표시를 사용하지 않습니다.')
        required = ('path', 'author', 'license', 'checked_at', 'alt', 'caption', 'subject')
        if any(not isinstance(image.get(k), str) or not image[k].strip() for k in required):
            raise WorkflowError('이미지 권리 또는 설명 정보가 부족합니다.')
        if image.get('display_width') is not None and (type(image['display_width']) is not int or not 100<=image['display_width']<=1600):
            raise WorkflowError('이미지 표시 폭은 100~1600 정수여야 합니다.')
        if image['license'] not in {'OWN', 'CC0', 'CC-BY-4.0', 'PERMISSION'} or image.get('commercial_use') is not True:
            raise WorkflowError('이미지의 상업적 이용 권한이 확인되지 않았습니다.')
        if image.get('subject_verified') is not True:
            raise WorkflowError('이미지와 실제 모델·주제의 일치 여부를 확인하세요.')
        if image['license'] in {'CC-BY-4.0', 'PERMISSION'} and not image.get('attribution'):
            raise WorkflowError('이미지 출처 표시 문구가 필요합니다.')
        if image['license'] == 'OWN':
            if not image.get('ownership_note'):
                raise WorkflowError('직접 제작 이미지의 제작·소유 근거를 기록하세요.')
        else:
            if not image.get('permission_url'):
                raise WorkflowError('이미지 이용 허가 근거 URL이 필요합니다.')
            safe_url(image['permission_url'])
        if image.get('source_url'):
            safe_url(image['source_url'])
        if date_value(image['checked_at'], '이미지 권리 확인일') > now().date():
            raise WorkflowError('미래 날짜의 이미지 권리 확인일입니다.')
        resolve_image(base_dir, image['path'])
    return article


def resolve_image(base_dir, name):
    base = Path(base_dir).resolve()
    path = (base / name).resolve()
    if base not in path.parents or not path.is_file():
        raise WorkflowError('이미지는 원고 폴더 안의 실제 파일이어야 합니다.')
    if path.stat().st_size > 20 * 1024 * 1024:
        raise WorkflowError('이미지 원본은 20MB 이하로 준비하세요.')
    return path


def optimized_image(path):
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with Image.open(path) as original:
            image = ImageOps.exif_transpose(original)
            image.thumbnail((1600, 1600))
            if image.mode in ('RGBA', 'LA'):
                background = Image.new('RGB', image.size, 'white')
                background.paste(image.convert('RGB'), mask=image.getchannel('A'))
                image = background
            else:
                image = image.convert('RGB')
            out = io.BytesIO()
            image.save(out, format='JPEG', quality=82, optimize=True)
            data = out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise WorkflowError('지원되는 안전한 이미지 파일이 아닙니다.') from None
    if len(data) > 1024 * 1024:
        raise WorkflowError('최적화 후 이미지가 1MB를 초과합니다.')
    return data


def article_hash(article, base_dir):
    # Any change to content, evidence or rights invalidates approval.
    value = {k: v for k, v in article.items() if k != 'review'}
    value['image_file_hashes'] = [digest(resolve_image(base_dir, x['path']).read_bytes()) for x in article.get('images', [])]
    return digest(value)


def slug_for(article):
    return 'yeob-' + article['id'][:60] + '-' + digest(article['id'])[:10]


def normalize_html(value):
    return re.sub(r'\s+', ' ', html.unescape(value or '')).strip()


def category_ids(value):
    categories=value or {}
    values=categories.values() if isinstance(categories,dict) else categories
    return sorted(str(c['ID']) for c in values)


def snapshot(post):
    keys = ('ID', 'slug', 'status', 'date', 'title', 'content')
    data={k: post.get(k) for k in keys}
    data['categories']=category_ids(post.get('categories'))
    return digest(data)


def category_id(article, categories):
    matches = [c for c in categories if html.unescape(c.get('name', '')) == article['category']]
    if len(matches) != 1:
        raise WorkflowError('카테고리 이름이 없거나 중복입니다. categories 명령에서 실제 이름을 확인하세요.')
    return int(matches[0]['ID'])


def payload_matches(post, payload):
    categories = post.get('categories') or {}
    values = categories.values() if isinstance(categories, dict) else categories
    ids = {str(c.get('ID')) for c in values}
    return (post.get('slug') == payload['slug'] and
            normalize_html(post.get('title')) == normalize_html(payload['title']) and
            normalize_html(post.get('content')) == normalize_html(payload['content']) and
            str(payload['categories']) in ids and
            ('featured_image' not in payload or
             str((post.get('post_thumbnail') or {}).get('ID')) == str(payload['featured_image'])))


class Workflow:
    def __init__(self, api, store):
        self.api, self.store = api, store

    def media(self, image, base_dir):
        data = optimized_image(resolve_image(base_dir, image['path']))
        # Metadata is part of the identity, so reused alt/caption stay accurate.
        caption = image['caption'] + (' — ' + image['attribution'] if image.get('attribution') else '')
        key = digest({'bytes': digest(data), 'alt': image['alt'], 'caption': caption})
        title = 'yeob-media-' + key
        record = self.store.data['media'].get(key)
        if record and record.get('media_id'):
            item = self.api.call('/media/' + str(record['media_id']) + '?context=edit')
            if html.unescape(item.get('title', '')) != title:
                raise WorkflowError('기존 미디어가 변경되었습니다. 확인 후 다시 진행하세요.')
            safe_url(item['URL'])
            return item
        existing = self.api.find_media(title)
        if existing:
            if not record:
                raise WorkflowError('로컬 기록이 없는 미디어가 있습니다. 자동으로 소유권을 가정하지 않습니다.')
            item = existing
        elif record:
            raise WorkflowError('이전 미디어 업로드 결과가 불명확하고 아직 조회되지 않습니다. 자동 재전송을 중단합니다.')
        else:
            self.store.data['media'][key] = {'stage': 'pending', 'title': title}
            self.store.save()
            item = self.api.upload_media(data, title, image['alt'], caption)
        safe_url(item['URL'])
        self.store.data['media'][key] = {'stage': 'uploaded', 'media_id': int(item['ID']), 'title': title}
        self.store.save()
        return item

    def upload(self, article, base_dir):
        validate_article(article, base_dir)
        self.api.verify_site()
        key = article['id']
        content_hash = article_hash(article, base_dir)
        record = self.store.data['posts'].get(key)
        if record and record.get('content_hash') != content_hash:
            raise WorkflowError('같은 원고 id의 내용이 변경되었습니다. 새 id를 사용하거나 기존 초안을 수동 검토하세요.')
        if record and record.get('post_id'):
            post = self.api.post(record['post_id'])
            if record.get('stage') == 'verify-pending':
                if post.get('status') != 'draft' or not payload_matches(post, record['payload']):
                    raise WorkflowError('저장된 글이 초안 요청과 일치하지 않습니다.')
                record.update({'stage': 'draft', 'snapshot': snapshot(post),
                               'url': post.get('URL'), 'verified_at': now().isoformat()})
                record.pop('payload', None)
                self.store.save()
                return post, False
            if snapshot(post) != record.get('snapshot'):
                raise WorkflowError('WordPress 게시물이 로컬 기록 이후 변경되었습니다. 자동 수정을 중단합니다.')
            return post, False
        slug = slug_for(article)
        existing = self.api.find_post(slug)
        if record:
            if not existing:
                raise WorkflowError('이전 글 저장 결과가 불명확하고 아직 조회되지 않습니다. 중복 방지를 위해 재전송하지 않습니다.')
            if not payload_matches(existing, record['payload']) or existing.get('status') != 'draft':
                raise WorkflowError('조회된 글이 이전 초안 요청과 일치하지 않습니다. 관리자에서 확인하세요.')
            post = existing
        else:
            if existing:
                raise WorkflowError('같은 슬러그의 관리되지 않은 게시물이 있습니다. 새 원고 id를 사용하세요.')
            cat_id = category_id(article, self.api.categories())
            content = article['content_html']
            featured_media_id = None
            for index, image in enumerate(article.get('images', [])):
                item = self.media(image, base_dir)
                if index == 0:
                    featured_media_id = int(item['ID'])
                if image.get('placement') == 'featured_only':
                    continue
                caption = image['caption'] + (' — ' + image['attribution'] if image.get('attribution') else '')
                width=image.get('display_width')
                width_attr=(' width="'+str(width)+'"') if width else ''
                figure = '<figure><img'+width_attr+' src="' + html.escape(item['URL'], quote=True) + '" alt="' + html.escape(image['alt'], quote=True) + '" /><figcaption>' + html.escape(caption) + '</figcaption></figure>'
                marker='<!-- blog-image-'+str(index)+' -->'
                content=content.replace(marker,figure,1) if marker in content else content+figure
            from post_layout import apply_layout
            content=apply_layout(content)
            payload = {'title': article['title'], 'content': content, 'status': 'draft',
                       'slug': slug, 'categories': str(cat_id), 'publicize': 'false'}
            if featured_media_id is not None:
                payload['featured_image'] = str(featured_media_id)
            record = {'stage': 'pending', 'content_hash': content_hash, 'payload': payload,
                      'featured_media_id': featured_media_id,
                      'attempted_at': now().isoformat()}
            self.store.data['posts'][key] = record
            self.store.save()
            result = self.api.call('/posts/new', data=payload)
            if not result.get('ID'):
                raise UncertainWrite('글 ID가 없습니다. 재실행 시 먼저 실제 저장 여부를 대조합니다.')
            # Save ID before verification, so a failed GET cannot cause duplicate creation.
            record['post_id'] = int(result['ID'])
            record['stage'] = 'verify-pending'
            self.store.save()
            post = self.api.post(record['post_id'])
        if post.get('status') != 'draft' or not payload_matches(post, record['payload']):
            raise WorkflowError('저장된 글의 상태 또는 본문이 요청과 다릅니다. 관리자에서 확인하세요.')
        record.update({'stage': 'draft', 'post_id': int(post['ID']), 'snapshot': snapshot(post),
                       'url': post.get('URL'), 'verified_at': now().isoformat()})
        record.pop('payload', None)
        self.store.save()
        return post, True

    def approve(self, article, base_dir, reviewer, checklist):
        validate_article(article, base_dir)
        if not reviewer.strip() or set(checklist) != {'facts', 'style', 'rights', 'links'}:
            raise WorkflowError('검토자와 facts,style,rights,links 검토 확인이 필요합니다.')
        record = self.store.data['posts'].get(article['id'])
        if not record or record.get('stage') != 'draft':
            raise WorkflowError('검증된 WordPress 초안이 필요합니다.')
        if record['content_hash'] != article_hash(article, base_dir):
            raise WorkflowError('원고가 업로드 후 변경되었습니다.')
        post = self.api.post(record['post_id'])
        if post.get('status') != 'draft' or snapshot(post) != record['snapshot']:
            raise WorkflowError('초안이 변경되었습니다. 다시 검토하세요.')
        record['approval'] = {'reviewer': reviewer, 'checks': sorted(checklist),
                              'content_hash': record['content_hash'], 'snapshot': record['snapshot'],
                              'approved_at': now().isoformat()}
        self.store.save()

    def publish(self, article, base_dir, confirm_id, at=None):
        validate_article(article, base_dir)
        self.api.verify_site()
        key = article['id']
        record = self.store.data['posts'].get(key)
        if confirm_id != key or not record or not record.get('approval'):
            raise WorkflowError('검토 승인과 정확한 --confirm 원고 id가 필요합니다.')
        if record['content_hash'] != article_hash(article, base_dir):
            raise WorkflowError('검토 승인 후 원고가 변경되었습니다.')
        post = self.api.post(record['post_id'])
        if record.get('stage') == 'publish-pending':
            request = record['publish_request']
            if post.get('status') == request['status'] and self.same_published_content(post, record):
                if request.get('date') and not same_instant(post.get('date'), request['date']):
                    raise WorkflowError('예약 시간이 요청과 다릅니다. 관리자에서 확인하세요.')
                record.update({'stage': post['status'], 'snapshot': snapshot(post)})
                self.store.save()
                return post, False
            raise WorkflowError('이전 발행 요청 결과가 불명확합니다. 관리자 확인 전에는 재전송하지 않습니다.')
        if record.get('stage') in {'publish', 'future'}:
            if snapshot(post) != record['snapshot']:
                raise WorkflowError('발행한 게시물이 이후 변경되었습니다.')
            return post, False
        if post.get('status') != 'draft' or snapshot(post) != record['approval']['snapshot']:
            raise WorkflowError('승인한 WordPress 초안과 현재 상태가 다릅니다.')
        payload = {'status': 'publish', 'publicize': 'false'}
        if at:
            parsed = parse_schedule(at)
            payload.update({'status': 'future', 'date': parsed.isoformat()})
        record.update({'stage': 'publish-pending', 'publish_request': payload,
                       'before_publish': {k: post.get(k) for k in ('title', 'content', 'slug', 'categories')}})
        self.store.save()
        self.api.call('/posts/' + str(record['post_id']), data=payload)
        verified = self.api.post(record['post_id'])
        if verified.get('status') != payload['status'] or not self.same_published_content(verified, record):
            raise UncertainWrite('발행 후 상태 또는 본문을 확인할 수 없습니다. 재실행 시 먼저 대조합니다.')
        if at and not same_instant(verified.get('date'), payload['date']):
            raise UncertainWrite('예약 시간이 요청과 일치하지 않습니다.')
        record.update({'stage': verified['status'], 'snapshot': snapshot(verified)})
        self.store.save()
        return verified, True

    @staticmethod
    def same_published_content(post, record):
        return all(category_ids(post.get(k)) == category_ids(v) if k == 'categories' else post.get(k) == v
                   for k, v in record['before_publish'].items())


def parse_schedule(value):
    try:
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=KST)
        if parsed <= now() + dt.timedelta(minutes=5):
            raise ValueError()
        return parsed.astimezone(KST)
    except (ValueError, TypeError):
        raise WorkflowError('예약 시간은 현재보다 5분 이후의 ISO 날짜·시간이어야 합니다. 오프셋이 없으면 Asia/Seoul입니다.') from None


def same_instant(a, b):
    try:
        return dt.datetime.fromisoformat(a) == dt.datetime.fromisoformat(b)
    except (TypeError, ValueError):
        return False
