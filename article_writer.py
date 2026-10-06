"""Cost-free structured drafting from a human-verified evidence packet."""
import html
from pathlib import Path

from blog_core import WorkflowError, validate_article

STYLE = ('한국어 존댓말, 짧은 문단. 독자의 질문에 먼저 답합니다. 제조사 주장·실측·계산·해석을 구분합니다. '
         '출시·예고·특허 출원·등록·실제 탑재를 구분합니다. 가격·지역·용량·세대·실험 조건을 생략하지 않습니다.')


def compose(packet, base_dir):
    # No source HTML or feed text is executed or given instruction priority.
    required = ('id', 'title', 'category', 'answer', 'sections', 'sources', 'claims')
    if any(not packet.get(k) for k in required):
        raise WorkflowError('근거 패킷 필수 항목을 확인하세요: ' + ', '.join(required))
    body = '<p>' + html.escape(packet['answer']) + '</p>'
    for section in packet['sections']:
        if not section.get('heading') or not section.get('paragraphs'):
            raise WorkflowError('섹션 제목과 문단이 필요합니다.')
        body += '<h3><strong>' + html.escape(section['heading']) + '</strong></h3>'
        for paragraph in section['paragraphs']:
            body += '<p>' + html.escape(paragraph) + '</p>'
    body += '<h3><strong>출처와 확인 날짜</strong></h3><ul>'
    for source in packet['sources']:
        body += '<li><a href="' + html.escape(source['url'], quote=True) + '">' + html.escape(source['title']) + '</a> — 발표일 ' + html.escape(source.get('published_at') or '확인 불가') + ', 확인일 ' + html.escape(source['retrieved_at']) + '</li>'
    body += '</ul><p>공개 자료 기반 정리이며 직접 사용하거나 성능을 측정한 결과는 아닙니다.</p>'
    result = {'id':packet['id'], 'title':packet['title'], 'category':packet['category'],
              'kind':packet.get('kind','news'), 'content_html':body,
              'sources':packet['sources'], 'claims':packet['claims'],
              'images':packet.get('images',[]), 'unresolved':packet.get('unresolved',[]),
              'review':{'status':'needs_review','writer':'verified-evidence-template'}}
    validate_article(result, base_dir)
    return result
