from flask import Flask, render_template, request, redirect, jsonify, send_from_directory, session
import os
from flask_socketio import SocketIO, emit
import json
import sys
import threading
import time
from datetime import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

# 导入数据库连接器
from tools.config import DB_CONFIG, RULE_SERVER_CONFIG, TEACHER_WEB_CONFIG, STUDENT_WEB_CONFIG, portal_login_url
from contextlib import closing
from mysql.connector import Error, IntegrityError
from db import MySQLConnector as RosterDatabase
from teacher_webui.teaching import FormError, set_student_class, teaching_routes

try:
    from tools.connector import MySQLConnector

    DB_AVAILABLE = True
    print("数据库连接模块加载成功")
except ImportError as e:
    print(f"数据库连接模块加载失败：{e}")
    DB_AVAILABLE = False

# 创建数据库连接实例
db_connector = None
try:
    if DB_AVAILABLE:
        db_connector = MySQLConnector(config=DB_CONFIG)
        print("数据库连接初始化成功")
except Exception as e:
    print(f"数据库连接初始化失败：{e}")
    db_connector = None

detect_module = None
rag_module = None
config_module = None
question_generator = None
score_visualizer = None


def get_detect_module():
    global detect_module
    if detect_module is None:
        try:
            from scripts.detect import start_hand_detection, stop_hand_detection
            detect_module = {
                'start_hand_detection': start_hand_detection,
                'stop_hand_detection': stop_hand_detection
            }
        except ImportError:
            print("警告: 无法导入detect模块，将使用模拟模式")
            detect_module = {
                'start_hand_detection': lambda: print("模拟: 开始手势检测"),
                'stop_hand_detection': lambda: print("模拟: 停止手势检测")
            }
    return detect_module


def get_rag_module():
    global rag_module
    if rag_module is None:
        try:
            from scripts.RAG_ui import answer_with_ollama
            rag_module = answer_with_ollama
        except ImportError:
            print("警告: 无法导入RAG_ui模块，将使用模拟AI回答")
            rag_module = lambda question: f"模拟AI回答: {question} (请检查Ollama服务是否运行)"
    return rag_module


def get_config_module():
    global config_module
    if config_module is None:
        try:
            from global_config import Login_Session, Global_Config, reset_session_score, get_global_score
            # 创建实例而不是使用类
            login_session = Login_Session()
            global_config = Global_Config()

            # 确保login_session有必要的属性
            if not hasattr(login_session, 'tno'):
                login_session.tno = "2024001"
            if not hasattr(login_session, 'account_name'):
                login_session.account_name = "测试教师"

            config_module = {
                'Login_Session': login_session,
                'Global_Config': global_config,
                'reset_session_score': reset_session_score,
                'get_global_score': get_global_score
            }
        except ImportError:
            print("警告: 无法导入global_config模块，将使用模拟配置")

            class MockLoginSession:
                def __init__(self):
                    # 添加缺失的tno和account_name属性
                    self.tno = "2024001"
                    self.account_name = "测试教师"

            class MockGlobalConfig:
                teacher_json = "teacher_config.json"
                rule_csv_path = "rule.csv"
                rule_server_ip = RULE_SERVER_CONFIG["ip"]
                rule_server_port = RULE_SERVER_CONFIG["port"]

            config_module = {
                'Login_Session': MockLoginSession(),
                'Global_Config': MockGlobalConfig(),
                'reset_session_score': lambda: True,
                'get_global_score': lambda: current_score
            }
    return config_module


app = Flask(__name__)
app.config.update(SECRET_KEY=STUDENT_WEB_CONFIG["secret_key"], SESSION_COOKIE_NAME="circuit_entry")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# 全局变量
current_score = 0
student_scores = {}
connected_students = {}


# 添加一些模拟成绩数据用于演示
def init_demo_data():
    """初始化演示数据"""
    global student_scores
    if not student_scores:  # 只在第一次调用时初始化
        demo_scores = {
            'S001': 85,
            'S002': 92,
            'S003': 78,
            'S004': 88,
            'S005': 95,
            'S006': 82,
            'S007': 76,
            'S008': 90,
            'S009': 87,
            'S010': 83
        }
        student_scores.update(demo_scores)
        print(f"已初始化 {len(student_scores)} 个学生的演示成绩数据")


STUDENTS_FILE = 'students.json'


def load_students():
    """从文件加载学生数据"""
    try:
        with open(STUDENTS_FILE, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return []


def save_students(students):
    """将学生数据保存到文件"""
    with open(STUDENTS_FILE, 'w') as file:
        json.dump(students, file)


def normalize_rule_filename(filename):
    filename = (filename or '').strip()
    if not filename:
        raise ValueError('规则文件名不能为空')

    filename = os.path.basename(filename)
    filename = ''.join(ch for ch in filename if ch not in '<>:"/\\|?*')
    filename = filename.strip().strip('.')
    if not filename:
        raise ValueError('规则文件名无效')

    if not filename.lower().endswith('.json'):
        filename += '.json'
    return filename


def validate_rule_payload(rules):
    if not isinstance(rules, list) or not rules:
        raise ValueError('请至少创建一组连线规则')

    normalized = []
    for source_index, rule in enumerate(rules, start=1):
        nodes = rule.get('nodes') if isinstance(rule, dict) else None
        score = rule.get('score', 0) if isinstance(rule, dict) else 0
        if not isinstance(nodes, list) or len(nodes) < 2:
            raise ValueError(f'第 {source_index} 条规则至少需要两个触点')

        clean_nodes = [str(node).strip() for node in nodes if str(node).strip()]
        if len(clean_nodes) < 2:
            raise ValueError(f'第 {source_index} 条规则至少需要两个有效触点')

        try:
            score = int(score)
        except (TypeError, ValueError):
            raise ValueError(f'第 {source_index} 条规则分值必须是整数')

        for left, right in zip(clean_nodes, clean_nodes[1:]):
            if left == right:
                raise ValueError(f'第 {source_index} 条规则包含重复触点')
            normalized.append({
                'id': len(normalized) + 1,
                'nodes': [left, right],
                'score': score
            })
    return normalized


def format_rules_json(rules):
    lines = ['[']
    for index, rule in enumerate(rules):
        comma = ',' if index < len(rules) - 1 else ''
        nodes = json.dumps(rule['nodes'], ensure_ascii=False)
        lines.extend([
            '  {',
            f'    "id": {rule["id"]},',
            f'    "nodes": {nodes},',
            f'    "score": {rule["score"]}',
            f'  }}{comma}',
        ])
    lines.append(']')
    return '\n'.join(lines) + '\n'


def get_rule_directory():
    config = get_config_module()
    global_config = config['Global_Config']
    rule_dir = os.path.abspath(str(global_config.rule_path))
    os.makedirs(rule_dir, exist_ok=True)
    return rule_dir


def resolve_rule_file(filename):
    safe_name = normalize_rule_filename(filename)
    rule_dir = get_rule_directory()
    file_path = os.path.abspath(os.path.join(rule_dir, safe_name))
    if os.path.commonpath([rule_dir, file_path]) != rule_dir:
        raise ValueError('规则文件路径无效')
    return safe_name, file_path


def read_rule_file(filename):
    safe_name, file_path = resolve_rule_file(filename)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f'规则文件不存在：{safe_name}')
    with open(file_path, 'r', encoding='utf-8') as f:
        return safe_name, json.load(f)


app.register_blueprint(teaching_routes(read_rule_file, validate_rule_payload))


def db_error_response(default_message='数据库操作失败'):
    error = getattr(db_connector, 'last_error', None) if db_connector else None
    message = f'{default_message}：{error}' if error else default_message
    return jsonify({'success': False, 'message': message}), 500


@app.before_request
def require_teacher_session():
    if request.endpoint == 'static' or session.get('teacher_id'):
        return
    if request.path.startswith('/api/'):
        return jsonify(success=False, message='请先登录教师账号'), 401
    return redirect(portal_login_url(request.host_url, request.script_root))


@app.route('/')
def index():
    return render_template('index.html'), 200, {'Cache-Control': 'no-store'}


# 添加新路由用于显示规则下载服务模态框
@app.route('/api/rule_download_service', methods=['GET'])
def rule_download_service():
    """规则下载服务模态框内容"""
    config = get_config_module()
    global_config = config['Global_Config']

    # 获取规则文件路径和服务器信息
    rule_file_path = str(global_config.test_rule)
    server_ip = global_config.rule_server_ip
    server_port = global_config.rule_server_port

    # 检查规则文件是否存在
    file_exists = os.path.exists(rule_file_path)
    file_size = os.path.getsize(rule_file_path) if file_exists else 0

    return jsonify({
        'title': '规则下载服务',
        'content': {
            'file_path': rule_file_path,
            'server_ip': server_ip,
            'server_port': server_port,
            'file_exists': file_exists,
            'file_size': file_size,
            'status': 'ready' if file_exists else 'missing'
        },
        'status': 'success'
    })


@app.route('/api/rules/save', methods=['POST'])
def save_rule_file():
    """保存教师在网页端制定的连线规则文件"""
    try:
        data = request.get_json() or {}
        filename = normalize_rule_filename(data.get('filename'))
        rules = validate_rule_payload(data.get('rules'))

        config = get_config_module()
        global_config = config['Global_Config']
        rule_dir = os.path.abspath(str(global_config.rule_path))
        os.makedirs(rule_dir, exist_ok=True)

        file_path = os.path.join(rule_dir, filename)
        current_rule_path = os.path.join(rule_dir, 'current_rule.json')

        for target_path in (file_path, current_rule_path):
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(format_rules_json(rules))

        return jsonify({
            'success': True,
            'message': '规则文件保存成功',
            'filename': filename,
            'path': file_path,
            'active_rule_path': current_rule_path,
            'rules_count': len(rules)
        })
    except ValueError as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 400
    except Exception as e:
        print(f"保存规则文件失败：{e}")
        return jsonify({
            'success': False,
            'message': f'保存规则文件失败：{str(e)}'
        }), 500


@app.route('/api/rules', methods=['GET'])
def list_rule_files():
    """列出全部规则文件。"""
    try:
        rule_dir = get_rule_directory()
        current_rule_path = os.path.abspath(os.path.join(rule_dir, 'current_rule.json'))
        files = []
        for filename in sorted(os.listdir(rule_dir), key=lambda name: name.lower()):
            if not filename.lower().endswith('.json'):
                continue

            file_path = os.path.join(rule_dir, filename)
            if not os.path.isfile(file_path):
                continue

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    rules = json.load(f)
                    rule_count = 0 if rules == [] else len(validate_rule_payload(rules))
            except Exception:
                rule_count = None

            stat = os.stat(file_path)
            files.append({
                'filename': filename,
                'size': stat.st_size,
                'modified_time': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                'rule_count': rule_count,
                'is_current': os.path.abspath(file_path) == current_rule_path
            })

        return jsonify({'success': True, 'files': files, 'total': len(files)})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取规则文件列表失败：{str(e)}'}), 500


@app.route('/api/rules/<path:filename>', methods=['GET'])
def get_rule_file(filename):
    """读取指定规则文件。"""
    try:
        safe_name, rules = read_rule_file(filename)
        rules = validate_rule_payload(rules)
        return jsonify({
            'success': True,
            'filename': safe_name,
            'rules': rules,
            'raw': format_rules_json(rules)
        })
    except FileNotFoundError as e:
        return jsonify({'success': False, 'message': str(e)}), 404
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'读取规则文件失败：{str(e)}'}), 500


@app.route('/api/rules/<path:filename>', methods=['PUT'])
def update_rule_file(filename):
    """更新指定规则文件内容。"""
    try:
        safe_name, file_path = resolve_rule_file(filename)
        data = request.get_json() or {}
        rules = validate_rule_payload(data.get('rules'))

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(format_rules_json(rules))

        return jsonify({
            'success': True,
            'message': '规则文件已保存',
            'filename': safe_name,
            'rules_count': len(rules)
        })
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'保存规则文件失败：{str(e)}'}), 500


@app.route('/api/rules/<path:filename>', methods=['DELETE'])
def delete_rule_file(filename):
    """删除指定规则文件。"""
    try:
        safe_name, file_path = resolve_rule_file(filename)
        if safe_name == 'current_rule.json':
            return jsonify({'success': False, 'message': 'current_rule.json 是当前启用规则，不允许删除'}), 400
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'message': f'规则文件不存在：{safe_name}'}), 404

        os.remove(file_path)
        return jsonify({
            'success': True,
            'message': '规则文件已删除',
            'filename': safe_name
        })
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除规则文件失败：{str(e)}'}), 500


@app.route('/api/rules/<path:filename>/rename', methods=['POST'])
def rename_rule_file(filename):
    """重命名规则文件。"""
    try:
        old_name, old_path = resolve_rule_file(filename)
        data = request.get_json() or {}
        new_name, new_path = resolve_rule_file(data.get('new_filename'))

        if old_name == 'current_rule.json':
            return jsonify({'success': False, 'message': 'current_rule.json 是当前启用规则，不允许重命名'}), 400
        if os.path.exists(new_path):
            return jsonify({'success': False, 'message': '目标文件名已存在'}), 409
        if not os.path.exists(old_path):
            return jsonify({'success': False, 'message': f'规则文件不存在：{old_name}'}), 404

        os.rename(old_path, new_path)
        return jsonify({
            'success': True,
            'message': '规则文件已重命名',
            'filename': new_name
        })
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'重命名规则文件失败：{str(e)}'}), 500


@app.route('/api/rules/<path:filename>/activate', methods=['POST'])
def activate_rule_file(filename):
    """将指定规则文件设为当前启用规则。"""
    try:
        safe_name, rules = read_rule_file(filename)
        rules = validate_rule_payload(rules)
        _, current_rule_path = resolve_rule_file('current_rule.json')

        with open(current_rule_path, 'w', encoding='utf-8') as f:
            f.write(format_rules_json(rules))

        return jsonify({
            'success': True,
            'message': f'已将 {safe_name} 设为当前规则',
            'active_rule_path': current_rule_path,
            'rules_count': len(rules)
        })
    except FileNotFoundError as e:
        return jsonify({'success': False, 'message': str(e)}), 404
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'设为当前规则失败：{str(e)}'}), 500


@app.route('/api/teacher_info', methods=['GET'])
def get_teacher_info():
    """获取教师信息"""
    return jsonify(teacher_id=session['teacher_id'], teacher_name=session.get('teacher_name', ''))


@app.route('/api/students', methods=['GET'])
def get_students():
    """Get all student records from the database."""
    if not db_connector:
        return jsonify({'success': False, 'message': '数据库连接不可用', 'students': []}), 500

    sort_by = request.args.get('sort_by', 'sno')
    sort_columns = {
        'sno': 's.sno',
        'student_id': 's.sno',
        'name': 's.name',
        'user_id': 's.user_id'
    }
    order_column = sort_columns.get(sort_by, 's.sno')

    try:
        with closing(RosterDatabase()) as db:
            rows = db.query(f"""
                SELECT s.sno, s.name, s.user_id, s.student_password, u.user_no, u.password, u.role
                FROM student s LEFT JOIN users u ON s.user_id = u.user_id ORDER BY {order_column}
            """)
    except RuntimeError:
        return jsonify(success=False, message='读取学生列表失败'), 503

    students = []
    for row in rows:
        sno, name, user_id, student_password, user_no, user_password, role = row
        password = student_password or user_password or ''
        students.append({
            'id': user_id,
            'user_id': user_id,
            'sno': str(sno) if sno is not None else '',
            'student_id': str(sno) if sno is not None else '',
            'name': name or '',
            'student_password': password,
            'password': password,
            'user_no': str(user_no) if user_no is not None else '',
            'role': role or 'student'
        })

    return jsonify({'success': True, 'students': students, 'total': len(students)})


@app.route('/api/student', methods=['POST'])
def add_student():
    """Add a student and matching login user."""
    if not db_connector:
        return jsonify({'success': False, 'message': '数据库连接不可用'}), 500

    data = request.get_json(silent=True) or {}
    sno = str(data.get('sno') or data.get('student_id') or '').strip()
    name = str(data.get('name') or '').strip()
    password = str(data.get('student_password') or data.get('password') or '').strip()

    if not sno or not name or not password:
        return jsonify({'success': False, 'message': '学号、姓名和密码不能为空'}), 400

    duplicate_student = db_connector.query("SELECT user_id FROM student WHERE sno = %s", (sno,))
    if getattr(db_connector, 'last_error', None):
        return db_error_response('检查学生学号失败')
    duplicate_user = db_connector.query("SELECT user_id FROM users WHERE user_no = %s", (sno,))
    if getattr(db_connector, 'last_error', None):
        return db_error_response('检查登录账号失败')
    if duplicate_student or duplicate_user:
        return jsonify({'success': False, 'message': '学号已存在'}), 400

    if not db_connector.execute(
        "INSERT INTO users (user_no, password, role) VALUES (%s, %s, %s)",
        (sno, password, 'student')
    ):
        return db_error_response('创建学生登录账号失败')

    user_id_rows = db_connector.query("SELECT LAST_INSERT_ID()")
    user_id = user_id_rows[0][0] if user_id_rows else None
    if not user_id:
        user_id_rows = db_connector.query(
            "SELECT user_id FROM users WHERE user_no = %s AND role = %s ORDER BY user_id DESC LIMIT 1",
            (sno, 'student')
        )
        user_id = user_id_rows[0][0] if user_id_rows else None
    if not user_id:
        return db_error_response('获取学生用户ID失败')

    if not db_connector.execute(
        "INSERT INTO student (sno, name, user_id, student_password) VALUES (%s, %s, %s, %s)",
        (sno, name, user_id, password)
    ):
        insert_error = getattr(db_connector, 'last_error', None)
        db_connector.execute("DELETE FROM users WHERE user_id = %s AND role = %s", (user_id, 'student'))
        db_connector.last_error = insert_error
        return db_error_response('创建学生目录失败')

    return jsonify({'success': True, 'message': '学生添加成功', 'student': {
        'id': user_id,
        'user_id': user_id,
        'sno': sno,
        'student_id': sno,
        'name': name,
        'student_password': password,
        'password': password,
        'role': 'student'
    }})


@app.route('/api/registration_requests', methods=['GET'])
def get_registration_requests():
    """获取当前教师需要审批的注册请求"""
    try:
        # 获取当前教师信息
        teacher_id = session['teacher_id']

        if not teacher_id:
            return jsonify({
                'success': False,
                'message': '未找到教师信息'
            }), 400

        # 检查数据库连接
        if not DB_AVAILABLE or db_connector is None:
            return jsonify({
                'success': False,
                'message': '数据库连接不可用'
            }), 500

        # 查询需要该教师审批的注册请求
        sql = "SELECT user_id, user_name, user_type, user_approve FROM register WHERE user_approve = %s"
        results = db_connector.query(sql, (teacher_id,))

        # 格式化结果
        requests = []
        for row in results:
            user_type_text = '教师' if row[2] == 'teacher' else '学生'
            requests.append({
                'user_id': row[0],
                'user_name': row[1],
                'user_type': row[2],
                'user_type_text': user_type_text,
                'user_approve': row[3]
            })

        return jsonify({
            'success': True,
            'requests': requests,
            'total': len(requests)
        })
    except Exception as e:
        print(f"获取注册请求失败：{e}")
        return jsonify({
            'success': False,
            'message': f'获取注册请求失败：{str(e)}'
        }), 500


@app.route('/api/approve_registration', methods=['POST'])
def approve_registration():
    """批准注册请求"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')

        if not user_id:
            return jsonify({
                'success': False,
                'message': '用户ID不能为空'
            }), 400

        # 检查数据库连接
        if not DB_AVAILABLE or db_connector is None:
            return jsonify({
                'success': False,
                'message': '数据库连接不可用'
            }), 500

        # 1. 从register表获取用户信息
        sql_get_user = "SELECT user_id, user_name, user_password, user_type FROM register WHERE user_id = %s"
        user_result = db_connector.query(sql_get_user, (user_id,))

        if not user_result:
            return jsonify({
                'success': False,
                'message': '用户不存在'
            }), 404

        user_data = user_result[0]

        # 2. 先将用户信息插入到users表中
        user_no = user_data[0]  # user_id作为user_no字段的值
        password = user_data[2]
        role = user_data[3]

        sql_add_user = "INSERT INTO users (user_no, password, role) VALUES (%s, %s, %s)"
        success = db_connector.execute(sql_add_user, (user_no, password, role))

        if not success:
            return jsonify({
                'success': False,
                'message': '添加用户到users表失败'
            }), 500

        # 获取刚刚插入到users表的自增ID
        # 假设db_connector有一个方法可以获取最后插入的ID
        try:
            # 尝试使用MySQL特有的方法获取最后插入的ID
            last_insert_id_result = db_connector.query("SELECT LAST_INSERT_ID()")
            if last_insert_id_result and len(last_insert_id_result) > 0:
                users_user_id = last_insert_id_result[0][0]
            else:
                # 如果无法获取，尝试通过user_no查询
                sql_get_user_id = "SELECT user_id FROM users WHERE user_no = %s"
                user_id_result = db_connector.query(sql_get_user_id, (user_no,))
                if user_id_result and len(user_id_result) > 0:
                    users_user_id = user_id_result[0][0]
                else:
                    raise Exception("无法获取插入的用户ID")
        except Exception as e:
            print(f"获取用户ID失败：{e}")
            return jsonify({
                'success': False,
                'message': f'获取用户ID失败：{str(e)}'
            }), 500

        # 3. 根据用户类型将用户添加到相应的表
        if user_data[3] == 'student':
            # 添加到student表，包含user_id字段
            sql_add_student = "INSERT INTO student (sno, name, student_password, user_id) VALUES (%s, %s, %s, %s)"
            success = db_connector.execute(sql_add_student, (user_data[0], user_data[1], user_data[2], users_user_id))
        else:
            # 添加到teacher表，包含user_id字段
            sql_add_teacher = "INSERT INTO teacher (tno, name, teacher_password, user_id) VALUES (%s, %s, %s, %s)"
            success = db_connector.execute(sql_add_teacher, (user_data[0], user_data[1], user_data[2], users_user_id))

        if not success:
            return jsonify({
                'success': False,
                'message': '添加用户到正式表失败'
            }), 500

        # 4. 从register表中删除记录（因为已批准）
        sql_delete = "DELETE FROM register WHERE user_id = %s"
        success = db_connector.execute(sql_delete, (user_id,))

        if not success:
            return jsonify({
                'success': False,
                'message': '更新注册状态失败'
            }), 500

        return jsonify({
            'success': True,
            'message': '注册请求已批准'
        })
    except Exception as e:
        print(f"批准注册请求失败：{e}")
        return jsonify({
            'success': False,
            'message': f'批准注册请求失败：{str(e)}'
        }), 500


@app.route('/api/reject_registration', methods=['POST'])
def reject_registration():
    """拒绝注册请求"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        reason = data.get('reason', '未提供拒绝理由')

        if not user_id:
            return jsonify({
                'success': False,
                'message': '用户ID不能为空'
            }), 400

        # 检查数据库连接
        if not DB_AVAILABLE or db_connector is None:
            return jsonify({
                'success': False,
                'message': '数据库连接不可用'
            }), 500

        # 从register表中删除记录（因为已拒绝）
        sql = "DELETE FROM register WHERE user_id = %s"
        success = db_connector.execute(sql, (user_id,))

        if not success:
            return jsonify({
                'success': False,
                'message': '更新注册状态失败'
            }), 500

        return jsonify({
            'success': True,
            'message': '注册请求已拒绝'
        })
    except Exception as e:
        print(f"拒绝注册请求失败：{e}")
        return jsonify({
            'success': False,
            'message': f'拒绝注册请求失败：{str(e)}'
        }), 500


@app.route('/api/student/<int:student_id>', methods=['DELETE'])
def delete_student(student_id):
    """Delete a student and the matching student login user."""
    if not db_connector:
        return jsonify({'success': False, 'message': '数据库连接不可用'}), 500

    existing = db_connector.query("SELECT sno FROM student WHERE user_id = %s", (student_id,))
    if getattr(db_connector, 'last_error', None):
        return db_error_response('查询学生失败')
    if not existing:
        return jsonify({'success': False, 'message': '学生不存在'}), 404

    if not db_connector.execute("DELETE FROM student WHERE user_id = %s", (student_id,)):
        return db_error_response('删除学生目录失败')

    if not db_connector.execute("DELETE FROM users WHERE user_id = %s AND role = %s", (student_id, 'student')):
        return db_error_response('删除学生登录账号失败')

    return jsonify({'success': True, 'message': '学生删除成功'})


@app.route('/api/student/<int:student_id>', methods=['GET'])
def get_student(student_id):
    """Get one student record by users.user_id."""
    if not db_connector:
        return jsonify({'success': False, 'message': '数据库连接不可用'}), 500

    rows = db_connector.query("""
        SELECT s.sno, s.name, s.user_id, s.student_password,
               u.user_no, u.password, u.role
        FROM student s
        LEFT JOIN users u ON s.user_id = u.user_id
        WHERE s.user_id = %s
    """, (student_id,))
    if getattr(db_connector, 'last_error', None):
        return db_error_response('查询学生失败')
    if not rows:
        return jsonify({'success': False, 'message': '学生不存在'}), 404

    sno, name, user_id, student_password, user_no, user_password, role = rows[0]
    password = student_password or user_password or ''
    return jsonify({'success': True, 'student': {
        'id': user_id,
        'user_id': user_id,
        'sno': str(sno) if sno is not None else '',
        'student_id': str(sno) if sno is not None else '',
        'name': name or '',
        'student_password': password,
        'password': password,
        'user_no': str(user_no) if user_no is not None else '',
        'role': role or 'student'
    }})


@app.route('/api/student/<int:student_id>', methods=['PUT'])
def edit_student(student_id):
    """Update a student and matching login user."""
    if not db_connector:
        return jsonify({'success': False, 'message': '数据库连接不可用'}), 500

    data = request.get_json(silent=True) or {}
    sno_new = str(data.get('sno') or data.get('student_id') or '').strip()
    name = str(data.get('name') or '').strip()
    password = str(data.get('student_password') or data.get('password') or '').strip()

    if not sno_new or not name or not password:
        return jsonify({'success': False, 'message': '学号、姓名和密码不能为空'}), 400

    try:
        with closing(RosterDatabase()) as db:
            db.connect()
            with db.connection.cursor() as cur:
                cur.execute("SELECT sno FROM student WHERE user_id=%s FOR UPDATE", (student_id,))
                if not cur.fetchone():
                    raise FormError('学生不存在', 404)
                cur.execute("SELECT user_id FROM users WHERE user_no=%s AND user_id<>%s LIMIT 1",
                            (sno_new, student_id))
                if cur.fetchone():
                    raise FormError('学号已存在')
                cur.execute("UPDATE users SET user_no=%s,password=%s WHERE user_id=%s AND role='student'",
                            (sno_new, password, student_id))
                cur.execute("UPDATE student SET sno=%s,name=%s,student_password=%s WHERE user_id=%s",
                            (sno_new, name, password, student_id))
                if 'class_id' in data:
                    set_student_class(cur, sno_new, data['class_id'])
                db.connection.commit()
    except FormError as exc:
        return jsonify(success=False, message=str(exc)), exc.status
    except IntegrityError as exc:
        message = '学号已存在' if exc.errno == 1062 else '学生或班级信息已变更，请刷新后重试'
        return jsonify(success=False, message=message), 409
    except Error:
        app.logger.exception('保存学生信息失败')
        return jsonify(success=False, message='保存学生信息失败'), 503

    return jsonify({'success': True, 'message': '学生信息更新成功', 'student': {
        'id': student_id,
        'user_id': student_id,
        'sno': sno_new,
        'student_id': sno_new,
        'name': name,
        'student_password': password,
        'password': password,
        'role': 'student'
    }})



def format_db_datetime(value):
    if value is None:
        return ''
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    return str(value)


def parse_score_value(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def split_knowledge_points(value):
    if not value:
        return []
    text = str(value).replace('\uff0c', ',').replace('\u3001', ',').replace(';', ',').replace('\uff1b', ',')
    return [item.strip() for item in text.split(',') if item.strip()]


@app.route('/api/student_score/<sno>', methods=['GET'])
def get_student_score(sno):
    """Get the latest score for one student from exam_result."""
    if not db_connector:
        return jsonify({'success': False, 'message': 'Database connection unavailable'}), 500

    rows = db_connector.query(
        """
        SELECT test_score, test_name
        FROM exam_result
        WHERE student_no = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (sno,)
    )
    if getattr(db_connector, 'last_error', None):
        return db_error_response('Failed to load student score')

    score = parse_score_value(rows[0][0]) if rows else 0
    return jsonify({'success': True, 'sno': sno, 'score': score, 'test_name': rows[0][1] if rows else ''})


@app.route('/api/get_score_summary', methods=['GET'])
def get_score_summary():
    """Get score statistics from exam_result."""
    if not db_connector:
        return jsonify({'success': False, 'message': 'Database connection unavailable'}), 500

    rows = db_connector.query('SELECT test_score FROM exam_result')
    if getattr(db_connector, 'last_error', None):
        return db_error_response('Failed to load score summary')

    scores = [parse_score_value(row[0]) for row in rows]
    if not scores:
        return jsonify({'success': True, 'summary': {'average': 0, 'highest': 0, 'lowest': 0, 'total': 0}})

    return jsonify({'success': True, 'summary': {
        'average': round(sum(scores) / len(scores), 1),
        'highest': max(scores),
        'lowest': min(scores),
        'total': len(scores)
    }})


@app.route('/api/get_students_scores', methods=['GET'])
def get_students_scores():
    """Get all student score rows from exam_result."""
    if not db_connector:
        return jsonify({'success': False, 'message': 'Database connection unavailable'}), 500

    rows = db_connector.query(
        """
        SELECT er.id, er.student_no, COALESCE(s.name, er.student_name), er.test_score,
               er.test_name, er.knowledge, et.publish_time
        FROM exam_result er
        LEFT JOIN student s ON CAST(er.student_no AS UNSIGNED) = s.sno
        LEFT JOIN exam_test et ON CAST(er.test_id AS UNSIGNED) = et.test_id
        ORDER BY er.id DESC
        """
    )
    if getattr(db_connector, 'last_error', None):
        return db_error_response('Failed to load student scores')

    students = []
    for row in rows:
        students.append({
            'id': row[0],
            'sno': str(row[1] or ''),
            'student_id': str(row[1] or ''),
            'name': row[2] or '',
            'score': parse_score_value(row[3]),
            'subject': row[4] or 'Wiring exam',
            'test_name': row[4] or '',
            'exam_time': format_db_datetime(row[6]),
            'weak_points': split_knowledge_points(row[5])
        })

    return jsonify({'success': True, 'students': students, 'total': len(students)})


@app.route('/api/get_score_distribution', methods=['GET'])
def get_score_distribution():
    """Get score distribution from exam_result."""
    if not db_connector:
        return jsonify({'success': False, 'message': 'Database connection unavailable'}), 500

    rows = db_connector.query('SELECT test_score FROM exam_result')
    if getattr(db_connector, 'last_error', None):
        return db_error_response('Failed to load score distribution')

    buckets = [
        {'range': '90-100', 'count': 0},
        {'range': '80-89', 'count': 0},
        {'range': '70-79', 'count': 0},
        {'range': '60-69', 'count': 0},
        {'range': '0-59', 'count': 0},
    ]
    for row in rows:
        score = parse_score_value(row[0])
        if score >= 90:
            buckets[0]['count'] += 1
        elif score >= 80:
            buckets[1]['count'] += 1
        elif score >= 70:
            buckets[2]['count'] += 1
        elif score >= 60:
            buckets[3]['count'] += 1
        else:
            buckets[4]['count'] += 1

    return jsonify({'success': True, 'distribution': buckets})


@app.route('/api/get_weak_knowledge_points', methods=['GET'])
def get_weak_knowledge_points():
    """Summarize weak knowledge points from exam_result.knowledge."""
    if not db_connector:
        return jsonify({'success': False, 'message': 'Database connection unavailable'}), 500

    rows = db_connector.query('SELECT knowledge FROM exam_result WHERE knowledge IS NOT NULL AND knowledge <> ""')
    if getattr(db_connector, 'last_error', None):
        return db_error_response('Failed to load weak knowledge points')

    counts = {}
    total = 0
    for row in rows:
        points = split_knowledge_points(row[0])
        total += 1
        for point in points:
            counts[point] = counts.get(point, 0) + 1

    result = [
        {'point': point, 'errorRate': round(count / total * 100, 1) if total else 0, 'count': count}
        for point, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    ]
    return jsonify({'success': True, 'points': result})



@app.route('/api/get_exams', methods=['GET'])
def get_exams():
    """Get exam list from exam_test."""
    teacher_id = session.get('teacher_id')
    if not teacher_id:
        return jsonify(success=False, message='请先登录教师账号'), 401
    try:
        if not DB_AVAILABLE or db_connector is None:
            return jsonify({'success': False, 'message': 'Database connection unavailable'}), 500

        teacher_info = None
        if teacher_id:
            teacher_rows = db_connector.query('SELECT tno, name FROM teacher WHERE tno = %s LIMIT 1', (teacher_id,))
            if teacher_rows:
                teacher_info = {'tno': str(teacher_rows[0][0]), 'teacher_name': teacher_rows[0][1]}

        sql = """
            SELECT e.id, e.test_name, e.test_type, e.duration_minutes,
                   e.publish_time, e.deadline_time, e.create_time, e.update_time,
                   e.teacher_id, t.name
            FROM exam_test e
            LEFT JOIN teacher t ON CAST(e.teacher_id AS UNSIGNED) = t.tno
            WHERE e.issuer_tno = %s
            ORDER BY e.publish_time DESC, e.id DESC
        """
        rows = db_connector.query(sql, (teacher_id,))
        if getattr(db_connector, 'last_error', None):
            return db_error_response('Failed to load exams')

        exams = []
        for row in rows:
            row_teacher_info = {
                'tno': str(row[8] or ''),
                'teacher_name': row[9] or (teacher_info or {}).get('teacher_name', 'Unknown')
            }
            exams.append({
                'id': row[0],
                'name': row[1],
                'test_name': row[1],
                'type': row[2],
                'test_type': row[2],
                'duration': row[3],
                'duration_minutes': row[3],
                'publish_time': format_db_datetime(row[4]),
                'deadline_time': format_db_datetime(row[5]),
                'create_time': format_db_datetime(row[6]),
                'update_time': format_db_datetime(row[7]),
                'teacher_info': row_teacher_info
            })

        return jsonify({'success': True, 'exams': exams, 'total': len(exams), 'teacher_info': teacher_info})
    except Exception as exc:
        return jsonify({'success': False, 'message': f'Failed to load exams: {exc}'}), 500


@socketio.on('connect')
def handle_connect():
    """处理客户端连接"""
    teacher_id = request.sid
    print(f"教师 {teacher_id} 已连接")
    emit('connection_established', {'teacher_id': teacher_id})


@socketio.on('disconnect')
def handle_disconnect():
    """处理客户端断开连接"""
    teacher_id = request.sid
    print(f"教师 {teacher_id} 已断开连接")


@socketio.on('student_connect')
def handle_student_connect(data):
    """处理学生连接事件"""
    sno = data.get('sno')
    student_name = data.get('student_name')
    if sno and student_name:
        connected_students[sno] = {
            'sno': sno,
            'student_name': student_name,
            'connected_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f"学生 {sno} ({student_name}) 已连接")
        # 广播给所有教师客户端
        socketio.emit('student_connected', connected_students[sno])


@socketio.on('update_score')
def handle_update_score(data):
    """处理成绩更新事件"""
    sno = data.get('sno')
    score = data.get('score')
    if sno and score is not None:
        student_scores[sno] = score
        print(f"更新学生 {sno} 的成绩为 {score}")
        # 广播给所有教师客户端
        socketio.emit('score_updated', {
            'sno': sno,
            'score': score
        })


@app.route('/api/rule-server/start', methods=['POST'])
def start_rule_server():
    """启动规则下载服务"""
    try:
        # 这里应该实现实际的启动逻辑
        # 目前返回模拟成功响应
        return jsonify({
            'success': True,
            'message': '规则下载服务已启动',
            'status': 'running'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'启动失败: {str(e)}'
        }), 500


@app.route('/api/rule-server/stop', methods=['POST'])
def stop_rule_server():
    """停止规则下载服务"""
    try:
        # 这里应该实现实际的停止逻辑
        # 目前返回模拟成功响应
        return jsonify({
            'success': True,
            'message': '规则下载服务已停止',
            'status': 'stopped'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'停止失败: {str(e)}'
        }), 500


if __name__ == '__main__':
    print("教师端Web服务器启动中...")
    try:
        # 尝试使用eventlet
        import eventlet

        eventlet.monkey_patch()
        socketio.run(
            app,
            host=TEACHER_WEB_CONFIG["host"],
            port=TEACHER_WEB_CONFIG["port"],
            debug=True,
            use_reloader=False,
        )
    except Exception as e:
        print(f"使用eventlet启动失败: {e}")
        print("尝试使用默认模式启动...")
        # 使用默认模式
        socketio.run(
            app,
            host=TEACHER_WEB_CONFIG["host"],
            port=TEACHER_WEB_CONFIG["port"],
            debug=True,
            use_reloader=False,
        )
