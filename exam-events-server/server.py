"""Single-class exam event service. SQLite transactions protect concurrent submissions."""
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone, date
from http.cookies import SimpleCookie
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('DATA_DIR', ROOT / 'data'))
SECURE = os.environ.get('COOKIE_SECURE', 'true').lower() == 'true'
SESSIONS = ('1-1', '1-2', '2-1', '2-2')
KST = timezone(timedelta(hours=9))

class Problem(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message

def check(ok, message='입력 형식을 확인해주세요.', status=400):
    if not ok:
        raise Problem(status, message)

def blank():
    now = datetime.now(KST)
    year, exam = str(now.year), '1-1' if now.month < 8 else '2-1'
    return {'version': 3, 'activeYear': year, 'activeExam': exam,
            'years': {year: {'roster': [], 'sessions': {exam: {'students': [], 'exams': [], 'lottoPredWindow': {'start': '', 'end': ''}}}}}}

def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def password_hash(value):
    salt = secrets.token_hex(16)
    return salt + ':' + hashlib.pbkdf2_hmac('sha256', value.encode(), salt.encode(), 600000).hex()

def password_ok(value, stored):
    salt, expected = stored.split(':')
    return hmac.compare_digest(expected, hashlib.pbkdf2_hmac('sha256', value.encode(), salt.encode(), 600000).hex())

def connect():
    con = sqlite3.connect(DATA / 'events.sqlite3', timeout=20)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con

def init():
    DATA.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as con, con:
        con.execute('PRAGMA journal_mode=WAL')
        con.executescript('''
          CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL, revision INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS codes (year TEXT, student TEXT, hash TEXT UNIQUE, PRIMARY KEY(year,student));
          CREATE TABLE IF NOT EXISTS sessions (hash TEXT PRIMARY KEY, role TEXT, year TEXT, student TEXT, expires REAL);
          CREATE TABLE IF NOT EXISTS attempts (key TEXT PRIMARY KEY, count INTEGER, until REAL);
        ''')
        con.execute('INSERT OR IGNORE INTO state VALUES (1,?,0)', (encode(blank()),))
        if not con.execute("SELECT 1 FROM config WHERE key='password'").fetchone():
            pw = os.environ.get('ADMIN_PASSWORD', '')
            check(12 <= len(pw) <= 256, '서버 시작 전에 ADMIN_PASSWORD를 12~256자로 설정해주세요.')
            con.execute("INSERT INTO config VALUES ('password',?)", (password_hash(pw),))

def valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False

def validate(db):
    check(isinstance(db, dict) and db.get('version') == 3)
    years = db.get('years')
    check(isinstance(years, dict) and 1 <= len(years) <= 201)
    check(db.get('activeYear') in years and db.get('activeExam') in SESSIONS)
    for year, bucket in years.items():
        check(re.fullmatch(r'20\d\d|21\d\d|2200', year) and isinstance(bucket, dict))
        roster, sessions = bucket.get('roster'), bucket.get('sessions')
        check(isinstance(roster, list) and len(roster) <= 1000 and isinstance(sessions, dict))
        ids = set()
        for r in roster:
            check(isinstance(r, dict) and isinstance(r.get('id'), str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', r['id']))
            check(r['id'] not in ids and isinstance(r.get('name'), str) and 0 < len(r['name'].strip()) <= 100)
            ids.add(r['id'])
        for exam, entry in sessions.items():
            check(exam in SESSIONS and isinstance(entry, dict))
            students, exams = entry.get('students'), entry.get('exams', [])
            check(isinstance(students, list) and len(students) == len(ids))
            check(isinstance(exams, list) and len(exams) <= 500)
            seen = set()
            for s in students:
                check(isinstance(s, dict) and s.get('id') in ids and s['id'] not in seen)
                seen.add(s['id'])
                check(s.get('name') == next(r['name'] for r in roster if r['id'] == s['id']))
                for key in ('studyJoined', 'studyExcluded', 'plannerJoined', 'plannerExcluded'):
                    check(isinstance(s.get(key, False), bool))
                minutes = s.get('studyMinutes', '')
                check(minutes == '' or type(minutes) is int and 0 <= minutes <= 9007199254740991)
                check(isinstance(s.get('plannerDates', []), list) and len(s.get('plannerDates', [])) <= 10000)
                check(all(valid_date(d) for d in s.get('plannerDates', [])))
                check(isinstance(s.get('lotto', {}), dict) and len(s.get('lotto', {})) <= 500)
                for key, pair in s.get('lotto', {}).items():
                    check(re.fullmatch(r'eng|math|sci|hist|sub_[a-f0-9_]+', key) and isinstance(pair, dict))
                    for field in ('pred', 'actual'):
                        value = pair.get(field, '')
                        check(value == '' or isinstance(value, (str, int, float)) and not isinstance(value, bool))
                        if value != '':
                            try:
                                check(math.isfinite(float(value)) and 0 <= float(value) <= 100)
                            except (ValueError, TypeError):
                                raise Problem(400, '점수는 0~100 숫자로 입력해주세요.')
            for e in exams:
                check(isinstance(e, dict))
                for key, limit in [('id', 150), ('subject', 40), ('date', 10), ('period', 20), ('range', 3000), ('note', 1000), ('subjectKey', 1000)]:
                    check(isinstance(e.get(key, ''), str) and len(e.get(key, '')) <= limit)
                check(e.get('subject', '').strip())
                check(re.fullmatch(r'eng|math|sci|hist|sub_[a-f0-9_]+', e.get('subjectKey', '')))
                check(not e.get('date') or valid_date(e['date']))
            for key in ('lottoPredWindow', 'eventPeriod'):
                window = entry.get(key, {})
                check(isinstance(window, dict))
                check(all(not window.get(k) or valid_date(window[k]) for k in ('start', 'end')))
                check(not window.get('start') or not window.get('end') or window['start'] <= window['end'])
            if 'examDday' in entry:
                d = entry['examDday']
                check(isinstance(d, dict) and valid_date(d.get('date')) and isinstance(d.get('title', ''), str) and len(d.get('title', '')) <= 60)
    check(db['activeExam'] in years[db['activeYear']]['sessions'])
    return db

def read_state(con):
    r = con.execute('SELECT * FROM state WHERE id=1').fetchone()
    return json.loads(r['body']), r['revision']

def identity(con, env):
    cookie = SimpleCookie()
    try:
        cookie.load(env.get('HTTP_COOKIE', ''))
    except Exception:
        return None
    token = cookie.get('exam_session')
    return con.execute('SELECT * FROM sessions WHERE hash=? AND expires>?', (digest(token.value), time.time())).fetchone() if token else None

def require(user, role=None):
    check(user is not None, '로그인이 필요합니다.', 401)
    check(role is None or user['role'] == role, '권한이 없습니다.', 403)

def student_record(db, user):
    check(user['year'] == db['activeYear'], '학년도가 변경되었습니다. 선생님께 새 접속 코드를 받아주세요.', 403)
    entry = db['years'][db['activeYear']]['sessions'][db['activeExam']]
    student = next((s for s in entry['students'] if s['id'] == user['student']), None)
    check(student is not None, '명단에서 학생을 찾을 수 없습니다.', 403)
    return entry, student

def payload(db, revision, user):
    if user is None:
        return {'role': 'guest', 'data': blank(), 'revision': 0}
    if user['role'] == 'student':
        entry, student = student_record(db, user)
        entry = dict(entry, students=[student])
        db = dict(version=3, activeYear=db['activeYear'], activeExam=db['activeExam'], years={db['activeYear']: {'roster': [{'id': student['id'], 'name': student['name']}], 'sessions': {db['activeExam']: entry}}})
    return {'role': user['role'], 'data': db, 'revision': revision}

def cookie(token='', age=0):
    return ('Set-Cookie', f'exam_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={age}' + ('; Secure' if SECURE else ''))

def route(env, body, con):
    path, method = env.get('PATH_INFO', '/'), env['REQUEST_METHOD']
    user = identity(con, env)
    if method == 'GET' and path == '/api/health':
        return {'ok': True}, []
    if method == 'GET' and path == '/api/state':
        return payload(*read_state(con), user), []
    if path == '/api/login' and method == 'POST':
        # Shared bounded login budget works behind proxies without trusting forged IP headers.
        now = time.time()
        con.execute('BEGIN IMMEDIATE')
        con.execute('DELETE FROM attempts WHERE until<?', (now,))
        key = 'login'
        attempt = con.execute('SELECT * FROM attempts WHERE key=?', (key,)).fetchone()
        check(not attempt or attempt['count'] < 120, '로그인 시도가 많습니다. 잠시 후 다시 시도해주세요.', 429)
        con.execute('INSERT INTO attempts VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1', (key, now + 300))
        con.commit()
        value = body.get('password', '') if body.get('role') == 'teacher' else body.get('code', '')
        check(isinstance(value, str) and len(value) <= 256)
        if body.get('role') == 'teacher':
            stored = con.execute("SELECT value FROM config WHERE key='password'").fetchone()[0]
            check(password_ok(value, stored), '비밀번호가 맞지 않습니다.', 401)
            role, year, student = 'teacher', '', ''
        else:
            code = re.sub(r'[\s-]', '', value).upper()
            row = con.execute('SELECT * FROM codes WHERE hash=?', (digest(code),)).fetchone()
            check(row, '접속 코드가 맞지 않습니다.', 401)
            role, year, student = 'student', row['year'], row['student']
            student_record(read_state(con)[0], {'year': year, 'student': student})
        token = secrets.token_urlsafe(32)
        if user:
            con.execute('DELETE FROM sessions WHERE hash=?', (user['hash'],))
        con.execute('DELETE FROM sessions WHERE expires<?', (now,))
        con.execute('INSERT INTO sessions VALUES (?,?,?,?,?)', (digest(token), role, year, student, now + 28800))
        con.commit()
        return {'ok': True}, [cookie(token, 28800)]
    if path == '/api/logout' and method == 'POST':
        if user:
            con.execute('DELETE FROM sessions WHERE hash=?', (user['hash'],))
            con.commit()
        return {'ok': True}, [cookie()]
    if path == '/api/password' and method == 'POST':
        require(user, 'teacher')
        pw = body.get('password', '')
        check(isinstance(pw, str) and 12 <= len(pw) <= 256, '비밀번호는 12~256자로 입력해주세요.')
        con.execute("UPDATE config SET value=? WHERE key='password'", (password_hash(pw),))
        con.execute("DELETE FROM sessions WHERE role='teacher' AND hash<>?", (user['hash'],))
        con.commit()
        return {'ok': True}, []
    if path == '/api/state' and method == 'PUT':
        require(user, 'teacher')
        db = validate(body.get('data'))
        con.execute('BEGIN IMMEDIATE')
        _, revision = read_state(con)
        check(type(body.get('revision')) is int and body['revision'] == revision,
              '다른 기기에서 기록이 변경되었습니다. 최신 기록을 불러온 뒤 다시 수정해주세요.', 409)
        con.execute('UPDATE state SET body=?,revision=revision+1 WHERE id=1', (encode(db),))
        for row in con.execute('SELECT year,student FROM codes').fetchall():
            if row['year'] not in db['years'] or not any(r['id'] == row['student'] for r in db['years'][row['year']]['roster']):
                con.execute('DELETE FROM codes WHERE year=? AND student=?', tuple(row))
                con.execute("DELETE FROM sessions WHERE role='student' AND year=? AND student=?", tuple(row))
        con.commit()
        return {'revision': revision + 1}, []
    if path == '/api/codes' and method == 'POST':
        require(user, 'teacher')
        con.execute('BEGIN IMMEDIATE')
        db, _ = read_state(con)
        year = db['activeYear']
        roster = db['years'][year]['roster']
        if body.get('student'):
            roster = [r for r in roster if r['id'] == body['student']]
        check(roster, '먼저 학생 명단을 등록해주세요.')
        result = []
        for r in roster:
            raw = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(16))
            con.execute('INSERT INTO codes VALUES (?,?,?) ON CONFLICT(year,student) DO UPDATE SET hash=excluded.hash', (year, r['id'], digest(raw)))
            con.execute("DELETE FROM sessions WHERE role='student' AND year=? AND student=?", (year, r['id']))
            result.append(dict(name=r['name'], code='-'.join(raw[i:i+4] for i in range(0,16,4))))
        con.commit()
        return {'codes': result, 'year': year}, []
    if path == '/api/scores' and method == 'POST':
        require(user, 'student')
        con.execute('BEGIN IMMEDIATE')
        db, revision = read_state(con)
        check(body.get('year') == db['activeYear'] and body.get('exam') == db['activeExam'], '시험이 변경되었습니다. 새로고침 후 다시 입력해주세요.', 409)
        entry, student = student_record(db, user)
        mode, values = body.get('mode'), body.get('values')
        check(mode in ('pred', 'actual') and isinstance(values, dict))
        keys = {e['subjectKey'] for e in entry.get('exams', []) if re.sub(r'\s', '', e['subject']) != '자기주도학습'}
        check(keys and set(values) == keys, '시험 과목이 변경되었습니다. 새로고침 후 다시 입력해주세요.', 409)
        if mode == 'pred':
            w, today = entry.get('lottoPredWindow', {}), datetime.now(KST).date().isoformat()
            check((not w.get('start') or today >= w['start']) and (not w.get('end') or today <= w['end']), '지금은 예상 점수 입력 기간이 아닙니다.', 403)
        for key, value in values.items():
            check(isinstance(value, (str, int, float)) and not isinstance(value, bool) and value != '')
            try:
                n = float(value)
            except (ValueError, TypeError):
                raise Problem(400, '점수 형식을 확인해주세요.')
            check(math.isfinite(n) and (40 if mode == 'pred' else 0) <= n <= 100, '점수 범위를 확인해주세요.')
            student.setdefault('lotto', {}).setdefault(key, {'pred': '', 'actual': ''})[mode] = str(value)
        con.execute('UPDATE state SET body=?,revision=revision+1 WHERE id=1', (encode(db),))
        con.commit()
        return {'revision': revision + 1}, []
    raise Problem(404, '요청한 경로를 찾을 수 없습니다.')

def app(env, start_response):
    headers = [('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'), ('X-Frame-Options', 'DENY'), ('Referrer-Policy', 'no-referrer'), ('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")]
    status = 200
    try:
        if env['REQUEST_METHOD'] == 'GET' and env.get('PATH_INFO', '/') in ('/', '/student', '/teacher'):
            data = (ROOT / 'public' / 'index.html').read_bytes()
            headers.append(('Content-Type', 'text/html; charset=utf-8'))
        else:
            body = {}
            if env['REQUEST_METHOD'] not in ('GET', 'HEAD'):
                check(env.get('HTTP_X_EXAM_REQUEST') == '1', '잘못된 요청입니다.', 403)
                check(env.get('CONTENT_TYPE', '').split(';')[0] == 'application/json', 'JSON 요청이 필요합니다.', 415)
                length = int(env.get('CONTENT_LENGTH') or 0)
                check(0 <= length <= 20000000, '요청이 너무 큽니다.', 413)
                try:
                    body = json.loads(env['wsgi.input'].read(length))
                    check(isinstance(body, dict))
                except (ValueError, UnicodeDecodeError):
                    raise Problem(400, 'JSON 형식을 확인해주세요.')
            con = connect()
            try:
                result, extra = route(env, body, con)
            finally:
                con.close()
            headers.extend(extra)
            data = encode(result).encode()
            headers.append(('Content-Type', 'application/json; charset=utf-8'))
    except Problem as e:
        status, data = e.status, encode({'error': e.message}).encode()
        headers.append(('Content-Type', 'application/json; charset=utf-8'))
    except Exception:
        import traceback
        traceback.print_exc()
        status, data = 500, encode({'error': '서버에서 처리하지 못했습니다. 잠시 후 다시 시도해주세요.'}).encode()
        headers.append(('Content-Type', 'application/json; charset=utf-8'))
    from http import HTTPStatus
    headers.append(('Content-Length', str(len(data))))
    start_response(f'{status} {HTTPStatus(status).phrase}', headers)
    return [data]

if __name__ == '__main__':
    init()
    from waitress import serve
    serve(app, host='0.0.0.0', port=int(os.environ.get('PORT', '8080')), threads=8, max_request_body_size=20000000)
