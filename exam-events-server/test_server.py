import copy
import io
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import server

def request(path, method='GET', body=None, cookie='', custom=True):
    raw = json.dumps(body or {}).encode()
    env = {'PATH_INFO': path, 'REQUEST_METHOD': method, 'CONTENT_LENGTH': str(len(raw)),
           'CONTENT_TYPE': 'application/json', 'HTTP_COOKIE': cookie, 'wsgi.input': io.BytesIO(raw)}
    if custom:
        env['HTTP_X_EXAM_REQUEST'] = '1'
    meta = {}
    def start(status, headers):
        meta.update(status=int(status.split()[0]), headers=dict(headers))
    result = b''.join(server.app(env, start))
    return meta['status'], json.loads(result), meta['headers']

class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        server.DATA = Path(self.tmp.name)
        os.environ['ADMIN_PASSWORD'] = 'local-test-password-12345'
        server.init()
        status, _, headers = request('/api/login', 'POST', {'role': 'teacher', 'password': os.environ['ADMIN_PASSWORD']})
        self.assertEqual(status, 200)
        self.teacher = headers['Set-Cookie'].split(';')[0]
        _, self.initial, _ = request('/api/state', cookie=self.teacher)
        self.db = self.initial['data']
        year, exam = self.db['activeYear'], self.db['activeExam']
        self.entry = self.db['years'][year]['sessions'][exam]
        roster = [{'id': 's1', 'name': '테스트학생가'}, {'id': 's2', 'name': '테스트학생나'}]
        self.db['years'][year]['roster'] = roster
        self.entry['students'] = [dict(r, lotto={'math': {'pred': '', 'actual': ''}}, studyMinutes=0) for r in roster]
        self.entry['exams'] = [{'id': 'e1', 'subject': '수학', 'subjectKey': 'math', 'date': '', 'period': '', 'range': '', 'note': ''}]
        self.assertEqual(self.save(self.db, 0)[0], 200)
        _, codes, _ = request('/api/codes', 'POST', {}, self.teacher)
        self.codes = codes['codes']
        self.students = []
        for row in self.codes:
            status, _, headers = request('/api/login', 'POST', {'code': row['code']})
            self.assertEqual(status, 200)
            self.students.append(headers['Set-Cookie'].split(';')[0])

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, data, revision):
        return request('/api/state', 'PUT', {'data': data, 'revision': revision}, self.teacher)

    def score(self, cookie, value=80, **extra):
        body = {'year': self.db['activeYear'], 'exam': self.db['activeExam'], 'mode': 'pred', 'values': {'math': value}}
        body.update(extra)
        return request('/api/scores', 'POST', body, cookie)

    def test_auth_and_privacy(self):
        _, guest, _ = request('/api/state')
        self.assertNotIn('테스트학생', json.dumps(guest, ensure_ascii=False))
        self.assertEqual(request('/api/state', 'PUT', {'data': self.db, 'revision': 1})[0], 401)
        self.assertEqual(request('/api/state', 'PUT', {'data': self.db, 'revision': 1}, self.students[0])[0], 403)
        _, own, _ = request('/api/state', cookie=self.students[0])
        self.assertIn('테스트학생가', json.dumps(own, ensure_ascii=False))
        self.assertNotIn('테스트학생나', json.dumps(own, ensure_ascii=False))
        self.assertEqual(request('/api/codes', 'POST', {}, self.students[0])[0], 403)
        self.assertEqual(request('/api/login', 'POST', {'role': 'teacher', 'password': 'wrong'})[0], 401)
        self.assertEqual(request('/api/logout', 'POST', {}, self.teacher, custom=False)[0], 403)

    def test_concurrent_students_and_teacher_conflict(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda pair: self.score(*pair), zip(self.students, [81, 92])))
        self.assertEqual([r[0] for r in results], [200, 200])
        self.assertEqual(self.save(self.db, 1)[0], 409)
        _, fresh, _ = request('/api/state', cookie=self.teacher)
        entries = fresh['data']['years'][self.db['activeYear']]['sessions'][self.db['activeExam']]['students']
        self.assertEqual([s['lotto']['math']['pred'] for s in entries], ['81', '92'])
        server.init()  # Reopening/reinitializing the service preserves submitted data.
        self.assertEqual(request('/api/state', cookie=self.teacher)[1]['revision'], 3)

    def test_period_scores_context_and_tampering(self):
        for value in [39, 101, '', 'abc', float('nan'), True]:
            self.assertEqual(self.score(self.students[0], value)[0], 400)
        self.assertEqual(self.score(self.students[0], 80, student='s2')[0], 200)
        _, own2, _ = request('/api/state', cookie=self.students[1])
        entry = own2['data']['years'][self.db['activeYear']]['sessions'][self.db['activeExam']]
        self.assertEqual(entry['students'][0]['lotto']['math']['pred'], '')
        self.assertEqual(self.score(self.students[0], exam='1-2' if self.db['activeExam'] != '1-2' else '2-1')[0], 409)
        self.entry['lottoPredWindow'] = {'start': '2000-01-01', 'end': '2000-01-02'}
        self.assertEqual(self.save(self.db, 2)[0], 200)
        self.assertEqual(self.score(self.students[0])[0], 403)
        self.assertEqual(self.score(self.students[0], 0, mode='actual')[0], 200)

    def test_revocation_restore_and_validation(self):
        malformed = copy.deepcopy(self.db)
        malformed['years'][self.db['activeYear']]['roster'][0]['id'] = '<script>'
        self.assertEqual(self.save(malformed, 1)[0], 400)
        self.assertEqual(request('/api/codes', 'POST', {'student': 's1'}, self.teacher)[0], 200)
        self.assertEqual(self.score(self.students[0])[0], 401)
        self.assertEqual(request('/api/login', 'POST', {'code': self.codes[0]['code']})[0], 401)
        self.assertEqual(self.save(self.db, 1)[0], 200)
        self.assertEqual(request('/api/password', 'POST', {'password': 'changed-password-123456'}, self.teacher)[0], 200)
        self.assertEqual(request('/api/login', 'POST', {'role': 'teacher', 'password': os.environ['ADMIN_PASSWORD']})[0], 401)
        self.assertEqual(request('/api/logout', 'POST', {}, self.teacher)[0], 200)
        self.assertEqual(self.save(self.db, 2)[0], 401)

if __name__ == '__main__':
    unittest.main(verbosity=2)
