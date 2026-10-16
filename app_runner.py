#!/usr/bin/env python3
"""Codex app writes/reviews public draft data; Python validates and publishes."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import automation_guard
import news_sources
import run_scheduled
from blog_core import ROOT,Store,Workflow,WordPress,WorkflowError,atomic_json,locked,load_token,now,read_json,validate_article


def today_id():
    day=now().date().isoformat()
    policy=read_json(ROOT/'automation-policy.json')
    return policy.get('day_article_overrides',{}).get(day,'it-news-'+day)


def prepare():
    if read_json(ROOT/'automation-policy.json').get('publication_mode') == 'manual_request':
        return {'action':'skip','reason':'수동 요청 전용입니다. 정기 자동 발행은 중지되어 있습니다.'}
    article_id=today_id()
    # A completed day needs only a read: no lock writes or remote revalidation.
    record=Store().data['posts'].get(article_id,{})
    if record.get('stage') in {'publish','future'}:
        return {'action':'already_published','id':article_id,'post_id':record['post_id']}
    policy=read_json(ROOT/'automation-policy.json')
    weekdays=('MON','TUE','WED','THU','FRI','SAT','SUN')
    if weekdays[now().weekday()] not in policy.get('weekdays',[]):
        return {'action':'skip','reason':'오늘은 정책에서 허용한 발행 요일이 아닙니다.'}
    with locked():
        record=Store().data['posts'].get(article_id,{})
        if record.get('stage') in {'publish','future'}:
            return {'action':'already_published','id':article_id,'post_id':record['post_id']}
        packet=ROOT/'state'/(article_id+'-sources.json')
        draft=ROOT/'articles'/(article_id+'-draft.json')
        review=ROOT/'articles'/(article_id+'-review.json')
        if packet.exists() and draft.exists():
            return {'action':'review_existing','id':article_id,'sources_file':str(packet),'draft_file':str(draft),'review_file':str(review)}
        recent=[]
        store=Store()
        for path in (ROOT/'articles').glob('*.json'):
            item=read_json(path)
            record=store.data['posts'].get(item.get('id'),{}) if isinstance(item,dict) else {}
            if record.get('stage')=='publish':
                recent.append({'id':item['id'],'title':item['title'],'topic_category':item.get('topic_category'),
                               'topic_type':item.get('topic_type'),'sources':item.get('sources',[])})
        return {'action':'research_topics','id':article_id,'topic_prompt_file':str(ROOT/'it_blog_topic_prompt.txt'),
                'recent_posts':sorted(recent,key=lambda p:p['id'],reverse=True)[:30],
                'selection_file':str(ROOT/'state'/(article_id+'-selection.json')),
                'sources_file':str(packet),'draft_file':str(draft),'review_file':str(review)}



def finalize(draft_path,review_path):
    article_id=today_id()
    automation_guard.publication_guard({'id':article_id,'sources':[]})
    draft_path=Path(draft_path).resolve();review_path=Path(review_path).resolve()
    for path in (draft_path,review_path):
        if path.parent!=ROOT/'articles':raise WorkflowError('원고·검토 파일은 articles 폴더 안에 있어야 합니다.')
    with locked():
        store=Store();client=WordPress(load_token());client.verify_site();workflow=Workflow(client,store)
        record=store.data['posts'].get(article_id,{})
        if record.get('stage') in {'publish','future'}:
            post=client.post(record['post_id'])
            if post.get('status')!='publish':raise WorkflowError('기록된 공개 글의 실제 상태가 변경되었습니다. 관리자 확인이 필요합니다.')
            return {'action':'already_published','post_id':post['ID'],'status':post['status'],'url':post.get('URL','')}
        review=read_json(review_path)
        if review.get('draft_sha256')!=hashlib.sha256(draft_path.read_bytes()).hexdigest() or review.get('publishable') is not True or review.get('issues'):
            raise WorkflowError('원고 해시와 일치하는 문제 없는 검토 기록이 필요합니다.')
        selection=read_json(ROOT/'state'/(article_id+'-selection.json'))
        candidates=selection.get('candidates',[])
        if len(candidates)<10 or len({c.get('url') for c in candidates})<10:
            raise WorkflowError('서로 다른 출처 URL의 주제 후보 10개 이상을 조사해야 합니다.')
        if not selection.get('selected_url') or not selection.get('category') or not selection.get('type') or not selection.get('reason'):
            raise WorkflowError('주제 선정과 분야·유형·선정 이유 기록이 필요합니다.')
        sources=read_json(ROOT/'state'/(article_id+'-sources.json'))
        if selection['selected_url'] not in {s['url'] for s in sources}:
            raise WorkflowError('선정한 주제와 원고 출처가 다릅니다.')
        article=run_scheduled.build_article(read_json(draft_path),sources,article_id)
        article['topic_category']=selection['category']
        article['topic_type']=selection['type']
        article['review']={'status':'ready','writer':'codex-app','verification':'source-quote-match-and-app-source-review'}
        validate_article(article,ROOT/'articles')
        if '<h2' in article['content_html'] or not re.search(r'<h3>\s*<strong>',article['content_html']):
            raise WorkflowError('자동 원고는 h3 볼드 소제목을 사용해야 합니다.')
        if '<table' not in article['content_html'] or not article['images']:
            raise WorkflowError('자동 원고에는 성능 비교표와 주제에 맞는 권리 확인 이미지가 필요합니다.')
        for source in sources:news_sources.fetch(source['url'])
        path=ROOT/'articles'/(article_id+'.json');atomic_json(path,article)
        automation_guard.publication_guard(article)
        if record.get('stage')!='publish-pending':
            workflow.upload(article,path.parent)
            workflow.approve(article,path.parent,'Codex 자동운영',['facts','style','rights','links'])
        automation_guard.publication_guard(article)
        post,_=workflow.publish(article,path.parent,article_id)
        if post['status']!='publish':raise WorkflowError('공개 상태를 확인하지 못했습니다.')
        return {'action':'published','post_id':post['ID'],'status':post['status'],'url':post.get('URL',''),'title':post['title']}


def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('prepare')
    cmd=sub.add_parser('finalize');cmd.add_argument('draft');cmd.add_argument('review')
    args=parser.parse_args()
    try:
        result=prepare() if args.command=='prepare' else finalize(args.draft,args.review)
        print(json.dumps(result,ensure_ascii=False));return 0
    except WorkflowError as exc:print(json.dumps({'action':'hold','reason':str(exc)},ensure_ascii=False));return 1
    except Exception as exc:print(json.dumps({'action':'error','type':type(exc).__name__}));return 1

if __name__=='__main__':raise SystemExit(main())
