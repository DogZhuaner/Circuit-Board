import json
from contextlib import closing
from datetime import datetime
from math import ceil

from flask import Blueprint, current_app, jsonify, request, session, url_for
from mysql.connector import Error, IntegrityError

from db import MySQLConnector
from score_feedback import split_knowledge_points
from student_webui.model_service import ModelError
from teacher_webui.exam_feedback import exam_comment, exam_score_summary


class FormError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def text_field(key, label, limit):
    body = request.get_json(silent=True)
    value = body.get(key) if isinstance(body, dict) else None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise FormError(f'请填写{label}，最多 {limit} 个字符')
    return value.strip()


def exam_time(key, label):
    try:
        return datetime.strptime(text_field(key, label, 16), '%Y-%m-%dT%H:%M')
    except ValueError:
        raise FormError(f'请选择有效的{label}') from None


def owned_class(cur, class_id, lock=False):
    sql = 'SELECT id,name FROM teaching_class WHERE id=%s AND teacher_tno=%s'
    cur.execute(sql + (' FOR UPDATE' if lock else ''), (class_id, session['teacher_id']))
    row = cur.fetchone()
    if not row:
        raise FormError('未找到该班级', 404)
    return row


def set_student_class(cur, sno, class_id, *, unassigned_only=False):
    teacher = session.get('teacher_id')
    if not teacher:
        raise FormError('请先登录教师账号', 401)
    if class_id is not None:
        if type(class_id) is not int or class_id <= 0:
            raise FormError('所选班级无效')
        owned_class(cur, class_id, True)
    cur.execute('SELECT m.class_id,c.teacher_tno FROM class_student m '
                'JOIN teaching_class c ON c.id=m.class_id WHERE m.student_no=%s FOR UPDATE', (sno,))
    existing = cur.fetchone()
    if existing:
        if str(existing[1]) != str(teacher):
            raise FormError('该学生已在其他教师的班级，请先由原班教师移出', 409)
        if existing[0] == class_id:
            return
        if unassigned_only:
            raise FormError('该学生已有班级，请在管理学生中调整所属班级', 409)
        cur.execute('DELETE FROM class_student WHERE student_no=%s', (sno,))
    if class_id is not None:
        cur.execute('INSERT INTO class_student (class_id,student_no) VALUES (%s,%s)', (class_id, sno))


def read_ended_exam_scores(exam_id):
    with closing(MySQLConnector()) as db:
        db.connect()
        with db.connection.cursor() as cur:
            cur.execute('SELECT class_restricted,deadline_time<=NOW(),test_name,rule_snapshot FROM exam_test '
                        'WHERE id=%s AND issuer_tno=%s', (exam_id, session['teacher_id']))
            exam = cur.fetchone()
            if not exam:
                raise FormError('未找到这场考试', 404)
            if not exam[1]:
                raise FormError('考试结束后可查看成绩明细', 409)
            roster_sql = 'SELECT s.sno,s.name FROM student s'
            if exam[0]:
                roster_sql += (' WHERE EXISTS (SELECT 1 FROM exam_class ec JOIN class_student cs '
                               'ON cs.class_id=ec.class_id WHERE ec.exam_id=%s AND cs.student_no=s.sno)')
            cur.execute(roster_sql, (exam_id,) if exam[0] else ())
            students = {str(sno): dict(sno=str(sno), name=name, score=None) for sno, name in cur.fetchall()}
            cur.execute('SELECT r.student_no,r.student_name,r.test_score,r.knowledge,w.result_id FROM exam_result r '
                        'LEFT JOIN exam_recording w ON w.result_id=r.id '
                        'WHERE r.test_id=%s AND r.test_score IS NOT NULL ORDER BY r.id', (str(exam_id),))
            for sno, name, score, knowledge, recording_result in cur.fetchall():
                # Include submitted work even if the student has since changed class.
                row = students.setdefault(sno, dict(sno=sno, name=name, score=None))
                if row['score'] is None:
                    row['score'] = float(score)
                    row['topics'] = list(dict.fromkeys(split_knowledge_points(knowledge)))
                    if recording_result is not None:
                        row['review_url'] = f'/staff/exams/{exam_id}/scores/{recording_result}/review'
            rows = sorted(students.values(), key=lambda r: (len(r['sno']), r['sno']))
            return exam[2], rows, exam_score_summary(rows, exam[3])


def teaching_routes(read_rule_file, validate_rules):
    bp = Blueprint('teaching', __name__, url_prefix='/api')

    @bp.before_request
    def require_teacher():
        if not session.get('teacher_id'):
            return jsonify(success=False, message='请先登录教师账号'), 401

    @bp.errorhandler(FormError)
    def invalid(error):
        return jsonify(success=False, message=str(error)), error.status

    @bp.errorhandler(IntegrityError)
    def conflict(error):
        message = '你已创建过同名班级' if error.errno == 1062 else '关联账号已变更，请刷新后重试'
        return jsonify(success=False, message=message), 409

    @bp.errorhandler(Error)
    def database_error(error):
        current_app.logger.exception('教学管理数据库操作失败')
        return jsonify(success=False, message='数据库操作失败，请稍后重试'), 503

    def rule_snapshot(filename):
        try:
            safe_name, rules = read_rule_file(filename)
            if filename != safe_name:
                raise ValueError('请选择列表中的规则文件')
            rules = validate_rules(rules)
        except (OSError, ValueError) as exc:
            raise FormError('所选规则文件不存在或内容无效，请重新选择') from exc
        return json.dumps(rules, ensure_ascii=False)

    def selected_class_ids():
        selected = request.json.get('class_ids')
        if not isinstance(selected, list) or not selected or any(type(i) is not int or i <= 0 for i in selected):
            raise FormError('请至少选择一个有效的参考班级')
        return sorted(set(selected))

    def check_classes(cur, teacher, class_ids):
        placeholders = ','.join(['%s'] * len(class_ids))
        cur.execute(f'SELECT id FROM teaching_class WHERE teacher_tno=%s AND id IN ({placeholders}) '
                    'ORDER BY id FOR SHARE', (teacher, *class_ids))
        if len(cur.fetchall()) != len(class_ids):
            raise FormError('所选班级不存在或不属于当前教师，请重新选择')

    @bp.post('/create_exam')
    def create_exam():
        name = text_field('test_name', '考试名称', 100)
        content = text_field('exam_content', '考试内容', 10000)
        filename = text_field('rule_filename', '规则文件名', 255)
        start = exam_time('publish_time', '开始时间')
        end = exam_time('deadline_time', '截止时间')
        if end <= start:
            raise FormError('截止时间必须晚于开始时间')
        snapshot = rule_snapshot(filename)
        class_ids = selected_class_ids()
        teacher = session['teacher_id']
        with closing(MySQLConnector()) as db:
            db.connect()
            with db.connection.cursor() as cur:
                check_classes(cur, teacher, class_ids)
                cur.execute('SELECT NOW()')
                if end <= cur.fetchone()[0]:
                    raise FormError('截止时间已过，请选择新的时间')
                cur.execute(
                    'INSERT INTO exam_test (test_name, test_type, duration_minutes, publish_time, '
                    'deadline_time, teacher_id, issuer_tno, exam_content, rule_filename, rule_snapshot, class_restricted) '
                    'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)',
                    (name, '接线操作', ceil((end - start).total_seconds() / 60), start, end, teacher,
                     teacher, content, filename, snapshot))
                exam_id = cur.lastrowid
                cur.executemany('INSERT INTO exam_class (exam_id,class_id) VALUES (%s,%s)',
                                [(exam_id, class_id) for class_id in class_ids])
                db.connection.commit()
        return jsonify(success=True, exam_id=exam_id), 201

    @bp.get('/exams')
    def list_exams():
        with closing(MySQLConnector()) as db:
            db.connect()
            with db.connection.cursor(dictionary=True) as cur:
                cur.execute('SELECT NOW() AS now')
                now = cur.fetchone()['now']
                cur.execute(
                    'SELECT e.id,e.test_name,e.publish_time,e.deadline_time,e.exam_content,e.rule_filename,'
                    'e.class_restricted,c.id AS class_id,c.name AS class_name FROM exam_test e '
                    'LEFT JOIN exam_class ec ON ec.exam_id=e.id LEFT JOIN teaching_class c ON c.id=ec.class_id '
                    'WHERE e.issuer_tno=%s ORDER BY e.publish_time DESC,e.id DESC,c.name,c.id',
                    (session['teacher_id'],))
                exams = {}
                for row in cur.fetchall():
                    class_id = row.pop('class_id')
                    class_name = row.pop('class_name')
                    if row['id'] not in exams:
                        for key in ('publish_time', 'deadline_time'):
                            row[key] = row[key].isoformat()
                        row['classes'] = []
                        exams[row['id']] = row
                    if class_id is not None:
                        exams[row['id']]['classes'].append({'id': class_id, 'name': class_name})
                return jsonify(success=True, exams=list(exams.values()), server_time=now.isoformat()), 200, {'Cache-Control': 'no-store'}

    @bp.delete('/exams/<int:exam_id>')
    def delete_exam(exam_id):
        with closing(MySQLConnector()) as db:
            db.connect()
            with db.connection.cursor() as cur:
                cur.execute('SELECT publish_time,deadline_time FROM exam_test '
                            'WHERE id=%s AND issuer_tno=%s FOR UPDATE', (exam_id, session['teacher_id']))
                exam = cur.fetchone()
                if not exam:
                    raise FormError('未找到这场考试', 404)
                cur.execute('SELECT NOW()')
                now = cur.fetchone()[0]
                if now >= exam[1]:
                    raise FormError('已结束的考试无法删除', 409)
                state = 'upcoming' if now < exam[0] else 'running'
                if request.args.get('state', state) != state:
                    raise FormError('考试状态已变化，请核对后重新确认删除', 409)
                if state == 'running':
                    cur.execute('DELETE w FROM exam_recording w JOIN exam_result r ON r.id=w.result_id '
                                'WHERE r.test_id=%s', (str(exam_id),))
                    cur.execute('DELETE FROM exam_result WHERE test_id=%s', (str(exam_id),))
                # The audience links cascade. Recheck the state after acquiring any dependent locks.
                condition = 'publish_time>NOW()' if state == 'upcoming' else 'deadline_time>NOW()'
                cur.execute(f'DELETE FROM exam_test WHERE id=%s AND {condition}', (exam_id,))
                if not cur.rowcount:
                    raise FormError('考试状态已变化，请刷新后重试', 409)
                db.connection.commit()
        return jsonify(success=True)

    @bp.get('/exams/<int:exam_id>/scores')
    def ended_exam_scores(exam_id):
        _, rows, summary = read_ended_exam_scores(exam_id)
        return jsonify(success=True, students=rows, summary=summary,
                       analysis_url=url_for('exam_analysis', exam_id=exam_id)), 200, {'Cache-Control': 'no-store'}

    @bp.post('/exams/<int:exam_id>/ai-comment')
    def generate_exam_comment(exam_id):
        if not request.is_json:
            raise FormError('请求格式有误，请刷新后重试', 415)
        name, rows, summary = read_ended_exam_scores(exam_id)
        if not summary['count']:
            raise FormError('本场考试暂无有效成绩', 422)
        try:
            comment = exam_comment(name, rows, summary)
        except ModelError as exc:
            return jsonify(success=False, message=str(exc)), exc.status
        return jsonify(success=True, comment=comment), 200, {'Cache-Control': 'no-store'}

    @bp.patch('/exams/<int:exam_id>')
    def edit_exam(exam_id):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not body or body.keys() - {'test_name', 'publish_time', 'deadline_time', 'exam_content', 'rule_filename', 'class_ids'}:
            raise FormError('未识别的考试修改项')
        teacher = session['teacher_id']
        with closing(MySQLConnector()) as db:
            db.connect()
            with db.connection.cursor() as cur:
                cur.execute('SELECT publish_time,deadline_time FROM exam_test WHERE id=%s AND issuer_tno=%s FOR UPDATE',
                            (exam_id, teacher))
                exam = cur.fetchone()
                if not exam:
                    raise FormError('未找到这场考试', 404)
                def ensure_upcoming():
                    cur.execute('SELECT NOW() < %s', (exam[0],))
                    if not cur.fetchone()[0]:
                        raise FormError('考试已开始，无法再修改', 409)

                ensure_upcoming()
                if 'test_name' in body:
                    cur.execute('UPDATE exam_test SET test_name=%s WHERE id=%s',
                                (text_field('test_name', '考试名称', 100), exam_id))
                if 'publish_time' in body or 'deadline_time' in body:
                    start = exam_time('publish_time', '开始时间') if 'publish_time' in body else exam[0]
                    end = exam_time('deadline_time', '截止时间') if 'deadline_time' in body else exam[1]
                    cur.execute('SELECT NOW()')
                    if start <= cur.fetchone()[0] or end <= start:
                        raise FormError('开始时间必须晚于当前时间，截止时间必须晚于开始时间')
                    cur.execute('UPDATE exam_test SET publish_time=%s,deadline_time=%s,duration_minutes=%s WHERE id=%s',
                                (start, end, ceil((end - start).total_seconds() / 60), exam_id))
                if 'exam_content' in body:
                    cur.execute('UPDATE exam_test SET exam_content=%s WHERE id=%s',
                                (text_field('exam_content', '考试内容', 10000), exam_id))
                if 'rule_filename' in body:
                    filename = text_field('rule_filename', '规则文件名', 255)
                    cur.execute('UPDATE exam_test SET rule_filename=%s,rule_snapshot=%s WHERE id=%s',
                                (filename, rule_snapshot(filename), exam_id))
                if 'class_ids' in body:
                    ids = selected_class_ids()
                    check_classes(cur, teacher, ids)
                    cur.execute('UPDATE exam_test SET class_restricted=TRUE WHERE id=%s', (exam_id,))
                    cur.execute('DELETE FROM exam_class WHERE exam_id=%s', (exam_id,))
                    cur.executemany('INSERT INTO exam_class (exam_id,class_id) VALUES (%s,%s)',
                                    [(exam_id, class_id) for class_id in ids])
                # A class lock or a rule file read may have taken us past the start time.
                ensure_upcoming()
                db.connection.commit()
        return jsonify(success=True)

    @bp.route('/classes', methods=['GET', 'POST'])
    def classes():
        teacher = session['teacher_id']
        with closing(MySQLConnector()) as db:
            db.connect()
            with db.connection.cursor(dictionary=True) as cur:
                if request.method == 'POST':
                    name = text_field('name', '班级名称', 100)
                    cur.execute('INSERT INTO teaching_class (teacher_tno,name) VALUES (%s,%s)', (teacher, name))
                    class_id = cur.lastrowid
                    db.connection.commit()
                    return jsonify(success=True, id=class_id), 201
                cur.execute('SELECT c.id,c.name,COUNT(m.student_no) AS count FROM teaching_class c '
                            'LEFT JOIN class_student m ON m.class_id=c.id WHERE c.teacher_tno=%s '
                            'GROUP BY c.id,c.name ORDER BY c.name,c.id', (teacher,))
                groups = cur.fetchall()
                if request.args.get('memberships') == '1':
                    cur.execute('SELECT m.student_no,m.class_id,c.name AS class_name FROM class_student m '
                                'JOIN teaching_class c ON c.id=m.class_id')
                    return jsonify(success=True, classes=groups, memberships=cur.fetchall())
                return jsonify(success=True, classes=groups)

    @bp.route('/classes/<int:class_id>', methods=['GET', 'PATCH', 'DELETE'])
    def class_detail(class_id):
        with closing(MySQLConnector()) as db:
            db.connect()
            with db.connection.cursor(dictionary=True) as cur:
                group = owned_class(cur, class_id, request.method != 'GET')
                if request.method == 'DELETE':
                    # Foreign keys remove this class's memberships and exam audience links.
                    cur.execute('DELETE FROM teaching_class WHERE id=%s', (class_id,))
                    db.connection.commit()
                    return jsonify(success=True)
                if request.method == 'PATCH':
                    name = text_field('name', '班级名称', 100)
                    cur.execute('UPDATE teaching_class SET name=%s WHERE id=%s', (name, class_id))
                    db.connection.commit()
                    return jsonify(success=True)
                cur.execute('SELECT s.sno,s.name,m.class_id IS NOT NULL AS member FROM student s '
                            'LEFT JOIN class_student m ON m.student_no=s.sno WHERE m.class_id IS NULL OR m.class_id=%s '
                            'ORDER BY s.sno', (class_id,))
                return jsonify(success=True, group=group, students=cur.fetchall())

    def lock_student(cur, sno):
        cur.execute('SELECT sno FROM student WHERE sno=%s FOR UPDATE', (sno,))
        if not cur.fetchone():
            raise FormError('学生不存在，请刷新名册', 404)

    @bp.put('/students/<int:sno>/class')
    def move_student(sno):
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or 'class_id' not in data:
            raise FormError('请选择班级')
        with closing(MySQLConnector()) as db:
            db.connect()
            with db.connection.cursor() as cur:
                lock_student(cur, sno)
                set_student_class(cur, sno, data['class_id'])
                db.connection.commit()
                return jsonify(success=True)

    @bp.route('/classes/<int:class_id>/students/<int:sno>', methods=['PUT', 'DELETE'])
    def membership(class_id, sno):
        with closing(MySQLConnector()) as db:
            db.connect()
            with db.connection.cursor() as cur:
                lock_student(cur, sno)
                if request.method == 'PUT':
                    set_student_class(cur, sno, class_id, unassigned_only=True)
                else:
                    owned_class(cur, class_id, True)
                    cur.execute('DELETE FROM class_student WHERE class_id=%s AND student_no=%s', (class_id, sno))
                db.connection.commit()
                return jsonify(success=True)

    return bp
