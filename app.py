from flask import Flask, request, jsonify, session, send_file, render_template_string
import json, os, random, string, hashlib, jwt, csv, io

DATABASE_URL = os.environ.get('DATABASE_URL', '')
if DATABASE_URL:
    import psycopg2
    import psycopg2.extras
    USE_PG = True
else:
    import sqlite3
    USE_PG = False
from datetime import datetime, timedelta
from functools import wraps
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

app = Flask(__name__, static_folder='public', static_url_path='/static')
app.secret_key = 'exam_system_secret_2024_!@#'
JWT_SECRET = 'jwt_exam_secret_2024'
DB_PATH = os.environ.get('DB_PATH', 'data/exam_system.db')

# ─── SCHOOL CONFIG ────────────────────────────────────────────────────────────
SCHOOL_CONFIG = {
    "name_ar": "مدرسة الرازي حلقة ثانية بنين",
    "name_en": "Al-Razi Boys School Cycle 2",
    "logo": "/static/images/logo.png",
    "address": "دبي، الامارات العربية المتحدة",
    "phone": "",
    "email": "",
    "copyright": "جميع الحقوق محفوظة : مدرسة الرازي - مديرة المدرسة أ. بدرية سيف - تصميم : هاني ابوالدهب",
    "banner_color": "#1a3a5c"
}

# ─── DATABASE ─────────────────────────────────────────────────────────────────
def get_db():
    if USE_PG:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn
    else:
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(DB_PATH)
        conn.row_factory = _sqlite3.Row
        db_execute(conn, "PRAGMA journal_mode=WAL")
        return conn

def fetchall(cursor):
    if USE_PG:
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    return [dict(r) for r in cursor.fetchall()]

def fetchone(cursor):
    if USE_PG:
        row = cursor.fetchone()
        if row is None: return None
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))
    row = cursor.fetchone()
    return dict(row) if row else None

def init_db():
    os.makedirs('data', exist_ok=True)
    os.makedirs('public/images', exist_ok=True)
    conn = get_db()
    c = conn.cursor()

    tables = [
        '''CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            full_name_ar TEXT,
            full_name_en TEXT,
            email TEXT,
            student_code TEXT UNIQUE,
            class_name TEXT,
            grade TEXT,
            created_at TEXT DEFAULT 'now'
        )''',
        '''CREATE TABLE IF NOT EXISTS subjects (
            id SERIAL PRIMARY KEY,
            name_ar TEXT NOT NULL,
            name_en TEXT NOT NULL,
            code TEXT UNIQUE NOT NULL,
            teacher_id INTEGER,
            grade TEXT,
            color TEXT DEFAULT '#3b82f6',
            icon TEXT DEFAULT '📚'
        )''',
        '''CREATE TABLE IF NOT EXISTS question_bank (
            id SERIAL PRIMARY KEY,
            subject_id INTEGER NOT NULL,
            question_ar TEXT NOT NULL,
            question_en TEXT,
            type TEXT NOT NULL,
            options_ar TEXT,
            options_en TEXT,
            correct_answer TEXT,
            points REAL DEFAULT 1,
            difficulty TEXT DEFAULT 'medium',
            skill_tag TEXT,
            created_by INTEGER,
            created_at TEXT DEFAULT 'now'
        )''',
        '''CREATE TABLE IF NOT EXISTS exams (
            id SERIAL PRIMARY KEY,
            title_ar TEXT NOT NULL,
            title_en TEXT,
            subject_id INTEGER NOT NULL,
            teacher_id INTEGER NOT NULL,
            instructions_ar TEXT,
            instructions_en TEXT,
            duration_minutes INTEGER DEFAULT 60,
            total_points INTEGER DEFAULT 100,
            pass_score INTEGER DEFAULT 50,
            start_time TEXT,
            end_time TEXT,
            status TEXT DEFAULT 'draft',
            question_ids TEXT,
            randomize_questions INTEGER DEFAULT 0,
            randomize_options INTEGER DEFAULT 0,
            created_at TEXT DEFAULT 'now'
        )''',
        '''CREATE TABLE IF NOT EXISTS exam_access (
            id SERIAL PRIMARY KEY,
            exam_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            access_code TEXT UNIQUE NOT NULL,
            used INTEGER DEFAULT 0,
            used_at TEXT
        )''',
        '''CREATE TABLE IF NOT EXISTS exam_sessions (
            id SERIAL PRIMARY KEY,
            exam_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            start_time TEXT DEFAULT 'now',
            end_time TEXT,
            status TEXT DEFAULT 'in_progress',
            time_remaining INTEGER
        )''',
        '''CREATE TABLE IF NOT EXISTS student_answers (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            answer TEXT,
            is_correct INTEGER,
            points_earned REAL DEFAULT 0,
            teacher_grade REAL,
            teacher_feedback TEXT,
            answered_at TEXT DEFAULT 'now'
        )''',
        '''CREATE TABLE IF NOT EXISTS exam_results (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            exam_id INTEGER NOT NULL,
            total_score REAL DEFAULT 0,
            percentage REAL DEFAULT 0,
            grade_letter TEXT,
            passed INTEGER DEFAULT 0,
            submitted_at TEXT DEFAULT 'now'
        )''',
        '''CREATE TABLE IF NOT EXISTS school_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )'''
    ]

    for sql in tables:
        if USE_PG:
            c.execute(sql)
        else:
            import sqlite3 as _sq
            db_execute(conn, sql.replace('SERIAL PRIMARY KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT'))

    conn.commit()

    # Default admin - only if not exists
    admin_hash = hash_password('admin123')
    if USE_PG:
        c.execute('INSERT INTO users (username,password_hash,role,full_name_ar,full_name_en) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(username) DO NOTHING',
                  ('admin', admin_hash, 'admin', 'مدير النظام', 'System Admin'))
        # Only insert school settings if they don't exist - never overwrite
        for k, v in SCHOOL_CONFIG.items():
            c.execute('INSERT INTO school_settings VALUES (%s,%s) ON CONFLICT(key) DO NOTHING', (k, str(v)))
    else:
        c.execute('INSERT OR IGNORE INTO users (username,password_hash,role,full_name_ar,full_name_en) VALUES (?,?,?,?,?)',
                  ('admin', admin_hash, 'admin', 'مدير النظام', 'System Admin'))
        # Only insert school settings if they don't exist - never overwrite
        for k, v in SCHOOL_CONFIG.items():
            c.execute('INSERT OR IGNORE INTO school_settings VALUES (?,?)', (k, str(v)))

    conn.commit()
    conn.close()

def hash_password(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

def qmark(sql):
    """Convert ? placeholders to %s for PostgreSQL"""
    if USE_PG:
        return sql.replace('?', '%s')
    return sql

def db_fetchall(conn, sql, params=()):
    c = conn.cursor()
    c.execute(qmark(sql), params)
    if USE_PG:
        cols = [d[0] for d in c.description]
        return [dict(zip(cols, row)) for row in c.fetchall()]
    return [dict(r) for r in c.fetchall()]

def db_fetchone(conn, sql, params=()):
    c = conn.cursor()
    c.execute(qmark(sql), params)
    if USE_PG:
        row = c.fetchone()
        if row is None: return None
        cols = [d[0] for d in c.description]
        return dict(zip(cols, row))
    row = c.fetchone()
    return dict(row) if row else None

def db_execute(conn, sql, params=()):
    c = conn.cursor()
    c.execute(qmark(sql), params)
    return c

def db_execute_returning(conn, sql, params=()):
    """Execute INSERT and return lastrowid"""
    c = conn.cursor()
    if USE_PG:
        sql2 = qmark(sql)
        if 'RETURNING' not in sql2.upper():
            sql2 += ' RETURNING id'
        c.execute(sql2, params)
        row = c.fetchone()
        return row[0] if row else None
    else:
        c.execute(sql, params)
        return c.lastrowid

def generate_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

# ─── AUTH ─────────────────────────────────────────────────────────────────────
def create_token(user_id, role):
    payload = {'user_id': user_id, 'role': role,
                'exp': datetime.utcnow() + timedelta(hours=12)}
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')

def token_required(roles=None):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            token = request.headers.get('Authorization', '').replace('Bearer ', '')
            if not token:
                return jsonify({'error': 'No token'}), 401
            try:
                data = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
                if roles and data['role'] not in roles:
                    return jsonify({'error': 'Forbidden'}), 403
                request.user = data
                return f(*args, **kwargs)
            except jwt.ExpiredSignatureError:
                return jsonify({'error': 'Token expired'}), 401
            except:
                return jsonify({'error': 'Invalid token'}), 401
        return decorated
    return decorator

# ─── ROUTES: AUTH ─────────────────────────────────────────────────────────────
@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db()
    user = db_fetchone(conn, 'SELECT * FROM users WHERE username=?', (data['username'],))
    conn.close()
    if not user or user['password_hash'] != hash_password(data['password']):
        return jsonify({'error': 'بيانات الدخول غير صحيحة / Invalid credentials'}), 401
    token = create_token(user['id'], user['role'])
    return jsonify({'token': token, 'role': user['role'], 'name': user['full_name_ar'],
                    'user_id': user['id']})

@app.route('/api/auth/me', methods=['GET'])
@token_required()
def me():
    conn = get_db()
    user = db_execute(conn, 'SELECT id, username, role, full_name_ar, full_name_en, email, class_name, grade FROM users WHERE id=?',
                        (request.user['user_id'],)).fetchone()
    conn.close()
    return jsonify(dict(user))

# ─── ROUTES: SCHOOL SETTINGS ──────────────────────────────────────────────────
@app.route('/api/settings', methods=['GET'])
def get_settings():
    conn = get_db()
    rows = db_fetchall(conn, 'SELECT key, value FROM school_settings')
    conn.close()
    return jsonify({r['key']: r['value'] for r in rows})

@app.route('/api/settings', methods=['PUT'])
@token_required(['admin'])
def update_settings():
    data = request.json
    conn = get_db()
    for k, v in data.items():
        db_execute(conn, 'INSERT OR REPLACE INTO school_settings VALUES (?, ?)', (k, str(v)))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ─── ROUTES: USERS ────────────────────────────────────────────────────────────
@app.route('/api/users', methods=['GET'])
@token_required(['admin', 'teacher'])
def get_users():
    role = request.args.get('role', '')
    conn = get_db()
    if role:
        users = db_fetchall(conn, 'SELECT id, username, role, full_name_ar, full_name_en, email, student_code, class_name, grade FROM users WHERE role=? ORDER BY full_name_ar', (role,))
    else:
        users = db_fetchall(conn, 'SELECT id, username, role, full_name_ar, full_name_en, email, student_code, class_name, grade FROM users ORDER BY role, full_name_ar')
    conn.close()
    return jsonify([dict(u) for u in users])

@app.route('/api/users', methods=['POST'])
@token_required(['admin'])
def create_user():
    data = request.json
    conn = get_db()
    code = generate_code(6) if data.get('role') == 'student' else None
    try:
        db_execute(conn, '''INSERT INTO users (username, password_hash, role, full_name_ar, full_name_en, email, student_code, class_name, grade)
                       VALUES (?,?,?,?,?,?,?,?,?)''',
                    (data['username'], hash_password(data.get('password', '123456')),
                     data['role'], data.get('full_name_ar'), data.get('full_name_en'),
                     data.get('email'), code, data.get('class_name'), data.get('grade')))
        conn.commit()
        return jsonify({'success': True, 'student_code': code})
    except Exception as e:
        return jsonify({'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/users/<int:uid>', methods=['PUT'])
@token_required(['admin'])
def update_user(uid):
    data = request.json
    conn = get_db()
    fields = []
    vals = []
    for f in ['full_name_ar', 'full_name_en', 'email', 'class_name', 'grade']:
        if f in data:
            fields.append(f'{f}=?')
            vals.append(data[f])
    if 'password' in data and data['password']:
        fields.append('password_hash=?')
        vals.append(hash_password(data['password']))
    vals.append(uid)
    db_execute(conn, f'UPDATE users SET {", ".join(fields)} WHERE id=?', vals)
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/users/<int:uid>', methods=['DELETE'])
@token_required(['admin'])
def delete_user(uid):
    conn = get_db()
    db_execute(conn, 'DELETE FROM users WHERE id=?', (uid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/users/import', methods=['POST'])
@token_required(['admin'])
def import_students():
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file'}), 400

    filename = file.filename.lower()
    rows = []

    try:
        if filename.endswith('.xlsx') or filename.endswith('.xls'):
            # Read Excel file
            import openpyxl
            file_bytes = io.BytesIO(file.read())
            wb = openpyxl.load_workbook(file_bytes, data_only=True)
            ws = wb.active
            headers = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                # Skip empty rows
                if all(v is None for v in row):
                    continue
                # Find header row (contains 'username')
                if not headers:
                    row_vals = [str(v).strip() if v else '' for v in row]
                    if 'username' in row_vals:
                        headers = row_vals
                    continue
                # Data row
                row_dict = {}
                for j, val in enumerate(row):
                    if j < len(headers) and headers[j]:
                        row_dict[headers[j]] = str(val).strip() if val is not None else ''
                if row_dict.get('username') or row_dict.get('full_name_ar'):
                    rows.append(row_dict)
        else:
            # Read CSV file
            content = file.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(content))
            for row in reader:
                rows.append(dict(row))
    except Exception as e:
        return jsonify({'error': f'خطأ في قراءة الملف: {str(e)}'}), 400

    conn = get_db()
    created = 0
    skipped = 0
    errors = []

    for row in rows:
        try:
            username = str(row.get('username') or '').strip()
            name_ar = str(row.get('full_name_ar') or '').strip()

            if not username and not name_ar:
                continue

            if not username:
                username = f"st{generate_code(6).lower()}"

            # Check if username already exists
            existing = db_fetchone(conn, 'SELECT id FROM users WHERE username=?', (username,))
            if existing:
                skipped += 1
                continue

            code = generate_code(6)
            password = str(row.get('password') or '123456').strip() or '123456'

            db_execute(conn, '''INSERT INTO users (username, password_hash, role, full_name_ar, full_name_en, email, student_code, class_name, grade)
                           VALUES (?,?,?,?,?,?,?,?,?)''',
                        (username, hash_password(password),
                         'student', name_ar,
                         str(row.get('full_name_en') or '').strip(),
                         str(row.get('email') or '').strip(),
                         code,
                         str(row.get('class_name') or '').strip(),
                         str(row.get('grade') or '').strip()))
            created += 1
        except Exception as e:
            errors.append(f"{row.get('username','?')}: {str(e)}")

    conn.commit()
    conn.close()
    return jsonify({'created': created, 'skipped': skipped, 'errors': errors})

# ─── ROUTES: SUBJECTS ─────────────────────────────────────────────────────────
@app.route('/api/subjects', methods=['GET'])
@token_required()
def get_subjects():
    conn = get_db()
    subjects = db_execute(conn, '''SELECT s.*, u.full_name_ar as teacher_name
                               FROM subjects s LEFT JOIN users u ON s.teacher_id=u.id
                               ORDER BY s.name_ar''').fetchall()
    conn.close()
    return jsonify([dict(s) for s in subjects])

@app.route('/api/subjects', methods=['POST'])
@token_required(['admin'])
def create_subject():
    data = request.json
    conn = get_db()
    try:
        db_execute(conn, 'INSERT INTO subjects (name_ar, name_en, code, teacher_id, grade, color, icon) VALUES (?,?,?,?,?,?,?)',
                    (data['name_ar'], data.get('name_en'), data['code'],
                     data.get('teacher_id'), data.get('grade'),
                     data.get('color', '#3b82f6'), data.get('icon', '📚')))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/subjects/<int:sid>', methods=['PUT'])
@token_required(['admin'])
def update_subject(sid):
    data = request.json
    conn = get_db()
    db_execute(conn, 'UPDATE subjects SET name_ar=?, name_en=?, teacher_id=?, grade=?, color=?, icon=? WHERE id=?',
                (data['name_ar'], data.get('name_en'), data.get('teacher_id'),
                 data.get('grade'), data.get('color'), data.get('icon'), sid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/subjects/<int:sid>', methods=['DELETE'])
@token_required(['admin'])
def delete_subject(sid):
    conn = get_db()
    db_execute(conn, 'DELETE FROM subjects WHERE id=?', (sid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ─── ROUTES: QUESTION BANK ────────────────────────────────────────────────────
@app.route('/api/questions', methods=['GET'])
@token_required(['admin', 'teacher'])
def get_questions():
    subject_id = request.args.get('subject_id')
    conn = get_db()
    if subject_id:
        qs = db_fetchall(conn, 'SELECT q.*, s.name_ar as subject_name FROM question_bank q JOIN subjects s ON q.subject_id=s.id WHERE q.subject_id=? ORDER BY q.id DESC', (subject_id,))
    else:
        qs = db_fetchall(conn, 'SELECT q.*, s.name_ar as subject_name FROM question_bank q JOIN subjects s ON q.subject_id=s.id ORDER BY q.id DESC')
    conn.close()
    return jsonify([dict(q) for q in qs])

@app.route('/api/questions', methods=['POST'])
@token_required(['admin', 'teacher'])
def create_question():
    data = request.json
    conn = get_db()
    db_execute(conn, '''INSERT INTO question_bank (subject_id, question_ar, question_en, type, options_ar, options_en, correct_answer, points, difficulty, skill_tag, created_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (data['subject_id'], data['question_ar'], data.get('question_en'),
                 data['type'], json.dumps(data.get('options_ar', [])),
                 json.dumps(data.get('options_en', [])),
                 data.get('correct_answer'), data.get('points', 1),
                 data.get('difficulty', 'medium'), data.get('skill_tag'),
                 request.user['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/questions/<int:qid>', methods=['PUT'])
@token_required(['admin', 'teacher'])
def update_question(qid):
    data = request.json
    conn = get_db()
    db_execute(conn, '''UPDATE question_bank SET subject_id=?, question_ar=?, question_en=?, type=?,
                   options_ar=?, options_en=?, correct_answer=?, points=?, difficulty=?, skill_tag=?
                   WHERE id=?''',
                (data['subject_id'], data['question_ar'], data.get('question_en'),
                 data['type'], json.dumps(data.get('options_ar', [])),
                 json.dumps(data.get('options_en', [])),
                 data.get('correct_answer'), data.get('points', 1),
                 data.get('difficulty', 'medium'), data.get('skill_tag'), qid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/questions/<int:qid>', methods=['DELETE'])
@token_required(['admin', 'teacher'])
def delete_question(qid):
    conn = get_db()
    db_execute(conn, 'DELETE FROM question_bank WHERE id=?', (qid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ─── ROUTES: EXAMS ────────────────────────────────────────────────────────────
@app.route('/api/exams', methods=['GET'])
@token_required(['admin', 'teacher'])
def get_exams():
    conn = get_db()
    uid = request.user['user_id']
    role = request.user['role']
    if role == 'admin':
        exams = db_execute(conn, '''SELECT e.*, s.name_ar as subject_name, u.full_name_ar as teacher_name
                                FROM exams e JOIN subjects s ON e.subject_id=s.id
                                JOIN users u ON e.teacher_id=u.id ORDER BY e.created_at DESC''').fetchall()
    else:
        exams = db_execute(conn, '''SELECT e.*, s.name_ar as subject_name, u.full_name_ar as teacher_name
                                FROM exams e JOIN subjects s ON e.subject_id=s.id
                                JOIN users u ON e.teacher_id=u.id
                                WHERE e.teacher_id=? ORDER BY e.created_at DESC''', (uid,)).fetchall()
    conn.close()
    return jsonify([dict(e) for e in exams])

@app.route('/api/exams', methods=['POST'])
@token_required(['admin', 'teacher'])
def create_exam():
    data = request.json
    conn = get_db()
    cursor = db_execute(conn, '''INSERT INTO exams (title_ar, title_en, subject_id, teacher_id, instructions_ar, instructions_en,
                             duration_minutes, total_points, pass_score, start_time, end_time, question_ids,
                             randomize_questions, randomize_options)
                             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                         (data['title_ar'], data.get('title_en'), data['subject_id'],
                          request.user['user_id'], data.get('instructions_ar'), data.get('instructions_en'),
                          data.get('duration_minutes', 60), data.get('total_points', 100),
                          data.get('pass_score', 50), data.get('start_time'), data.get('end_time'),
                          json.dumps(data.get('question_ids', [])),
                          1 if data.get('randomize_questions') else 0,
                          1 if data.get('randomize_options') else 0))
    conn.commit()
    exam_id = cursor.lastrowid if not USE_PG else cursor
    conn.close()
    return jsonify({'success': True, 'exam_id': exam_id})

@app.route('/api/exams/<int:eid>', methods=['PUT'])
@token_required(['admin', 'teacher'])
def update_exam(eid):
    data = request.json
    conn = get_db()
    db_execute(conn, '''UPDATE exams SET title_ar=?, title_en=?, subject_id=?, instructions_ar=?, instructions_en=?,
                   duration_minutes=?, total_points=?, pass_score=?, start_time=?, end_time=?,
                   question_ids=?, randomize_questions=?, randomize_options=?, status=?
                   WHERE id=?''',
                (data['title_ar'], data.get('title_en'), data['subject_id'],
                 data.get('instructions_ar'), data.get('instructions_en'),
                 data.get('duration_minutes', 60), data.get('total_points', 100),
                 data.get('pass_score', 50), data.get('start_time'), data.get('end_time'),
                 json.dumps(data.get('question_ids', [])),
                 1 if data.get('randomize_questions') else 0,
                 1 if data.get('randomize_options') else 0,
                 data.get('status', 'draft'), eid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/exams/<int:eid>', methods=['DELETE'])
@token_required(['admin', 'teacher'])
def delete_exam(eid):
    conn = get_db()
    db_execute(conn, 'DELETE FROM exams WHERE id=?', (eid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# Generate access codes for students
@app.route('/api/exams/<int:eid>/generate-codes', methods=['POST'])
@token_required(['admin', 'teacher'])
def generate_codes(eid):
    data = request.json
    student_ids = data.get('student_ids', [])
    conn = get_db()
    codes = []
    for sid in student_ids:
        # Check if code already exists
        existing = db_fetchone(conn, 'SELECT access_code FROM exam_access WHERE exam_id=? AND student_id=?', (eid, sid))
        if existing:
            codes.append({'student_id': sid, 'code': existing['access_code']})
        else:
            code = generate_code(8)
            db_execute(conn, 'INSERT INTO exam_access (exam_id, student_id, access_code) VALUES (?,?,?)', (eid, sid, code))
            codes.append({'student_id': sid, 'code': code})
    conn.commit()
    # Enrich with student names
    result = []
    for c in codes:
        student = db_fetchone(conn, 'SELECT full_name_ar, class_name FROM users WHERE id=?', (c['student_id'],))
        result.append({**c, 'name': student['full_name_ar'] if student else '', 'class': student['class_name'] if student else ''})
    conn.close()
    return jsonify(result)

# ─── ROUTES: EXAM TAKING ──────────────────────────────────────────────────────
@app.route('/api/exam/enter', methods=['POST'])
def enter_exam():
    """Student enters exam with access code"""
    data = request.json
    code = data.get('code', '').strip().upper()
    conn = get_db()
    access = db_execute(conn, '''SELECT ea.*, e.title_ar, e.duration_minutes, e.status, e.start_time, e.end_time
                             FROM exam_access ea JOIN exams e ON ea.exam_id=e.id
                             WHERE ea.access_code=?''', (code,)).fetchone()
    if not access:
        conn.close()
        return jsonify({'error': 'كود الامتحان غير صحيح / Invalid exam code'}), 404
    if access['used']:
        conn.close()
        return jsonify({'error': 'تم استخدام هذا الكود مسبقاً / Code already used'}), 400
    if access['status'] != 'active':
        conn.close()
        return jsonify({'error': 'الامتحان غير متاح الآن / Exam not available'}), 400

    # Check if student already has a session
    existing_session = db_execute(conn, '''SELECT es.* FROM exam_sessions es
                                       WHERE es.exam_id=? AND es.student_id=? AND es.status='in_progress' ''',
                                   (access['exam_id'], access['student_id'])).fetchone()
    if existing_session:
        conn.close()
        token = create_token(access['student_id'], 'student')
        return jsonify({'session_id': existing_session['id'], 'token': token,
                        'exam_id': access['exam_id'], 'resume': True})

    # Create session
    session_cursor = db_execute(conn, 'INSERT INTO exam_sessions (exam_id, student_id) VALUES (?,?)',
                                  (access['exam_id'], access['student_id']))
    session_id = session_cursor if USE_PG else session_cursor.lastrowid
    db_execute(conn, 'UPDATE exam_access SET used=1, used_at=datetime("now") WHERE access_code=?', (code,))
    conn.commit()
    conn.close()
    token = create_token(access['student_id'], 'student')
    return jsonify({'session_id': session_id, 'token': token, 'exam_id': access['exam_id']})

@app.route('/api/exam/session/<int:session_id>/questions', methods=['GET'])
@token_required(['student'])
def get_exam_questions(session_id):
    conn = get_db()
    session_row = db_execute(conn, 'SELECT * FROM exam_sessions WHERE id=? AND student_id=?',
                               (session_id, request.user['user_id'])).fetchone()
    if not session_row:
        conn.close()
        return jsonify({'error': 'Session not found'}), 404

    exam = db_fetchone(conn, 'SELECT * FROM exams WHERE id=?', (session_row['exam_id'],))
    question_ids = json.loads(exam['question_ids'])

    if exam['randomize_questions']:
        random.shuffle(question_ids)

    questions = []
    for qid in question_ids:
        q = db_fetchone(conn, 'SELECT * FROM question_bank WHERE id=?', (qid,))
        if q:
            qd = dict(q)
            qd['options_ar'] = json.loads(q['options_ar'] or '[]')
            qd['options_en'] = json.loads(q['options_en'] or '[]')
            if exam['randomize_options'] and qd['options_ar']:
                indices = list(range(len(qd['options_ar'])))
                random.shuffle(indices)
                qd['options_ar'] = [qd['options_ar'][i] for i in indices]
                if qd['options_en']:
                    qd['options_en'] = [qd['options_en'][i] for i in indices]
            # Don't send correct answer to student
            qd.pop('correct_answer', None)
            questions.append(qd)

    # Calculate time remaining
    start = datetime.fromisoformat(session_row['start_time'])
    elapsed = (datetime.utcnow() - start).total_seconds()
    time_remaining = max(0, exam['duration_minutes'] * 60 - elapsed)

    # Get existing answers
    answers = db_fetchall(conn, 'SELECT question_id, answer FROM student_answers WHERE session_id=?', (session_id,))
    answers_map = {a['question_id']: a['answer'] for a in answers}

    conn.close()
    return jsonify({
        'exam': {'id': exam['id'], 'title_ar': exam['title_ar'], 'title_en': exam['title_en'],
                 'duration_minutes': exam['duration_minutes'], 'instructions_ar': exam['instructions_ar'],
                 'instructions_en': exam['instructions_en'], 'total_points': exam['total_points']},
        'questions': questions,
        'time_remaining': int(time_remaining),
        'answers': answers_map
    })

@app.route('/api/exam/session/<int:session_id>/answer', methods=['POST'])
@token_required(['student'])
def save_answer(session_id):
    data = request.json
    conn = get_db()
    # Check/upsert answer
    existing = db_execute(conn, 'SELECT id FROM student_answers WHERE session_id=? AND question_id=?',
                            (session_id, data['question_id'])).fetchone()
    if existing:
        db_execute(conn, 'UPDATE student_answers SET answer=?, answered_at=datetime("now") WHERE session_id=? AND question_id=?',
                    (data['answer'], session_id, data['question_id']))
    else:
        db_execute(conn, 'INSERT INTO student_answers (session_id, question_id, answer) VALUES (?,?,?)',
                    (session_id, data['question_id'], data['answer']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/exam/session/<int:session_id>/submit', methods=['POST'])
@token_required(['student'])
def submit_exam(session_id):
    conn = get_db()
    session_row = db_execute(conn, 'SELECT * FROM exam_sessions WHERE id=? AND student_id=?',
                               (session_id, request.user['user_id'])).fetchone()
    if not session_row:
        conn.close()
        return jsonify({'error': 'Session not found'}), 404

    exam = db_fetchone(conn, 'SELECT * FROM exams WHERE id=?', (session_row['exam_id'],))
    answers = db_fetchall(conn, 'SELECT * FROM student_answers WHERE session_id=?', (session_id,))

    total_score = 0
    for ans in answers:
        q = db_fetchone(conn, 'SELECT * FROM question_bank WHERE id=?', (ans['question_id'],))
        if q and q['type'] != 'essay':
            correct = str(q['correct_answer']).strip().lower()
            given = str(ans['answer'] or '').strip().lower()
            is_correct = 1 if correct == given else 0
            pts = q['points'] if is_correct else 0
            total_score += pts
            db_execute(conn, 'UPDATE student_answers SET is_correct=?, points_earned=? WHERE id=?',
                        (is_correct, pts, ans['id']))

    percentage = (total_score / exam['total_points'] * 100) if exam['total_points'] > 0 else 0
    passed = 1 if percentage >= exam['pass_score'] else 0
    grade_letter = get_grade_letter(percentage)

    db_execute(conn, 'UPDATE exam_sessions SET status=?, end_time=datetime("now") WHERE id=?',
                ('submitted', session_id))
    db_execute(conn, '''INSERT OR REPLACE INTO exam_results (session_id, student_id, exam_id, total_score, percentage, grade_letter, passed)
                   VALUES (?,?,?,?,?,?,?)''',
                (session_id, request.user['user_id'], session_row['exam_id'],
                 total_score, percentage, grade_letter, passed))
    conn.commit()
    conn.close()
    return jsonify({'score': total_score, 'percentage': round(percentage, 1),
                    'grade': grade_letter, 'passed': bool(passed)})

def get_grade_letter(pct):
    if pct >= 95: return 'A+'
    elif pct >= 90: return 'A'
    elif pct >= 85: return 'B+'
    elif pct >= 80: return 'B'
    elif pct >= 75: return 'C+'
    elif pct >= 70: return 'C'
    elif pct >= 65: return 'D+'
    elif pct >= 60: return 'D'
    else: return 'F'

# ─── ROUTES: RESULTS & ANALYTICS ─────────────────────────────────────────────
@app.route('/api/results/exam/<int:eid>', methods=['GET'])
@token_required(['admin', 'teacher'])
def exam_results(eid):
    conn = get_db()
    results = db_execute(conn, '''SELECT er.*, u.full_name_ar, u.class_name, u.grade,
                              es.start_time, es.end_time
                              FROM exam_results er
                              JOIN users u ON er.student_id=u.id
                              JOIN exam_sessions es ON er.session_id=es.id
                              WHERE er.exam_id=? ORDER BY er.percentage DESC''', (eid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in results])

@app.route('/api/results/student/<int:sid>', methods=['GET'])
@token_required(['admin', 'teacher', 'student'])
def student_results(sid):
    # Students can only see their own
    if request.user['role'] == 'student' and request.user['user_id'] != sid:
        return jsonify({'error': 'Forbidden'}), 403
    conn = get_db()
    results = db_execute(conn, '''SELECT er.*, e.title_ar, e.total_points, e.pass_score,
                              s.name_ar as subject_name, s.color as subject_color
                              FROM exam_results er
                              JOIN exams e ON er.exam_id=e.id
                              JOIN subjects s ON e.subject_id=s.id
                              WHERE er.student_id=? ORDER BY er.submitted_at DESC''', (sid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in results])

@app.route('/api/analytics/overview', methods=['GET'])
@token_required(['admin', 'teacher'])
def analytics_overview():
    conn = get_db()
    stats = {
        'total_students': db_fetchone(conn, "SELECT COUNT(*) FROM users WHERE role='student'")[0],
        'total_teachers': db_fetchone(conn, "SELECT COUNT(*) FROM users WHERE role='teacher'")[0],
        'total_exams': db_fetchone(conn, "SELECT COUNT(*) FROM exams")[0],
        'total_questions': db_fetchone(conn, "SELECT COUNT(*) FROM question_bank")[0],
        'active_exams': db_fetchone(conn, "SELECT COUNT(*) FROM exams WHERE status='active'")[0],
        'total_submissions': db_fetchone(conn, "SELECT COUNT(*) FROM exam_results")[0],
        'avg_score': db_fetchone(conn, "SELECT AVG(percentage) FROM exam_results")[0] or 0,
        'pass_rate': 0
    }
    pass_data = db_fetchone(conn, "SELECT COUNT(*) as total, SUM(passed) as passed FROM exam_results")
    if pass_data['total'] > 0:
        stats['pass_rate'] = round(pass_data['passed'] / pass_data['total'] * 100, 1)
    stats['avg_score'] = round(stats['avg_score'], 1)

    # Per subject stats
    subject_stats = db_execute(conn, '''SELECT s.name_ar, s.color, COUNT(er.id) as attempts,
                                    AVG(er.percentage) as avg_score, SUM(er.passed) as passed
                                    FROM subjects s LEFT JOIN exams e ON s.id=e.subject_id
                                    LEFT JOIN exam_results er ON e.id=er.exam_id
                                    GROUP BY s.id ORDER BY avg_score DESC''').fetchall()
    stats['subject_stats'] = [dict(s) for s in subject_stats]

    # Recent activity
    recent = db_execute(conn, '''SELECT er.*, u.full_name_ar, e.title_ar, s.name_ar as subject_name
                             FROM exam_results er JOIN users u ON er.student_id=u.id
                             JOIN exams e ON er.exam_id=e.id JOIN subjects s ON e.subject_id=s.id
                             ORDER BY er.submitted_at DESC LIMIT 10''').fetchall()
    stats['recent_activity'] = [dict(r) for r in recent]

    # Grade distribution
    grade_dist = db_fetchall(conn, '''SELECT grade_letter, COUNT(*) as count FROM exam_results GROUP BY grade_letter''')
    stats['grade_distribution'] = [dict(g) for g in grade_dist]

    conn.close()
    return jsonify(stats)

@app.route('/api/analytics/class/<class_name>', methods=['GET'])
@token_required(['admin', 'teacher'])
def class_analytics(class_name):
    conn = get_db()
    students = db_fetchall(conn, "SELECT * FROM users WHERE class_name=? AND role='student'", (class_name,))
    data = []
    for st in students:
        results = db_execute(conn, '''SELECT er.percentage, er.grade_letter, er.passed, e.title_ar, s.name_ar as subject
                                  FROM exam_results er JOIN exams e ON er.exam_id=e.id
                                  JOIN subjects s ON e.subject_id=s.id
                                  WHERE er.student_id=?''', (st['id'],)).fetchall()
        avg = sum(r['percentage'] for r in results) / len(results) if results else 0
        data.append({'student': dict(st), 'results': [dict(r) for r in results], 'avg': round(avg, 1)})
    conn.close()
    return jsonify(data)

# ─── ROUTES: REPORTS (PDF) ────────────────────────────────────────────────────
@app.route('/api/reports/student/<int:sid>', methods=['GET'])
@token_required(['admin', 'teacher', 'student'])
def student_report_pdf(sid):
    if request.user['role'] == 'student' and request.user['user_id'] != sid:
        return jsonify({'error': 'Forbidden'}), 403
    conn = get_db()
    student = db_fetchone(conn, 'SELECT * FROM users WHERE id=?', (sid,))
    results = db_execute(conn, '''SELECT er.*, e.title_ar, e.total_points, e.pass_score,
                              s.name_ar as subject_name
                              FROM exam_results er JOIN exams e ON er.exam_id=e.id
                              JOIN subjects s ON e.subject_id=s.id
                              WHERE er.student_id=? ORDER BY er.submitted_at DESC''', (sid,)).fetchall()
    settings = {r['key']: r['value'] for r in db_fetchall(conn, 'SELECT * FROM school_settings')}
    conn.close()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    story = []
    styles = getSampleStyleSheet()

    # Header
    header_style = ParagraphStyle('header', fontSize=16, fontName='Helvetica-Bold',
                                   alignment=1, spaceAfter=6, textColor=colors.HexColor('#1a3a5c'))
    sub_style = ParagraphStyle('sub', fontSize=11, fontName='Helvetica',
                                alignment=1, spaceAfter=4, textColor=colors.HexColor('#64748b'))
    normal = ParagraphStyle('norm', fontSize=10, fontName='Helvetica', spaceAfter=4)

    story.append(Paragraph(settings.get('name_en', 'School Exam System'), header_style))
    story.append(Paragraph(settings.get('address', ''), sub_style))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#1a3a5c')))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph('STUDENT PERFORMANCE REPORT / تقرير أداء الطالب', header_style))
    story.append(Spacer(1, 0.3*cm))

    # Student info
    info_data = [
        ['Student Name / اسم الطالب', student['full_name_ar'] or student['full_name_en'] or ''],
        ['Class / الفصل', student['class_name'] or '-'],
        ['Grade / المرحلة', student['grade'] or '-'],
        ['Report Date / تاريخ التقرير', datetime.now().strftime('%Y-%m-%d')],
    ]
    t = Table(info_data, colWidths=[5*cm, 10*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#e8f0fe')),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.5*cm))

    # Summary stats
    if results:
        avg_pct = sum(r['percentage'] for r in results) / len(results)
        passed = sum(1 for r in results if r['passed'])
        story.append(Paragraph('Performance Summary / ملخص الأداء', ParagraphStyle('h2', fontSize=13, fontName='Helvetica-Bold', textColor=colors.HexColor('#1a3a5c'), spaceAfter=8)))
        summary_data = [
            ['Total Exams / عدد الامتحانات', 'Average Score / المتوسط', 'Passed / ناجح', 'Failed / راسب'],
            [str(len(results)), f'{round(avg_pct,1)}%', str(passed), str(len(results)-passed)]
        ]
        st_table = Table(summary_data, colWidths=[4.5*cm]*4)
        st_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a3a5c')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
            ('FONTSIZE', (0,0), (-1,-1), 10),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0,0), (-1,-1), 8),
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8fafc')),
        ]))
        story.append(st_table)
        story.append(Spacer(1, 0.5*cm))

        # Detailed results
        story.append(Paragraph('Exam Results Detail / تفاصيل نتائج الامتحانات', ParagraphStyle('h2', fontSize=13, fontName='Helvetica-Bold', textColor=colors.HexColor('#1a3a5c'), spaceAfter=8)))
        detail_data = [['Exam / الامتحان', 'Subject / المادة', 'Score / الدرجة', 'Grade / التقدير', 'Status / الحالة']]
        for r in results:
            status = '✓ Pass / ناجح' if r['passed'] else '✗ Fail / راسب'
            detail_data.append([r['title_ar'][:30], r['subject_name'], f"{round(r['percentage'],1)}%", r['grade_letter'], status])

        dt = Table(detail_data, colWidths=[5*cm, 3.5*cm, 2.5*cm, 2*cm, 3*cm])
        dt.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a3a5c')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0,0), (-1,-1), 6),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f1f5f9')]),
        ]))
        story.append(dt)

    # Footer
    story.append(Spacer(1, 1*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#cbd5e1')))
    story.append(Paragraph(settings.get('copyright', ''), ParagraphStyle('footer', fontSize=8, alignment=1, textColor=colors.HexColor('#94a3b8'))))

    doc.build(story)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf',
                     download_name=f'report_{student["full_name_ar"] or sid}.pdf')

@app.route('/api/reports/class/<class_name>', methods=['GET'])
@token_required(['admin', 'teacher'])
def class_report_pdf(class_name):
    conn = get_db()
    students = db_fetchall(conn, "SELECT * FROM users WHERE class_name=? AND role='student' ORDER BY full_name_ar", (class_name,))
    settings = {r['key']: r['value'] for r in db_fetchall(conn, 'SELECT * FROM school_settings')}

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    story = []
    styles = getSampleStyleSheet()
    header_style = ParagraphStyle('h', fontSize=16, fontName='Helvetica-Bold', alignment=1,
                                   spaceAfter=6, textColor=colors.HexColor('#1a3a5c'))
    sub_style = ParagraphStyle('s', fontSize=11, fontName='Helvetica', alignment=1,
                                spaceAfter=4, textColor=colors.HexColor('#64748b'))

    story.append(Paragraph(settings.get('name_en', 'School'), header_style))
    story.append(Paragraph(settings.get('address', ''), sub_style))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#1a3a5c')))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(f'CLASS REPORT / تقرير الفصل: {class_name}', header_style))
    story.append(Paragraph(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}', sub_style))
    story.append(Spacer(1, 0.5*cm))

    table_data = [['#', 'Student Name / الاسم', 'Exams / الامتحانات', 'Avg Score / المتوسط', 'Grade / التقدير', 'Status / الحالة']]
    for i, st in enumerate(students, 1):
        results = db_fetchall(conn, 'SELECT percentage, passed FROM exam_results WHERE student_id=?', (st['id'],))
        avg = sum(r['percentage'] for r in results) / len(results) if results else 0
        grade = get_grade_letter(avg)
        passed = sum(1 for r in results if r['passed'])
        table_data.append([str(i), st['full_name_ar'] or '', str(len(results)),
                           f'{round(avg,1)}%', grade, f'{passed}/{len(results)}'])

    t = Table(table_data, colWidths=[0.8*cm, 5.5*cm, 2.5*cm, 2.5*cm, 2*cm, 2.5*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a3a5c')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('PADDING', (0,0), (-1,-1), 6),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f1f5f9')]),
    ]))
    story.append(t)
    story.append(Spacer(1, 1*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#cbd5e1')))
    story.append(Paragraph(settings.get('copyright', ''), ParagraphStyle('footer', fontSize=8, alignment=1, textColor=colors.HexColor('#94a3b8'))))

    doc.build(story)
    buf.seek(0)
    conn.close()
    return send_file(buf, mimetype='application/pdf', download_name=f'class_report_{class_name}.pdf')


# ─── HELPER: READ EXCEL OR CSV ───────────────────────────────────────────────
def read_file_rows(file, key_column):
    """Read Excel or CSV file and return list of dicts, finding header row by key_column"""
    filename = file.filename.lower()
    rows = []
    if filename.endswith('.xlsx') or filename.endswith('.xls'):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(file.read()), data_only=True)
        ws = wb.active
        headers = []
        for row in ws.iter_rows(values_only=True):
            if all(v is None for v in row):
                continue
            if not headers:
                row_vals = [str(v).strip() if v else '' for v in row]
                if key_column in row_vals:
                    headers = row_vals
                continue
            row_dict = {}
            for j, val in enumerate(row):
                if j < len(headers) and headers[j]:
                    row_dict[headers[j]] = str(val).strip() if val is not None else ''
            if any(row_dict.get(h) for h in headers[:3]):
                rows.append(row_dict)
    else:
        content = file.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(content))
        rows = [dict(r) for r in reader]
    return rows

# ─── IMPORT: TEACHERS ────────────────────────────────────────────────────────
@app.route('/api/teachers/import', methods=['POST'])
@token_required(['admin'])
def import_teachers():
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file'}), 400
    try:
        rows = read_file_rows(file, 'username')
    except Exception as e:
        return jsonify({'error': f'خطأ في قراءة الملف: {str(e)}'}), 400

    conn = get_db()
    created = 0; skipped = 0; errors = []
    for row in rows:
        try:
            username = str(row.get('username') or '').strip()
            name_ar  = str(row.get('full_name_ar') or '').strip()
            if not username and not name_ar:
                continue
            if not username:
                username = f"t{generate_code(5).lower()}"
            existing = db_fetchone(conn, 'SELECT id FROM users WHERE username=?', (username,))
            if existing:
                skipped += 1
                continue
            password = str(row.get('password') or '123456').strip() or '123456'
            db_execute(conn, """INSERT INTO users (username,password_hash,role,full_name_ar,full_name_en,email)
                                VALUES (?,?,?,?,?,?)""",
                       (username, hash_password(password), 'teacher',
                        name_ar, str(row.get('full_name_en') or '').strip(),
                        str(row.get('email') or '').strip()))
            created += 1
        except Exception as e:
            errors.append(f"{row.get('username','?')}: {str(e)}")
    conn.commit(); conn.close()
    return jsonify({'created': created, 'skipped': skipped, 'errors': errors})

# ─── IMPORT: SUBJECTS ────────────────────────────────────────────────────────
@app.route('/api/subjects/import', methods=['POST'])
@token_required(['admin'])
def import_subjects():
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file'}), 400
    try:
        rows = read_file_rows(file, 'code')
    except Exception as e:
        return jsonify({'error': f'خطأ في قراءة الملف: {str(e)}'}), 400

    conn = get_db()
    created = 0; skipped = 0; errors = []
    for row in rows:
        try:
            code    = str(row.get('code') or '').strip()
            name_ar = str(row.get('name_ar') or '').strip()
            if not code or not name_ar:
                continue
            existing = db_fetchone(conn, 'SELECT id FROM subjects WHERE code=?', (code,))
            if existing:
                skipped += 1
                continue
            # Find teacher by name or username
            teacher_id = None
            teacher_name = str(row.get('teacher_username') or '').strip()
            if teacher_name:
                t = db_fetchone(conn, 'SELECT id FROM users WHERE username=? AND role=?', (teacher_name, 'teacher'))
                if t:
                    teacher_id = t['id']
            db_execute(conn, """INSERT INTO subjects (name_ar,name_en,code,teacher_id,grade,color,icon)
                                VALUES (?,?,?,?,?,?,?)""",
                       (name_ar, str(row.get('name_en') or '').strip(),
                        code, teacher_id,
                        str(row.get('grade') or '').strip(),
                        str(row.get('color') or '#3b82f6').strip(),
                        str(row.get('icon') or '📚').strip()))
            created += 1
        except Exception as e:
            errors.append(f"{row.get('code','?')}: {str(e)}")
    conn.commit(); conn.close()
    return jsonify({'created': created, 'skipped': skipped, 'errors': errors})

# ─── IMPORT: QUESTIONS ───────────────────────────────────────────────────────
@app.route('/api/questions/import', methods=['POST'])
@token_required(['admin', 'teacher'])
def import_questions():
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file'}), 400
    try:
        rows = read_file_rows(file, 'question_ar')
    except Exception as e:
        return jsonify({'error': f'خطأ في قراءة الملف: {str(e)}'}), 400

    conn = get_db()
    created = 0; errors = []
    for row in rows:
        try:
            question_ar = str(row.get('question_ar') or '').strip()
            subject_code = str(row.get('subject_code') or '').strip()
            if not question_ar or not subject_code:
                continue
            subject = db_fetchone(conn, 'SELECT id FROM subjects WHERE code=?', (subject_code,))
            if not subject:
                errors.append(f"مادة غير موجودة: {subject_code}")
                continue
            qtype = str(row.get('type') or 'mcq').strip().lower()
            # Build options for MCQ
            options_ar = []
            options_en = []
            correct_answer = str(row.get('correct_answer') or '').strip()
            if qtype == 'mcq':
                for i in range(1, 6):
                    opt = str(row.get(f'option{i}_ar') or row.get(f'option{i}') or '').strip()
                    opt_en = str(row.get(f'option{i}_en') or '').strip()
                    if opt:
                        options_ar.append(opt)
                        options_en.append(opt_en)
            db_execute(conn, """INSERT INTO question_bank
                               (subject_id,question_ar,question_en,type,options_ar,options_en,
                                correct_answer,points,difficulty,skill_tag,created_by)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                       (subject['id'], question_ar,
                        str(row.get('question_en') or '').strip(),
                        qtype,
                        json.dumps(options_ar, ensure_ascii=False),
                        json.dumps(options_en, ensure_ascii=False),
                        correct_answer,
                        float(row.get('points') or 1),
                        str(row.get('difficulty') or 'medium').strip(),
                        str(row.get('skill_tag') or '').strip(),
                        request.user['user_id']))
            created += 1
        except Exception as e:
            errors.append(f"{row.get('question_ar','?')[:30]}: {str(e)}")
    conn.commit(); conn.close()
    return jsonify({'created': created, 'errors': errors})

# ─── BACKUP & RESTORE ────────────────────────────────────────────────────────
@app.route('/api/backup/download', methods=['GET'])
@token_required(['admin'])
def backup_download():
    """Export all data as JSON backup"""
    conn = get_db()
    backup = {
        'version': '1.0',
        'created_at': datetime.now().isoformat(),
        'school': {r['key']: r['value'] for r in db_fetchall(conn, 'SELECT key,value FROM school_settings')},
        'users': db_fetchall(conn, 'SELECT * FROM users'),
        'subjects': db_fetchall(conn, 'SELECT * FROM subjects'),
        'questions': db_fetchall(conn, 'SELECT * FROM question_bank'),
        'exams': db_fetchall(conn, 'SELECT * FROM exams'),
        'exam_access': db_fetchall(conn, 'SELECT * FROM exam_access'),
        'exam_sessions': db_fetchall(conn, 'SELECT * FROM exam_sessions'),
        'student_answers': db_fetchall(conn, 'SELECT * FROM student_answers'),
        'exam_results': db_fetchall(conn, 'SELECT * FROM exam_results'),
    }
    conn.close()
    buf = io.BytesIO(json.dumps(backup, ensure_ascii=False, indent=2).encode('utf-8'))
    buf.seek(0)
    filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return send_file(buf, mimetype='application/json',
                     download_name=filename, as_attachment=True)

@app.route('/api/backup/restore', methods=['POST'])
@token_required(['admin'])
def backup_restore():
    """Restore data from JSON backup"""
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file'}), 400
    try:
        data = json.loads(file.read().decode('utf-8'))
    except Exception as e:
        return jsonify({'error': f'ملف غير صالح: {str(e)}'}), 400

    conn = get_db()
    restored = {}
    try:
        # Restore school settings
        if 'school' in data:
            for k, v in data['school'].items():
                if USE_PG:
                    conn.cursor().execute('INSERT INTO school_settings VALUES (%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value', (k, v))
                else:
                    db_execute(conn, 'INSERT OR REPLACE INTO school_settings VALUES (?,?)', (k, v))
            restored['school_settings'] = len(data['school'])

        # Restore users
        if 'users' in data:
            count = 0
            for u in data['users']:
                try:
                    if USE_PG:
                        conn.cursor().execute("""INSERT INTO users (username,password_hash,role,full_name_ar,full_name_en,email,student_code,class_name,grade,created_at)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(username) DO NOTHING""",
                            (u.get('username'),u.get('password_hash'),u.get('role'),u.get('full_name_ar'),
                             u.get('full_name_en'),u.get('email'),u.get('student_code'),
                             u.get('class_name'),u.get('grade'),u.get('created_at')))
                    else:
                        db_execute(conn, """INSERT OR IGNORE INTO users (username,password_hash,role,full_name_ar,full_name_en,email,student_code,class_name,grade,created_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?)""",
                            (u.get('username'),u.get('password_hash'),u.get('role'),u.get('full_name_ar'),
                             u.get('full_name_en'),u.get('email'),u.get('student_code'),
                             u.get('class_name'),u.get('grade'),u.get('created_at')))
                    count += 1
                except: pass
            restored['users'] = count

        # Restore subjects
        if 'subjects' in data:
            count = 0
            for s in data['subjects']:
                try:
                    if USE_PG:
                        conn.cursor().execute("""INSERT INTO subjects (name_ar,name_en,code,teacher_id,grade,color,icon)
                            VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(code) DO NOTHING""",
                            (s.get('name_ar'),s.get('name_en'),s.get('code'),s.get('teacher_id'),
                             s.get('grade'),s.get('color'),s.get('icon')))
                    else:
                        db_execute(conn, """INSERT OR IGNORE INTO subjects (name_ar,name_en,code,teacher_id,grade,color,icon)
                            VALUES (?,?,?,?,?,?,?)""",
                            (s.get('name_ar'),s.get('name_en'),s.get('code'),s.get('teacher_id'),
                             s.get('grade'),s.get('color'),s.get('icon')))
                    count += 1
                except: pass
            restored['subjects'] = count

        # Restore questions
        if 'questions' in data:
            count = 0
            for q in data['questions']:
                try:
                    db_execute(conn, """INSERT INTO question_bank
                        (subject_id,question_ar,question_en,type,options_ar,options_en,correct_answer,points,difficulty,skill_tag,created_by,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (q.get('subject_id'),q.get('question_ar'),q.get('question_en'),q.get('type'),
                         q.get('options_ar'),q.get('options_en'),q.get('correct_answer'),q.get('points'),
                         q.get('difficulty'),q.get('skill_tag'),q.get('created_by'),q.get('created_at')))
                    count += 1
                except: pass
            restored['questions'] = count

        # Restore exams
        if 'exams' in data:
            count = 0
            for e in data['exams']:
                try:
                    db_execute(conn, """INSERT INTO exams
                        (title_ar,title_en,subject_id,teacher_id,instructions_ar,instructions_en,
                         duration_minutes,total_points,pass_score,start_time,end_time,status,question_ids,
                         randomize_questions,randomize_options,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (e.get('title_ar'),e.get('title_en'),e.get('subject_id'),e.get('teacher_id'),
                         e.get('instructions_ar'),e.get('instructions_en'),e.get('duration_minutes'),
                         e.get('total_points'),e.get('pass_score'),e.get('start_time'),e.get('end_time'),
                         e.get('status'),e.get('question_ids'),e.get('randomize_questions'),
                         e.get('randomize_options'),e.get('created_at')))
                    count += 1
                except: pass
            restored['exams'] = count

        conn.commit()
        conn.close()
        return jsonify({'success': True, 'restored': restored})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500

# ─── SERVE FRONTEND ───────────────────────────────────────────────────────────
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path and os.path.exists(f'public/{path}'):
        return send_file(f'public/{path}')
    return send_file('public/index.html')

if __name__ == '__main__':
    init_db()
    print("\n" + "="*60)
    print("  🎓 نظام الامتحانات المدرسية / School Exam System")
    print("="*60)
    print("  🌐 URL: http://localhost:5000")
    print("  👤 Admin: admin / admin123")
    print("="*60 + "\n")
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)
