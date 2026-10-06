"""Automatic publication policy and Korean calendar-day checks."""
from blog_core import ROOT, WorkflowError, now, read_json


def publication_guard(article, policy_path=ROOT/'automation-policy.json'):
    policy=read_json(policy_path)
    if policy.get('publication_mode') != 'automatic_publish' or policy.get('execution_method') not in {'codex_app','codex_subscription_cli'}:
        raise WorkflowError('자동 공개 발행 정책이 설정되지 않았습니다.')
    if policy.get('status') == 'runtime_moved':
        raise WorkflowError('이전 실행 폴더입니다. 정책에 기록된 runtime_directory를 사용하세요.')
    current=now()
    weekdays=('MON','TUE','WED','THU','FRI','SAT','SUN')
    if weekdays[current.weekday()] not in policy.get('weekdays',[]):
        raise WorkflowError('오늘은 정책에서 허용한 발행 요일이 아닙니다.')
    day=current.date().isoformat()
    expected=policy.get('day_article_overrides',{}).get(day,'it-news-'+day)
    if article['id'] != expected:
        raise WorkflowError('자동 발행 원고는 오늘 날짜의 it-news-YYYY-MM-DD여야 합니다.')
    if len(article['sources']) > policy.get('maximum_official_sources',3):
        raise WorkflowError('설정된 공식 출처 수를 초과했습니다.')
