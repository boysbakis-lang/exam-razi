from flask import Flask, request, jsonify, session, send_file, render_template_string
import sqlite3, json, os, random, string, hashlib, jwt, csv, io
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
import os
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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    os.makedirs('data', exist_ok=True)
    os.makedirs('public/images', exist_ok=True)
    conn = get_db()
    c = conn.cursor()

    c.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL, -- admin, teacher, student
            full_name_ar TEXT,
            full_name_en TEXT,
            email TEXT,
            student_code TEXT UNIQUE,
            class_name TEXT,
            grade TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name_ar TEXT NOT NULL,
            name_en TEXT NOT NULL,
            code TEXT UNIQUE NOT NULL,
            teacher_id INTEGER,
            grade TEXT,
            color TEXT DEFAULT '#3b82f6',
            icon TEXT DEFAULT '📚',
            FOREIGN KEY(teacher_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS question_bank (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            question_ar TEXT NOT NULL,
            question_en TEXT,
            type TEXT NOT NULL, -- mcq, true_false, essay
            options_ar TEXT, -- JSON array
            options_en TEXT, -- JSON array
            correct_answer TEXT,
            points INTEGER DEFAULT 1,
            difficulty TEXT DEFAULT 'medium', -- easy, medium, hard
            skill_tag TEXT,
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(subject_id) REFERENCES subjects(id),
            FOREIGN KEY(created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            status TEXT DEFAULT 'draft', -- draft, active, closed
            question_ids TEXT, -- JSON array
            randomize_questions INTEGER DEFAULT 0,
            randomize_options INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(subject_id) REFERENCES subjects(id),
            FOREIGN KEY(teacher_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS exam_access (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            access_code TEXT UNIQUE NOT NULL,
            used INTEGER DEFAULT 0,
            used_at TEXT,
            FOREIGN KEY(exam_id) REFERENCES exams(id),
            FOREIGN KEY(student_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS exam_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            start_time TEXT DEFAULT (datetime('now')),
            end_time TEXT,
            status TEXT DEFAULT 'in_progress', -- in_progress, submitted, timed_out
            time_remaining INTEGER,
            FOREIGN KEY(exam_id) REFERENCES exams(id),
            FOREIGN KEY(student_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS student_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            answer TEXT,
            is_correct INTEGER,
            points_earned REAL DEFAULT 0,
            teacher_grade REAL, -- for essay questions
            teacher_feedback TEXT,
            answered_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(session_id) REFERENCES exam_sessions(id),
            FOREIGN KEY(question_id) REFERENCES question_bank(id)
        );

        CREATE TABLE IF NOT EXISTS exam_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            exam_id INTEGER NOT NULL,
            total_score REAL DEFAULT 0,
            percentage REAL DEFAULT 0,
            grade_letter TEXT,
            passed INTEGER DEFAULT 0,
            submitted_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(session_id) REFERENCES exam_sessions(id),
            FOREIGN KEY(student_id) REFERENCES users(id),
            FOREIGN KEY(exam_id) REFERENCES exams(id)
        );

        CREATE TABLE IF NOT EXISTS school_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    ''')

    # Default admin
    admin_hash = hash_password('admin123')
    c.execute('''INSERT OR IGNORE INTO users (username, password_hash, role, full_name_ar, full_name_en)
                 VALUES (?, ?, ?, ?, ?)''',
              ('admin', admin_hash, 'admin', 'مدير النظام', 'System Admin'))

    # Save school config
    for k, v in SCHOOL_CONFIG.items():
        c.execute('INSERT OR REPLACE INTO school_settings VALUES (?, ?)', (k, str(v)))

    conn.commit()
    conn.close()

def hash_password(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

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
    user = conn.execute('SELECT * FROM users WHERE username=?', (data['username'],)).fetchone()
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
    user = conn.execute('SELECT id, username, role, full_name_ar, full_name_en, email, class_name, grade FROM users WHERE id=?',
                        (request.user['user_id'],)).fetchone()
    conn.close()
    return jsonify(dict(user))

# ─── ROUTES: SCHOOL SETTINGS ──────────────────────────────────────────────────
@app.route('/api/settings', methods=['GET'])
def get_settings():
    conn = get_db()
    rows = conn.execute('SELECT key, value FROM school_settings').fetchall()
    conn.close()
    return jsonify({r['key']: r['value'] for r in rows})

@app.route('/api/settings', methods=['PUT'])
@token_required(['admin'])
def update_settings():
    data = request.json
    conn = get_db()
    for k, v in data.items():
        conn.execute('INSERT OR REPLACE INTO school_settings VALUES (?, ?)', (k, str(v)))
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
        users = conn.execute('SELECT id, username, role, full_name_ar, full_name_en, email, student_code, class_name, grade FROM users WHERE role=? ORDER BY full_name_ar', (role,)).fetchall()
    else:
        users = conn.execute('SELECT id, username, role, full_name_ar, full_name_en, email, student_code, class_name, grade FROM users ORDER BY role, full_name_ar').fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])

@app.route('/api/users', methods=['POST'])
@token_required(['admin'])
def create_user():
    data = request.json
    conn = get_db()
    code = generate_code(6) if data.get('role') == 'student' else None
    try:
        conn.execute('''INSERT INTO users (username, password_hash, role, full_name_ar, full_name_en, email, student_code, class_name, grade)
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
    conn.execute(f'UPDATE users SET {", ".join(fields)} WHERE id=?', vals)
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/users/<int:uid>', methods=['DELETE'])
@token_required(['admin'])
def delete_user(uid):
    conn = get_db()
    conn.execute('DELETE FROM users WHERE id=?', (uid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/users/import', methods=['POST'])
@token_required(['admin'])
def import_students():
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file'}), 400
    content = file.read().decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(content))
    conn = get_db()
    created = 0
    errors = []
    for row in reader:
        try:
            code = generate_code(6)
            username = row.get('username') or f"st{generate_code(6).lower()}"
            conn.execute('''INSERT OR IGNORE INTO users (username, password_hash, role, full_name_ar, full_name_en, email, student_code, class_name, grade)
                           VALUES (?,?,?,?,?,?,?,?,?)''',
                        (username, hash_password(row.get('password', '123456')),
                         'student', row.get('full_name_ar', ''), row.get('full_name_en', ''),
                         row.get('email', ''), code, row.get('class_name', ''), row.get('grade', '')))
            created += 1
        except Exception as e:
            errors.append(str(e))
    conn.commit()
    conn.close()
    return jsonify({'created': created, 'errors': errors})

# ─── ROUTES: SUBJECTS ─────────────────────────────────────────────────────────
@app.route('/api/subjects', methods=['GET'])
@token_required()
def get_subjects():
    conn = get_db()
    subjects = conn.execute('''SELECT s.*, u.full_name_ar as teacher_name
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
        conn.execute('INSERT INTO subjects (name_ar, name_en, code, teacher_id, grade, color, icon) VALUES (?,?,?,?,?,?,?)',
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
    conn.execute('UPDATE subjects SET name_ar=?, name_en=?, teacher_id=?, grade=?, color=?, icon=? WHERE id=?',
                (data['name_ar'], data.get('name_en'), data.get('teacher_id'),
                 data.get('grade'), data.get('color'), data.get('icon'), sid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/subjects/<int:sid>', methods=['DELETE'])
@token_required(['admin'])
def delete_subject(sid):
    conn = get_db()
    conn.execute('DELETE FROM subjects WHERE id=?', (sid,))
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
        qs = conn.execute('SELECT q.*, s.name_ar as subject_name FROM question_bank q JOIN subjects s ON q.subject_id=s.id WHERE q.subject_id=? ORDER BY q.id DESC', (subject_id,)).fetchall()
    else:
        qs = conn.execute('SELECT q.*, s.name_ar as subject_name FROM question_bank q JOIN subjects s ON q.subject_id=s.id ORDER BY q.id DESC').fetchall()
    conn.close()
    return jsonify([dict(q) for q in qs])

@app.route('/api/questions', methods=['POST'])
@token_required(['admin', 'teacher'])
def create_question():
    data = request.json
    conn = get_db()
    conn.execute('''INSERT INTO question_bank (subject_id, question_ar, question_en, type, options_ar, options_en, correct_answer, points, difficulty, skill_tag, created_by)
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
    conn.execute('''UPDATE question_bank SET subject_id=?, question_ar=?, question_en=?, type=?,
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
    conn.execute('DELETE FROM question_bank WHERE id=?', (qid,))
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
        exams = conn.execute('''SELECT e.*, s.name_ar as subject_name, u.full_name_ar as teacher_name
                                FROM exams e JOIN subjects s ON e.subject_id=s.id
                                JOIN users u ON e.teacher_id=u.id ORDER BY e.created_at DESC''').fetchall()
    else:
        exams = conn.execute('''SELECT e.*, s.name_ar as subject_name, u.full_name_ar as teacher_name
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
    cursor = conn.execute('''INSERT INTO exams (title_ar, title_en, subject_id, teacher_id, instructions_ar, instructions_en,
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
    exam_id = cursor.lastrowid
    conn.close()
    return jsonify({'success': True, 'exam_id': exam_id})

@app.route('/api/exams/<int:eid>', methods=['PUT'])
@token_required(['admin', 'teacher'])
def update_exam(eid):
    data = request.json
    conn = get_db()
    conn.execute('''UPDATE exams SET title_ar=?, title_en=?, subject_id=?, instructions_ar=?, instructions_en=?,
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
    conn.execute('DELETE FROM exams WHERE id=?', (eid,))
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
        existing = conn.execute('SELECT access_code FROM exam_access WHERE exam_id=? AND student_id=?', (eid, sid)).fetchone()
        if existing:
            codes.append({'student_id': sid, 'code': existing['access_code']})
        else:
            code = generate_code(8)
            conn.execute('INSERT INTO exam_access (exam_id, student_id, access_code) VALUES (?,?,?)', (eid, sid, code))
            codes.append({'student_id': sid, 'code': code})
    conn.commit()
    # Enrich with student names
    result = []
    for c in codes:
        student = conn.execute('SELECT full_name_ar, class_name FROM users WHERE id=?', (c['student_id'],)).fetchone()
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
    access = conn.execute('''SELECT ea.*, e.title_ar, e.duration_minutes, e.status, e.start_time, e.end_time
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
    existing_session = conn.execute('''SELECT es.* FROM exam_sessions es
                                       WHERE es.exam_id=? AND es.student_id=? AND es.status='in_progress' ''',
                                   (access['exam_id'], access['student_id'])).fetchone()
    if existing_session:
        conn.close()
        token = create_token(access['student_id'], 'student')
        return jsonify({'session_id': existing_session['id'], 'token': token,
                        'exam_id': access['exam_id'], 'resume': True})

    # Create session
    session_cursor = conn.execute('INSERT INTO exam_sessions (exam_id, student_id) VALUES (?,?)',
                                  (access['exam_id'], access['student_id']))
    session_id = session_cursor.lastrowid
    conn.execute('UPDATE exam_access SET used=1, used_at=datetime("now") WHERE access_code=?', (code,))
    conn.commit()
    conn.close()
    token = create_token(access['student_id'], 'student')
    return jsonify({'session_id': session_id, 'token': token, 'exam_id': access['exam_id']})

@app.route('/api/exam/session/<int:session_id>/questions', methods=['GET'])
@token_required(['student'])
def get_exam_questions(session_id):
    conn = get_db()
    session_row = conn.execute('SELECT * FROM exam_sessions WHERE id=? AND student_id=?',
                               (session_id, request.user['user_id'])).fetchone()
    if not session_row:
        conn.close()
        return jsonify({'error': 'Session not found'}), 404

    exam = conn.execute('SELECT * FROM exams WHERE id=?', (session_row['exam_id'],)).fetchone()
    question_ids = json.loads(exam['question_ids'])

    if exam['randomize_questions']:
        random.shuffle(question_ids)

    questions = []
    for qid in question_ids:
        q = conn.execute('SELECT * FROM question_bank WHERE id=?', (qid,)).fetchone()
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
    answers = conn.execute('SELECT question_id, answer FROM student_answers WHERE session_id=?', (session_id,)).fetchall()
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
    existing = conn.execute('SELECT id FROM student_answers WHERE session_id=? AND question_id=?',
                            (session_id, data['question_id'])).fetchone()
    if existing:
        conn.execute('UPDATE student_answers SET answer=?, answered_at=datetime("now") WHERE session_id=? AND question_id=?',
                    (data['answer'], session_id, data['question_id']))
    else:
        conn.execute('INSERT INTO student_answers (session_id, question_id, answer) VALUES (?,?,?)',
                    (session_id, data['question_id'], data['answer']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/exam/session/<int:session_id>/submit', methods=['POST'])
@token_required(['student'])
def submit_exam(session_id):
    conn = get_db()
    session_row = conn.execute('SELECT * FROM exam_sessions WHERE id=? AND student_id=?',
                               (session_id, request.user['user_id'])).fetchone()
    if not session_row:
        conn.close()
        return jsonify({'error': 'Session not found'}), 404

    exam = conn.execute('SELECT * FROM exams WHERE id=?', (session_row['exam_id'],)).fetchone()
    answers = conn.execute('SELECT * FROM student_answers WHERE session_id=?', (session_id,)).fetchall()

    total_score = 0
    for ans in answers:
        q = conn.execute('SELECT * FROM question_bank WHERE id=?', (ans['question_id'],)).fetchone()
        if q and q['type'] != 'essay':
            correct = str(q['correct_answer']).strip().lower()
            given = str(ans['answer'] or '').strip().lower()
            is_correct = 1 if correct == given else 0
            pts = q['points'] if is_correct else 0
            total_score += pts
            conn.execute('UPDATE student_answers SET is_correct=?, points_earned=? WHERE id=?',
                        (is_correct, pts, ans['id']))

    percentage = (total_score / exam['total_points'] * 100) if exam['total_points'] > 0 else 0
    passed = 1 if percentage >= exam['pass_score'] else 0
    grade_letter = get_grade_letter(percentage)

    conn.execute('UPDATE exam_sessions SET status=?, end_time=datetime("now") WHERE id=?',
                ('submitted', session_id))
    conn.execute('''INSERT OR REPLACE INTO exam_results (session_id, student_id, exam_id, total_score, percentage, grade_letter, passed)
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
    results = conn.execute('''SELECT er.*, u.full_name_ar, u.class_name, u.grade,
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
    results = conn.execute('''SELECT er.*, e.title_ar, e.total_points, e.pass_score,
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
        'total_students': conn.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone()[0],
        'total_teachers': conn.execute("SELECT COUNT(*) FROM users WHERE role='teacher'").fetchone()[0],
        'total_exams': conn.execute("SELECT COUNT(*) FROM exams").fetchone()[0],
        'total_questions': conn.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0],
        'active_exams': conn.execute("SELECT COUNT(*) FROM exams WHERE status='active'").fetchone()[0],
        'total_submissions': conn.execute("SELECT COUNT(*) FROM exam_results").fetchone()[0],
        'avg_score': conn.execute("SELECT AVG(percentage) FROM exam_results").fetchone()[0] or 0,
        'pass_rate': 0
    }
    pass_data = conn.execute("SELECT COUNT(*) as total, SUM(passed) as passed FROM exam_results").fetchone()
    if pass_data['total'] > 0:
        stats['pass_rate'] = round(pass_data['passed'] / pass_data['total'] * 100, 1)
    stats['avg_score'] = round(stats['avg_score'], 1)

    # Per subject stats
    subject_stats = conn.execute('''SELECT s.name_ar, s.color, COUNT(er.id) as attempts,
                                    AVG(er.percentage) as avg_score, SUM(er.passed) as passed
                                    FROM subjects s LEFT JOIN exams e ON s.id=e.subject_id
                                    LEFT JOIN exam_results er ON e.id=er.exam_id
                                    GROUP BY s.id ORDER BY avg_score DESC''').fetchall()
    stats['subject_stats'] = [dict(s) for s in subject_stats]

    # Recent activity
    recent = conn.execute('''SELECT er.*, u.full_name_ar, e.title_ar, s.name_ar as subject_name
                             FROM exam_results er JOIN users u ON er.student_id=u.id
                             JOIN exams e ON er.exam_id=e.id JOIN subjects s ON e.subject_id=s.id
                             ORDER BY er.submitted_at DESC LIMIT 10''').fetchall()
    stats['recent_activity'] = [dict(r) for r in recent]

    # Grade distribution
    grade_dist = conn.execute('''SELECT grade_letter, COUNT(*) as count FROM exam_results GROUP BY grade_letter''').fetchall()
    stats['grade_distribution'] = [dict(g) for g in grade_dist]

    conn.close()
    return jsonify(stats)

@app.route('/api/analytics/class/<class_name>', methods=['GET'])
@token_required(['admin', 'teacher'])
def class_analytics(class_name):
    conn = get_db()
    students = conn.execute("SELECT * FROM users WHERE class_name=? AND role='student'", (class_name,)).fetchall()
    data = []
    for st in students:
        results = conn.execute('''SELECT er.percentage, er.grade_letter, er.passed, e.title_ar, s.name_ar as subject
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
    student = conn.execute('SELECT * FROM users WHERE id=?', (sid,)).fetchone()
    results = conn.execute('''SELECT er.*, e.title_ar, e.total_points, e.pass_score,
                              s.name_ar as subject_name
                              FROM exam_results er JOIN exams e ON er.exam_id=e.id
                              JOIN subjects s ON e.subject_id=s.id
                              WHERE er.student_id=? ORDER BY er.submitted_at DESC''', (sid,)).fetchall()
    settings = {r['key']: r['value'] for r in conn.execute('SELECT * FROM school_settings').fetchall()}
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
    students = conn.execute("SELECT * FROM users WHERE class_name=? AND role='student' ORDER BY full_name_ar", (class_name,)).fetchall()
    settings = {r['key']: r['value'] for r in conn.execute('SELECT * FROM school_settings').fetchall()}

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
        results = conn.execute('SELECT percentage, passed FROM exam_results WHERE student_id=?', (st['id'],)).fetchall()
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
