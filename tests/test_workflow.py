import copy
import datetime as dt
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

import blog_core as c
import news_sources as n

class FakeAPI:
    def __init__(self):
        self.posts = {}
        self.medias = {}
        self.writes = []
        self.fail_write = False
        self.fail_verify = False
        self.fail_media = False

    def verify_site(self): return {'URL':'https://' + c.SITE, 'ID':123}
    def categories(self): return [{'ID':7,'name':'IT 소식·분석'}]
    def find_post(self, slug):
        return next((copy.deepcopy(p) for p in self.posts.values() if p['slug']==slug),None)
    def post(self, post_id):
        if self.fail_verify:
            self.fail_verify=False
            raise c.WorkflowError('simulated GET failure')
        return copy.deepcopy(self.posts[post_id])
    def find_media(self, title):
        return next((copy.deepcopy(m) for m in self.medias.values() if m['title']==title),None)
    def upload_media(self,data,title,alt,caption):
        self.writes.append('media')
        value={'ID':90,'title':title,'URL':'https://syeob.files.wordpress.com/test.jpg','alt':alt,'caption':caption}
        self.medias[90]=value
        if self.fail_media:
            self.fail_media=False
            raise c.UncertainWrite('simulated timeout')
        return copy.deepcopy(value)
    def call(self,path='',data=None,**kwargs):
        if path.startswith('/media/') and data is None:
            return copy.deepcopy(self.medias[int(path.split('/')[2].split('?')[0])])
        self.writes.append(path)
        if path == '/posts/new':
            value={'ID':42,'status':data['status'],'title':data['title'],'content':data['content'],'slug':data['slug'],'categories':{'IT 소식·분석':{'ID':7}},'date':'2026-10-05T12:00:00+09:00','URL':'https://syeob.wordpress.com/?p=42'}
            if 'featured_image' in data:
                value['post_thumbnail']={'ID':int(data['featured_image'])}
            self.posts[42]=value
        else:
            value=self.posts[int(path.rsplit('/',1)[-1])]
            value.update({k:v for k,v in data.items() if k in {'status','date'}})
        if self.fail_write:
            self.fail_write=False
            raise c.UncertainWrite('simulated timeout')
        return copy.deepcopy(value)

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.clock=patch.object(c,'now',return_value=dt.datetime(2026,10,5,14,tzinfo=c.KST))
        self.clock.start();self.addCleanup(self.clock.stop)
        self.a=json.loads((c.ROOT/'articles'/'samsung-ssd-news.json').read_text())
        self.a['images']=[]
        self.api=FakeAPI();self.store=c.Store(self.base/'state.json');self.w=c.Workflow(self.api,self.store)
    def upload(self):return self.w.upload(self.a,self.base)
    def approve(self):
        self.w.approve(self.a,self.base,'tester',['facts','style','rights','links'])
    def test_upload_then_reuse(self):
        post,created=self.upload();self.assertTrue(created);self.assertEqual(post['status'],'draft')
        self.assertNotIn('post_thumbnail',post)
        post,created=self.upload();self.assertFalse(created);self.assertEqual(self.api.writes,['/posts/new'])
    def test_timeout_recovery_no_duplicate(self):
        self.api.fail_write=True
        with self.assertRaises(c.UncertainWrite):self.upload()
        self.assertEqual(self.store.data['posts'][self.a['id']]['stage'],'pending')
        post,created=self.upload();self.assertEqual(post['ID'],42)
        self.assertEqual(self.api.writes,['/posts/new'])
    def test_no_match_after_timeout_never_reposts(self):
        self.api.fail_write=True
        with self.assertRaises(c.UncertainWrite):self.upload()
        self.api.posts.clear()
        with self.assertRaisesRegex(c.WorkflowError,'재전송'):self.upload()
        self.assertEqual(len(self.api.writes),1)
    def test_verify_failure_recovered_by_id(self):
        self.api.fail_verify=True
        with self.assertRaises(c.WorkflowError):self.upload()
        self.assertEqual(self.store.data['posts'][self.a['id']]['stage'],'verify-pending')
        self.upload();self.assertEqual(len(self.api.writes),1)
        self.assertEqual(self.store.data['posts'][self.a['id']]['stage'],'draft')
    def test_slug_collision_not_adopted(self):
        self.api.posts[99]={'ID':99,'slug':c.slug_for(self.a)}
        with self.assertRaisesRegex(c.WorkflowError,'관리되지 않은'):self.upload()
        self.assertEqual(self.api.writes,[])
    def test_changed_article_same_id_blocks(self):
        self.upload();self.a['title']+=' 변경'
        with self.assertRaisesRegex(c.WorkflowError,'변경'):self.upload()
        self.assertEqual(len(self.api.writes),1)
    def test_remote_edit_blocks(self):
        self.upload();self.api.posts[42]['content']+='external'
        with self.assertRaisesRegex(c.WorkflowError,'변경'):self.upload()
    def test_unreviewed_publish_blocked(self):
        self.upload()
        with self.assertRaisesRegex(c.WorkflowError,'검토 승인'):self.w.publish(self.a,self.base,self.a['id'])
        self.assertEqual(len(self.api.writes),1)
    def test_approve_requires_all_checks(self):
        self.upload()
        with self.assertRaises(c.WorkflowError):self.w.approve(self.a,self.base,'tester',['facts'])
    def test_wrong_confirmation_blocked(self):
        self.upload();self.approve()
        with self.assertRaises(c.WorkflowError):self.w.publish(self.a,self.base,'wrong-id')
    def test_local_change_after_approval_blocks(self):
        self.upload();self.approve();self.a['claims'][0]['text']+='changed'
        with self.assertRaisesRegex(c.WorkflowError,'변경'):self.w.publish(self.a,self.base,self.a['id'])
    def test_remote_change_after_approval_blocks(self):
        self.upload();self.approve();self.api.posts[42]['title']='changed'
        with self.assertRaisesRegex(c.WorkflowError,'다릅니다'):self.w.publish(self.a,self.base,self.a['id'])
    def test_publish_and_repeat(self):
        self.upload();self.approve()
        post,changed=self.w.publish(self.a,self.base,self.a['id']);self.assertTrue(changed);self.assertEqual(post['status'],'publish')
        post,changed=self.w.publish(self.a,self.base,self.a['id']);self.assertFalse(changed)
        self.assertEqual(len(self.api.writes),2)
    def test_publish_timeout_recovery(self):
        self.upload();self.approve();self.api.fail_write=True
        with self.assertRaises(c.UncertainWrite):self.w.publish(self.a,self.base,self.a['id'])
        post,changed=self.w.publish(self.a,self.base,self.a['id']);self.assertFalse(changed);self.assertEqual(post['status'],'publish')
        self.assertEqual(len(self.api.writes),2)
    def test_schedule_kst(self):
        self.upload();self.approve()
        post,changed=self.w.publish(self.a,self.base,self.a['id'],'2026-10-06T09:00:00')
        self.assertEqual(post['status'],'future');self.assertEqual(post['date'],'2026-10-06T09:00:00+09:00')
    def test_past_schedule_blocks(self):
        self.upload();self.approve()
        with self.assertRaises(c.WorkflowError):self.w.publish(self.a,self.base,self.a['id'],'2026-10-05T13:00:00')
        self.assertEqual(len(self.api.writes),1)
    def test_missing_or_unverified_claim_blocks(self):
        self.a['claims'][0]['verification']='unverified'
        with self.assertRaisesRegex(c.WorkflowError,'確認|확인'):self.upload()
        self.assertFalse(self.api.writes)
    def test_news_stale_blocks(self):
        self.a['sources'][0]['published_at']='2026-09-01'
        with self.assertRaisesRegex(c.WorkflowError,'오래'):self.upload()
    def test_future_source_blocks(self):
        self.a['sources'][0]['retrieved_at']='2026-10-06'
        with self.assertRaisesRegex(c.WorkflowError,'미래'):self.upload()
    def test_background_only_not_news(self):
        for s in self.a['sources']:s['role']='background'
        with self.assertRaisesRegex(c.WorkflowError,'최근'):self.upload()
    def test_unsafe_html_blocks(self):
        for unsafe in ['<script>alert(1)</script>','<p onclick="x">test</p>','<a href="javascript:alert(1)">x</a>']:
            candidate=copy.deepcopy(self.a);candidate['content_html']+=unsafe
            with self.assertRaises(c.WorkflowError):c.validate_article(candidate,self.base)
    def test_malformed_html_blocks(self):
        self.a['content_html']+='<p><strong>x</p></strong>'
        with self.assertRaises(c.WorkflowError):self.upload()
    def test_source_not_in_body_blocks(self):
        self.a['sources'][0]['url']='https://www.apple.com/newsroom/new/'
        with self.assertRaisesRegex(c.WorkflowError,'출처 링크'):self.upload()
    def test_h3_bold_headings_are_valid(self):
        self.a['content_html']=self.a['content_html'].replace('<h2>','<h3><strong>').replace('</h2>','</strong></h3>')
        self.upload()
    def test_unknown_image_marker_is_blocked(self):
        self.a['content_html']='<!-- blog-image-0 -->'+self.a['content_html']
        with self.assertRaisesRegex(c.WorkflowError,'이미지 위치'):self.upload()
        self.assertEqual(self.api.writes,[])
    def test_image_inserted_at_requested_position(self):
        from PIL import Image
        Image.new('RGB',(50,50),'blue').save(self.base/'diagram.png')
        self.a['images']=[{'path':'diagram.png','author':'tester','license':'OWN','ownership_note':'original diagram','commercial_use':True,'checked_at':'2026-10-05','alt':'diagram','caption':'diagram','subject':'SSD path','subject_verified':True,'display_width':400}]
        self.a['content_html']='<!-- blog-image-0 -->'+self.a['content_html']
        self.upload();body=self.api.posts[42]['content']
        self.assertTrue(body.startswith('<figure ' ))
        self.assertIn('width="400"',body)
        self.assertNotIn('blog-image-',body)

    def test_featured_only_image_is_not_duplicated_in_body(self):
        from PIL import Image
        Image.new('RGB',(50,50),'blue').save(self.base/'cover.png')
        self.a['images']=[{'path':'cover.png','author':'tester','license':'OWN','ownership_note':'original cover','commercial_use':True,'checked_at':'2026-10-05','alt':'cover','caption':'cover','subject':'SSD','subject_verified':True,'placement':'featured_only'}]
        self.upload()
        self.assertEqual(self.api.posts[42]['post_thumbnail']['ID'],90)
        self.assertNotIn('<img',self.api.posts[42]['content'])
        self.approve();self.w.publish(self.a,self.base,self.a['id'])
        self.assertEqual(self.api.posts[42]['status'],'publish')

    def test_featured_only_body_marker_is_blocked_before_write(self):
        from PIL import Image
        Image.new('RGB',(50,50),'blue').save(self.base/'cover.png')
        self.a['images']=[{'path':'cover.png','author':'tester','license':'OWN','ownership_note':'original cover','commercial_use':True,'checked_at':'2026-10-05','alt':'cover','caption':'cover','subject':'SSD','subject_verified':True,'placement':'featured_only'}]
        self.a['content_html']='<!-- blog-image-0 -->'+self.a['content_html']
        with self.assertRaisesRegex(c.WorkflowError,'대표 전용'):self.upload()
        self.assertEqual(self.api.writes,[])

    def test_media_rights_and_hash_reuse(self):
        from PIL import Image
        file=self.base/'diagram.png';Image.new('RGB',(50,50),'blue').save(file)
        image={'path':'diagram.png','author':'tester','license':'OWN','ownership_note':'original diagram','commercial_use':True,'checked_at':'2026-10-05','alt':'diagram','caption':'own diagram','subject':'SSD path','subject_verified':True}
        self.a['images']=[image]
        self.upload();self.upload()
        self.assertEqual(self.api.writes,['media','/posts/new'])
        self.assertIn('alt="diagram"',self.api.posts[42]['content'])
        self.assertEqual(self.api.posts[42]['post_thumbnail']['ID'],90)
        self.assertEqual(self.store.data['posts'][self.a['id']]['featured_media_id'],90)
        other=copy.deepcopy(self.a);other['id']='another-news-id'
        self.w.upload(other,self.base)
        self.assertEqual(self.api.writes.count('media'),1)
    def test_media_timeout_recovery(self):
        from PIL import Image
        file=self.base/'diagram.png';Image.new('RGB',(50,50),'blue').save(file)
        image={'path':'diagram.png','author':'tester','license':'OWN','ownership_note':'original diagram','commercial_use':True,'checked_at':'2026-10-05','alt':'diagram','caption':'own diagram','subject':'SSD path','subject_verified':True}
        self.a['images']=[image];self.api.fail_media=True
        with self.assertRaises(c.UncertainWrite):self.upload()
        self.upload();self.assertEqual(self.api.writes.count('media'),1)
    def test_nc_image_blocks(self):
        self.a['images']=[{'path':'test','author':'a','license':'CC-BY-NC','commercial_use':False,'checked_at':'2026-10-05','alt':'a','caption':'a','subject':'a','subject_verified':True}]
        with self.assertRaisesRegex(c.WorkflowError,'상업적'):self.upload()
    def test_image_path_escape_blocks(self):
        with self.assertRaises(c.WorkflowError):c.resolve_image(self.base,'../../etc/passwd')
    def test_lock_rejects_concurrent_process(self):
        with c.locked(self.base):
            with self.assertRaisesRegex(c.WorkflowError,'다른 작업'):
                with c.locked(self.base):pass
    def test_atomic_state_persists(self):
        self.upload();other=c.Store(self.store.path)
        self.assertEqual(other.data['posts'][self.a['id']]['post_id'],42)
        self.assertEqual(self.store.path.stat().st_mode & 0o777,0o600)
    def test_token_permissions_expiry_and_no_refresh_storage(self):
        path=self.base/'secrets'/'token.json'
        metadata=c.save_token({'access_token':'dummy-secret','expires_in':60,'refresh_token':'do-not-store'},path)
        self.assertTrue(metadata['has_refresh_token']);self.assertNotIn('refresh_token',c.read_json(path))
        with patch.dict(os.environ,{},clear=True),patch.object(c,'load_dotenv'):
            self.assertEqual(c.load_token(path),'dummy-secret')
            path.chmod(0o644)
            with self.assertRaisesRegex(c.AuthError,'권한'):c.load_token(path)
            path.chmod(0o600)
            with patch.object(c,'now',return_value=dt.datetime(2026,10,6,tzinfo=c.KST)):
                with self.assertRaisesRegex(c.AuthError,'만료'):c.load_token(path)
    def test_http_errors_do_not_expose_secrets(self):
        api=c.WordPress('dummy-token')
        for code in (401,403,500):
            error=urllib.error.HTTPError('https://example.com',code,'dummy-secret',{},io.BytesIO(b'dummy-secret'))
            api.opener=Mock();api.opener.open.side_effect=error
            with self.assertRaises(c.WorkflowError) as caught:api.call('/posts/new',data={'x':'dummy-secret'})
            self.assertNotIn('dummy-secret',str(caught.exception))
            if code>=500:self.assertIsInstance(caught.exception,c.UncertainWrite)
    def test_xml_entities_rejected(self):
        with self.assertRaises(c.WorkflowError):n.parse_feed(b'<!DOCTYPE x [<!ENTITY a "x">]><rss/>','google')
    def test_topic_priority(self):
        self.assertGreater(n.audience_score('Samsung P9 SSD USB4 launch performance')[0],n.audience_score('Leadership update on enterprise research')[0])
    def test_candidate_skeleton_cannot_upload(self):
        candidate={'id':'x','url':self.a['sources'][0]['url'],'title':'SSD launch','published_at':'2026-10-01','retrieved_at':'2026-10-05'}
        with self.assertRaises(c.WorkflowError):c.validate_article(n.brief(candidate,'sample-new-id'),self.base)

    def test_compose_verified_packet(self):
        import article_writer
        packet=json.loads((c.ROOT/'articles'/'evidence.example.json').read_text())
        packet['images']=[]
        result=article_writer.compose(packet,self.base)
        self.assertEqual(result['review']['status'],'needs_review')
        self.assertIn('<h3><strong>',result['content_html'])
        self.assertNotIn('<script',result['content_html'])
    def test_compose_escapes_source_text(self):
        import article_writer
        packet=json.loads((c.ROOT/'articles'/'evidence.example.json').read_text())
        packet['images']=[]
        packet['sections'][0]['paragraphs'][0]='<script>untrusted instructions</script>'
        result=article_writer.compose(packet,self.base)
        self.assertIn('&lt;script&gt;',result['content_html'])
    def test_compose_unverified_packet_blocked(self):
        import article_writer
        packet=json.loads((c.ROOT/'articles'/'evidence.example.json').read_text())
        packet['images']=[]
        packet['claims'][0]['verification']='unverified'
        with self.assertRaises(c.WorkflowError):article_writer.compose(packet,self.base)

if __name__=='__main__':unittest.main()
