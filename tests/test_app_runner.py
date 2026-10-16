import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import app_runner as a
import blog_core as c

class AppRunnerTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name).resolve()
        (self.root/'articles').mkdir();(self.root/'state').mkdir()
        self.date=dt.datetime(2026,10,5,15,tzinfo=c.KST)
        (self.root/'automation-policy.json').write_text(json.dumps({'publication_mode':'automatic_publish','weekdays':['MON','WED','FRI']}))
        root_patch=patch.object(a,'ROOT',self.root)
        root_patch.start();self.addCleanup(root_patch.stop)
    def test_published_day_skips_collection(self):
        with patch.object(a,'today_id',return_value='it-news-2026-10-05'),patch.object(a,'now',return_value=self.date),patch.object(a,'Store',return_value=Mock(data={'posts':{'it-news-2026-10-05':{'stage':'publish','post_id':28}}})),patch.object(a.news_sources,'collect') as collect:
            self.assertEqual(a.prepare()['action'],'already_published');collect.assert_not_called()
    def test_off_day_skips_without_wordpress(self):
        with patch.object(a,'now',return_value=dt.datetime(2026,10,6,15,tzinfo=c.KST)),patch.object(a,'read_json',return_value={'weekdays':['MON','WED','FRI']}),patch.object(a,'Store',return_value=Mock(data={'posts':{}})),patch.object(a,'WordPress') as client:
            self.assertEqual(a.prepare()['action'],'skip');client.assert_not_called()
    def test_manual_mode_skips_before_state_lock_or_remote_calls(self):
        (self.root/'automation-policy.json').write_text(json.dumps({'publication_mode':'manual_request'}))
        with patch.object(a,'Store') as store,patch.object(a,'locked') as lock,patch.object(a,'WordPress') as client:
            self.assertEqual(a.prepare()['action'],'skip')
            store.assert_not_called();lock.assert_not_called();client.assert_not_called()

    def test_published_day_does_not_lock_or_revalidate_remote_status(self):
        record={'posts':{'it-news-2026-10-05':{'stage':'publish','post_id':28}}}
        with patch.object(a,'today_id',return_value='it-news-2026-10-05'),patch.object(a,'Store',return_value=Mock(data=record)),patch.object(a,'locked') as lock,patch.object(a,'WordPress') as client:
            self.assertEqual(a.prepare()['action'],'already_published')
            lock.assert_not_called();client.assert_not_called()

    def test_review_hash_tamper_blocks_writes(self):
        draft=self.root/'articles/draft.json';draft.write_text('{}');review=self.root/'articles/review.json';review.write_text(json.dumps({'draft_sha256':'incorrect','publishable':True,'issues':[]}))
        workflow=Mock()
        with patch.object(a,'ROOT',self.root),patch.object(a,'today_id',return_value='it-news-2026-10-05'),patch.object(a.automation_guard,'publication_guard'),patch.object(a,'load_token',return_value='test'),patch.object(a,'WordPress'),patch.object(a,'Store',return_value=Mock(data={'posts':{}})),patch.object(a,'Workflow',return_value=workflow):
            with self.assertRaisesRegex(c.WorkflowError,'해시'):a.finalize(draft,review)
            workflow.upload.assert_not_called();workflow.publish.assert_not_called()
    def test_repeated_finalize_is_read_only(self):
        client=Mock();client.post.return_value={'ID':28,'status':'publish','URL':'https://example.com/post'};workflow=Mock()
        with patch.object(a,'ROOT',self.root),patch.object(a.automation_guard,'publication_guard'),patch.object(a,'load_token',return_value='test'),patch.object(a,'WordPress',return_value=client),patch.object(a,'today_id',return_value='it-news-2026-10-05'),patch.object(a,'Store',return_value=Mock(data={'posts':{'it-news-2026-10-05':{'stage':'publish','post_id':28}}})),patch.object(a,'Workflow',return_value=workflow):
            self.assertEqual(a.finalize(self.root/'articles/draft.json',self.root/'articles/review.json')['action'],'already_published')
            workflow.upload.assert_not_called();workflow.publish.assert_not_called()
            client.post.return_value['status']='draft'
            with self.assertRaises(c.WorkflowError):a.finalize(self.root/'articles/draft.json',self.root/'articles/review.json')

if __name__=='__main__':unittest.main()

class StableCategoryTests(unittest.TestCase):
    def test_category_count_changes_are_not_content_changes(self):
        import copy
        before={'ID':28,'title':'Title','content':'Content','slug':'slug','status':'draft','categories':{'news':{'ID':7,'post_count':0}}}
        after=copy.deepcopy(before);after['categories']['news']['post_count']=1
        self.assertEqual(c.snapshot(before),c.snapshot(after))
        record={'before_publish':{k:before[k] for k in ('title','content','slug','categories')}}
        self.assertTrue(c.Workflow.same_published_content(after,record))
        after['categories']['news']['ID']=8
        self.assertFalse(c.Workflow.same_published_content(after,record))
        self.assertNotEqual(c.snapshot(before),c.snapshot(after))

class DailySelectionTests(unittest.TestCase):
    def test_daily_policy_allows_tuesday_research(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'articles').mkdir();(root/'state').mkdir()
            (root/'automation-policy.json').write_text(json.dumps({'weekdays':['MON','TUE','WED','THU','FRI','SAT','SUN']}))
            with patch.object(a,'ROOT',root),patch.object(a,'now',return_value=dt.datetime(2026,10,6,15,tzinfo=c.KST)),patch.object(a,'Store',return_value=Mock(data={'posts':{}})),patch.object(a.news_sources,'collect') as collect:
                result=a.prepare()
                self.assertEqual(result['action'],'research_topics')
                self.assertEqual(result['id'],'it-news-2026-10-06')
                collect.assert_not_called()

class DailyGuardTests(unittest.TestCase):
    def test_all_seven_weekdays_and_wrong_date(self):
        import automation_guard as g
        with tempfile.TemporaryDirectory() as temp:
            policy=Path(temp)/'policy.json'
            policy.write_text(json.dumps({'publication_mode':'automatic_publish','execution_method':'codex_app','weekdays':['MON','TUE','WED','THU','FRI','SAT','SUN']}))
            for day in range(5,12):
                current=dt.datetime(2026,10,day,23,tzinfo=c.KST)
                with patch.object(g,'now',return_value=current):
                    g.publication_guard({'id':'it-news-'+current.date().isoformat(),'sources':[]},policy)
                    with self.assertRaises(c.WorkflowError):
                        g.publication_guard({'id':'it-news-2026-09-01','sources':[]},policy)
