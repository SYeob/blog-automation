"""Official RSS/Atom headline intake. Feed content is never treated as instructions."""
import datetime as dt
from email.utils import parsedate_to_datetime
import html
import json
from pathlib import Path
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from blog_core import ALLOWED_DOMAINS, KST, WorkflowError, atomic_json, digest, now, safe_url

FEEDS = {
    'google': 'https://blog.google/rss/',
    'microsoft': 'https://blogs.microsoft.com/feed/',
    'apple': 'https://www.apple.com/newsroom/rss-feed.rss',
    'samsung': 'https://news.samsungsemiconductor.com/global/feed/',
    'playstation': 'https://blog.playstation.com/feed/',
}

class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url(newurl, ALLOWED_DOMAINS)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    safe_url(url, ALLOWED_DOMAINS)
    try:
        opener = urllib.request.build_opener(OfficialRedirect())
        request = urllib.request.Request(url, headers={'User-Agent':'YeobBlogAutomation/1.0', 'Accept':'application/rss+xml, application/atom+xml, text/html'})
        with opener.open(request, timeout=20) as response:
            safe_url(response.url, ALLOWED_DOMAINS)
            data = response.read(2_000_001)
            if len(data) > 2_000_000:
                raise WorkflowError('출처 응답이 수집 한도를 초과했습니다.')
            return data
    except (urllib.error.URLError, OSError):
        raise WorkflowError('공식 출처 조회에 실패했습니다.') from None


def parse_feed(data, provider, days=14):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise WorkflowError('지원하지 않는 XML 선언입니다.')
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise WorkflowError('뉴스 피드 형식을 읽을 수 없습니다.') from None
    entries = root.findall('.//item')
    atom = '{http://www.w3.org/2005/Atom}'
    if not entries:
        entries = root.findall(atom + 'entry')
    results = []
    for entry in entries:
        is_atom = entry.tag.startswith(atom)
        prefix = atom if is_atom else ''
        title = entry.findtext(prefix + 'title', '')
        if is_atom:
            links = entry.findall(atom + 'link')
            url = next((l.get('href', '') for l in links if l.get('rel', 'alternate') == 'alternate'), '')
            date = entry.findtext(atom + 'published') or entry.findtext(atom + 'updated')
        else:
            url = entry.findtext('link', '')
            date = entry.findtext('pubDate')
        try:
            safe_url(url, ALLOWED_DOMAINS)
            published = dt.datetime.fromisoformat(date.replace('Z', '+00:00')) if is_atom else parsedate_to_datetime(date)
            if published.tzinfo is None:
                published = published.replace(tzinfo=dt.timezone.utc)
            published = published.astimezone(KST)
        except (ValueError, TypeError, AttributeError, WorkflowError):
            continue
        age = (now().date() - published.date()).days
        if age < 0 or age > days:
            continue
        results.append({'id':digest(url)[:12], 'title':html.unescape(re.sub('<[^>]+>', '', title)).strip(),
                        'url':url, 'published_at':published.date().isoformat(),
                        'retrieved_at':now().date().isoformat(), 'provider':provider,
                        'verification':'candidate'})
    return results


def audience_score(title):
    title = title.lower()
    groups = {
        '출시·구매 시점': r'launch|available|release|pre.?order|debut|arrive',
        '기기·부품': r'\bssd\b|nand|ufs|usb4|iphone|galaxy|pixel|nintendo|switch|ps5|playstation|console|controller|headphone|laptop|camera|airpods|memory|storage',
        '성능·체감 기능': r'speed|performance|battery|charg|display|material|cooling|feature|patent|thermal|durab|upscal|aperture|ray.trac|frame.rate|fps|pssr',
    }
    reasons = [name for name, pattern in groups.items() if re.search(pattern, title)]
    score = len(reasons) * 10
    if '기기·부품' in reasons:
        score += 20
    if re.search(r'leadership|education|enterprise|scientific|research|partnership|shareholder', title):
        score -= 20
    if re.search(r'podcast|monthly games|story overview|editions detailed|badge.a.thon', title):
        score -= 30
    return score, reasons


def collect(providers, days=14):
    result, failures = [], []
    for name in providers:
        try:
            result.extend(parse_feed(fetch(FEEDS[name]), name, days))
        except WorkflowError:
            failures.append(name)
    unique = {r['url']:r for r in result}
    for item in unique.values():
        item['audience_score'], item['selection_reasons'] = audience_score(item['title'])
    records = sorted(unique.values(), key=lambda r:(r['audience_score'], r['published_at'], r['title']), reverse=True)
    return {'collected_at':now().isoformat(), 'candidates':records, 'failed_providers':failures}


def brief(candidate, article_id):
    # A candidate is a lead, not a verified article. Validation blocks this skeleton.
    return {'id':article_id, 'kind':'news', 'title':'검토 필요: ' + candidate['title'][:70],
            'category':'IT 소식·분석',
            'content_html':'<p>공식 발표를 읽고 독자의 질문에 답하는 요약을 작성하세요.</p><h2>확인된 사실</h2><p>검증한 핵심 내용을 작성하세요.</p><h2>의미와 한계</h2><p>발표 내용과 해석을 구분하세요.</p><h2>출처</h2><p><a href="' + html.escape(candidate['url'], quote=True) + '">' + html.escape(candidate['title']) + '</a></p>',
            'sources':[{k:v for k,v in candidate.items() if k not in {'provider','verification','audience_score','selection_reasons'}}],
            'claims':[{'text':'공식 문서에서 확인한 주장으로 교체하세요.', 'source_ids':[candidate['id']], 'verification':'unverified'}],
            'images':[], 'unresolved':['원문 사실 확인과 한국어 원고 작성 필요'], 'review':{'status':'needs_review'}}
