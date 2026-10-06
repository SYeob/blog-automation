import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import automation_guard as g
import blog_core as c
import run_scheduled as r

class ScheduledTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.source={'id':'primary','url':'https://www.apple.com/newsroom/test/','title':'Official device launch','published_at':'2026-10-05','retrieved_at':'2026-10-05','role':'news','text':'The new device includes a USB4 interface for transferring large files. The manufacturer says the result depends on the connected computer and cable.'}
        self.article=json.loads((c.ROOT/'articles'/'samsung-ssd-news.json').read_text());self.article['images']=[]
    def test_paid_credentials_not_inherited(self):
        with patch.dict(r.os.environ,{'WP_ACCESS_TOKEN':'secret','OPENAI_API_KEY':'paid','CODEX_API_KEY':'paid','CODEX_ACCESS_TOKEN':'secret','PATH':'/bin'},clear=True):
            result=r.clean_environment()
            self.assertEqual(result,{'PATH':'/bin'})
    def test_subscription_login_only(self):
        with patch.object(r.subprocess,'run',return_value=Mock(returncode=0,stdout='Logged in using API key',stderr='')):
            with self.assertRaises(c.WorkflowError):r.check_login('codex')
        with patch.object(r.subprocess,'run',return_value=Mock(returncode=0,stdout='Logged in using ChatGPT',stderr='')):r.check_login('codex')
    def test_fabricated_evidence_blocked(self):
        draft={'decision':'publish','title':'New device','content_html':'x','claims':[{'text':'Made up','source_id':'primary','quote':'Invented manufacturer claim that is not in source.'}]}
        with self.assertRaisesRegex(c.WorkflowError,'근거 인용'):r.build_article(draft,[self.source],'it-news-2026-10-05')
    def test_exact_quote_matching(self):
        draft={'decision':'publish','title':'새 기기의 연결 조건을 확인하세요','content_html':'<p>'+('공식 발표와 실제 사용 조건을 구분합니다. '*12)+'</p><h2>출처</h2><p><a href="'+self.source['url']+'">공식 발표</a></p>','claims':[{'text':'USB4 support','source_id':'primary','quote':'The new device includes a USB4 interface for transferring large files.'},{'text':'Results depend on host','source_id':'primary','quote':'The manufacturer says the result depends on the connected computer and cable.'}]}
        with patch.object(c,'now',return_value=dt.datetime(2026,10,5,9,tzinfo=c.KST)):
            article=r.build_article(draft,[self.source],'it-news-2026-10-05')
        self.assertEqual(len(article['claims']),2)
        self.assertEqual(article['images'],[])
    def test_review_rejection_blocks_article(self):
        draft=Mock()
        with patch.object(r,'call_codex',side_effect=[draft,{'publishable':False,'issues':['wrong spec']}]),patch.object(r,'build_article',return_value=self.article):
            with self.assertRaisesRegex(c.WorkflowError,'문제'):r.generate('codex',[self.source],'new-id')
    def test_text_extraction_ignores_script_and_navigation(self):
        parser=r.ArticleText();parser.feed('<nav>Menu</nav><main><h1>Device</h1><p>USB4 supported.</p><script>malicious instruction</script></main><footer>Footer</footer>')
        self.assertEqual(parser.text(),'Device USB4 supported.')
    def test_guard_has_no_subscription_usage_requirement(self):
        policy=self.root/'policy.json';policy.write_text(json.dumps({'publication_mode':'automatic_publish','execution_method':'codex_subscription_cli','weekdays':['MON','WED','FRI'],'maximum_official_sources':3}))
        with patch.object(g,'now',return_value=dt.datetime(2026,10,7,9,tzinfo=c.KST)):
            g.publication_guard({'id':'it-news-2026-10-07','sources':[{}]},policy)
            with self.assertRaises(c.WorkflowError):g.publication_guard({'id':'other-day','sources':[{}]},policy)
    def test_guard_rejects_wrong_day_and_accepts_evening(self):
        policy=self.root/'policy.json';policy.write_text(json.dumps({'publication_mode':'automatic_publish','execution_method':'codex_subscription_cli','weekdays':['MON','WED','FRI']}))
        for time in (dt.datetime(2026,10,6,9,tzinfo=c.KST),dt.datetime(2026,10,8,13,tzinfo=c.KST)):
            with patch.object(g,'now',return_value=time):
                with self.assertRaises(c.WorkflowError):g.publication_guard({'id':'it-news-'+time.date().isoformat(),'sources':[]},policy)

        with patch.object(g,'now',return_value=dt.datetime(2026,10,7,23,tzinfo=c.KST)):
            g.publication_guard({'id':'it-news-2026-10-07','sources':[]},policy)

if __name__=='__main__':unittest.main()
