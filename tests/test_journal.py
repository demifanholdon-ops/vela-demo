import copy
import tempfile
import unittest
from pathlib import Path
from backend import agents, journal
from backend.server import Application

class JournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.app=Application(Path(cls.tmp.name)/'journal.sqlite3')
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def test_no_auto_confirm_and_retry_no_duplicate(self):
        body={'text':'今天没有去散步。明天想给朋友打电话。','request_id':'retry-case-001'}
        result=self.app.post('/api/drafts',body)
        self.assertEqual(len(result['entries']),2)
        self.assertFalse(any(x['confirmed'] for x in result['entries']))
        self.assertIn('没有',result['entries'][0]['title'])
        self.assertEqual(result['entries'][1]['entry_type'],'plan')
        again=self.app.post('/api/drafts',body)
        self.assertEqual(again['entry_ids'],[x['id'] for x in result['entries']])

    def test_cloud_requires_separate_consent(self):
        with self.assertRaises(ValueError): self.app.post('/api/drafts',{'text':'hello','cloud':True,'request_id':'consent-case'})

    def test_model_cannot_remove_negation_or_invent(self):
        for title in ('去散步','已经康复'):
            result=journal.organize('今天没有去散步',True,lambda _: {'items':[{'title':title,'source_quote':title,'kind':'event'}]})
            self.assertEqual(result['processor'],'local_sentences')
            self.assertEqual(result['items'][0]['title'],'今天没有去散步')

    def test_good_grounded_cloud(self):
        result=journal.organize('今天没有去散步。',True,lambda _: {'items':[{'sentence_id':0,'kind':'event'}]})
        self.assertEqual(result['processor'],'cloud_draft')

    def test_edit_conflict_type_and_delete_history(self):
        entry=self.app.post('/api/entries',{'title':'明天打电话','kind':'plan'})
        updated=self.app.post('/api/entries/update',{'id':entry['id'],'revision':1,'title':'明天给朋友打电话','done':True})
        with self.assertRaises(ValueError):self.app.post('/api/entries/update',{'id':entry['id'],'revision':1,'title':'stale'})
        updated=self.app.post('/api/entries/update',{'id':entry['id'],'revision':2,'kind':'feeling','title':'今天有点累'})
        self.assertFalse(updated['done'])
        with self.assertRaises(ValueError):self.app.post('/api/entries/update',{'id':entry['id'],'done':True})
        self.app.post('/api/delete',{'id':entry['id']})
        self.assertFalse(any(x['entry_id']==entry['id'] for x in self.app.store.items('entry_revision')))

    def test_bad_session_not_approved_without_window(self):
        r=copy.deepcopy(self.app.report)
        for w in r['windows']:w['usable']=False
        self.assertEqual(agents.run(r)['trace'][0]['status'],'abstain')

    def test_window_payload_is_window_specific(self):
        r=copy.deepcopy(self.app.report)
        r['windows'][0]['gyro_norm_p95_rad_s']=1
        r['windows'][1]['gyro_norm_p95_rad_s']=2
        self.assertNotEqual(agents.cloud_payload(r,0)['selected_window'],agents.cloud_payload(r,1)['selected_window'])

    def test_skip_survives_other_feedback(self):
        feedback=[{'mode':'low','action_id':'water','result':'skip'}]+[{'mode':'high','action_id':'pause','result':'done'}]*20
        self.assertNotEqual(agents.run(self.app.report,'low',feedback=feedback)['action']['id'],'water')

    def test_custom_plan_and_distinct_effect_feedback(self):
        plan=self.app.post('/api/plans',{'mode':'high','text':'我自己选的方式'})
        run=self.app.post('/api/run',{'mode':'high'})
        self.assertEqual(run['result']['action']['id'],plan['id'])
        with self.assertRaises(ValueError):self.app.post('/api/feedback',{'run_id':run['id'],'result':'helpful'})
        self.app.post('/api/feedback',{'run_id':run['id'],'result':'start'})
        self.app.post('/api/feedback',{'run_id':run['id'],'result':'done'})
        self.app.post('/api/feedback',{'run_id':run['id'],'result':'unhelpful'})
        self.app.post('/api/feedback',{'run_id':run['id'],'result':'correct'})
        self.app.post('/api/feedback',{'run_id':run['id'],'result':'start'})

    def test_partial_window_exposes_coverage(self):
        for w in self.app.report['windows']:
            self.assertLessEqual(w['coverage'],1)
            if w['duration_s']<29.7:self.assertFalse(w['usable'])

    def test_no_silent_truncation(self):
        with self.assertRaises(ValueError):journal.organize('一句话。'*13)

    def test_deleting_draft_removes_shared_transcript(self):
        result=self.app.post('/api/drafts',{'text':'要删除的片段。保留的片段。','request_id':'delete-shared-source'})
        a,b=result['entries']
        self.app.post('/api/entries/update',{'id':b['id'],'title':'保留的片段更新'})
        self.app.post('/api/delete',{'id':a['id']})
        self.assertNotIn('source_text',self.app.store.get(b['id']))
        for version in self.app.store.items('entry_revision'):
            if version['entry_id']==b['id']:self.assertNotIn('source_text',version['previous'])
