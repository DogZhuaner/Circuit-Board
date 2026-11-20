import os
import sys
import json
from contextlib import closing
from datetime import datetime
from flask import abort, Flask, render_template, jsonify, redirect, request, session, url_for
from flask_socketio import SocketIO

# 添加项目根目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
# 添加项目根目录到Python路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
# 添加script目录到Python路径（服务器部署时可不存在）
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../script')))

from itsdangerous import BadSignature
from db import MySQLConnector as StudentDatabase
from exam_results import exam_result, verified_receipt
from exam_access import ExamEntryError, exam_ticket, exam_rule_ticket, require_open_exam
from global_config import Global_Config
from practice_rules import default_rule
try:
    from script.detect_SwtichHand import start_hand_detection, stop_hand_detection
except Exception:
    start_hand_detection = None
    stop_hand_detection = None

# 添加tools目录到Python路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../tools')))
from student_webui.model_service import models, public_settings, read_settings
from tools.connector import MySQLConnector
from tools.config import (
    portal_login_url,
    LOCAL_CLIENT_BASE as CONFIG_LOCAL_CLIENT_BASE,
    RULE_SERVER_CONFIG,
    STUDENT_WEB_CONFIG,
)

# 导入项目模块 - 使用延迟导入提高启动速度
detect_module = None
config_module = None
question_generator = None
score_visualizer = None


def reset_contact_status():
    import os,json,shutil
    union_path = Global_Config.union_find_json_path
    file_path = Global_Config.old_result_csv_path
    csv_path = os.path.join(file_path,'merge_result.csv')
    default_csv = os.path.join(Global_Config.rule_path,'merge_result.csv')
    # 检查文件是否存在
    if os.path.exists(union_path):
        try:
            with open(union_path, 'w') as f:
                json.dump([], f, ensure_ascii=False, indent=4)
            print("并查集缓存文件内容已清空。")
        except Exception as e:
            print(f"删除并查集文件时发生错误: {e}")
    else:
        print("并查集缓存文件不存在。")

    os.makedirs(Global_Config.result_csv_path, exist_ok=True)
    # 执行复制
    shutil.copy(default_csv, Global_Config.result_csv_path)
    shutil.copy(default_csv, csv_path)
    print("接线状态已重置，请重新开始接线。")


def get_config_module():
    global config_module
    if config_module is None:
        try:
            from global_config import Login_Session, Global_Config, reset_session_score, get_global_score
            config_module = {
                'Login_Session': Login_Session,
                'Global_Config': Global_Config,
                'reset_session_score': reset_session_score,
                'get_global_score': get_global_score
            }
        except ImportError:
            print("警告: 无法导入global_config模块，将使用模拟配置")

            class MockLoginSession:
                sno = "2024001"
                account_name = "测试学生"

            class MockGlobalConfig:
                student_json = "student_config.json"
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


def get_student_no_from_request():
    student_no = request.args.get('student_no') or request.args.get('student_id')
    if not student_no and request.is_json:
        student_no = (request.get_json(silent=True) or {}).get('student_no')
    return str(student_no or '').strip()


def get_question_generator():
    global question_generator
    if question_generator is None:
        try:
            from scripts.question_generator import QuestionGenerator
            question_generator = QuestionGenerator()
        except ImportError as e:
            print(f"警告: 无法导入question_generator模块: {e}")
            question_generator = None
    return question_generator


def get_score_visualizer():
    global score_visualizer
    if score_visualizer is None:
        try:
            from scripts.score_visualizer import ScoreVisualizer
            score_visualizer = ScoreVisualizer()
        except ImportError as e:
            print(f"警告: 无法导入score_visualizer模块: {e}")
            score_visualizer = None
    return score_visualizer


app = Flask(__name__)
app.register_blueprint(models)
app.config.update(SECRET_KEY=STUDENT_WEB_CONFIG["secret_key"], SESSION_COOKIE_NAME="circuit_entry")
socketio = SocketIO(app, cors_allowed_origins="*", transports=['websocket', 'polling'])

# 进程级运行变量仅保留给旧版单机调试接口使用，不作为多用户学生状态来源。
current_score = 0

LOCAL_CLIENT_BASE = CONFIG_LOCAL_CLIENT_BASE


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


def get_rule_directory():
    rule_dir = os.path.abspath(str(Global_Config.rule_path))
    os.makedirs(rule_dir, exist_ok=True)
    return rule_dir


def resolve_rule_file(filename):
    safe_name = normalize_rule_filename(filename)
    rule_dir = get_rule_directory()
    file_path = os.path.abspath(os.path.join(rule_dir, safe_name))
    if os.path.commonpath([rule_dir, file_path]) != rule_dir:
        raise ValueError('规则文件路径无效')
    return safe_name, file_path


def validate_rule_payload(rules):
    if not isinstance(rules, list) or not rules:
        raise ValueError('规则文件不能为空')

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


@app.route('/api/start_detection', methods=['POST'])
def start_detection():
    """旧版接口：服务器无法代替远程浏览器访问学生本机 127.0.0.1。"""
    return jsonify({
        "success": False,
        "deprecated": True,
        "message": "请由学生端浏览器直接请求本地网关 http://127.0.0.1:6001/api/yolo/start"
    }), 410


@app.route('/api/stop_detection', methods=['POST'])
def stop_detection():
    """旧版接口：服务器无法代替远程浏览器访问学生本机 127.0.0.1。"""
    return jsonify({
        "success": False,
        "deprecated": True,
        "message": "请由学生端浏览器直接请求本地网关 http://127.0.0.1:6001/api/yolo/stop"
    }), 410


@app.route('/api/get_detection_status', methods=['GET'])
def get_detection_status():
    """旧版接口：实时检测状态应由浏览器直接从学生本机网关读取。"""
    return jsonify({
        "success": False,
        "deprecated": True,
        "message": "请由学生端浏览器直接请求本地网关 http://127.0.0.1:6001/api/yolo/status"
    }), 410


@app.route('/')
def index():
    """主页面"""
    student = session.get('student')
    if not student:
        return redirect(portal_login_url(request.host_url, request.script_root))
    return render_student_page(student['id'], student['name']), 200, {'Cache-Control': 'no-store'}


def exam_identity() -> tuple:
    try:
        exam_id, student_id, name = exam_ticket.loads(request.args.get('ticket', ''))
        if (session.get('student') or {}).get('id') != student_id:
            raise ExamEntryError("请使用本人学生账号登录并选择考试", 403)
        return exam_id, student_id, name
    except BadSignature:
        raise ExamEntryError("请从考试入口登录后进入", 403) from None


@app.get('/exam')
def exam_page():
    if not session.get('exam_entry_ticket') or session['exam_entry_ticket'] != request.args.get('ticket'):
        return redirect('/entry?mode=exam')
    try:
        exam_id, student_id, student_name = exam_identity()
        exam = require_open_exam(exam_id, student_id)
        score = exam_result(exam_id, student_id, student_name)
    except ExamEntryError as error:
        abort(error.status, description=str(error))
    return render_student_page(student_id, student_name, exam, score), 200, {'Cache-Control': 'no-store'}


@app.get('/api/exam/entry')
def check_exam_entry():
    try:
        exam_id, student_id, student_name = exam_identity()
        rule_ticket = exam_rule_ticket(exam_id, student_id, close_submission={
            'path': url_for('submit_closed_exam'), 'ticket': request.args['ticket']
        })
        score = exam_result(exam_id, student_id, student_name)
    except ExamEntryError as error:
        return jsonify(success=False, message=str(error)), error.status
    return jsonify(success=True, submitted_score=score, rule_ticket=rule_ticket), 200, {'Cache-Control': 'no-store'}


@app.post('/api/exam/closed-result')
def submit_closed_exam():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not all(isinstance(body.get(k), str) for k in ('ticket', 'receipt', 'archive')):
        return jsonify(success=False, message='缺少交卷凭据或接线记录'), 400
    try:
        exam_id, student_id, name = exam_ticket.loads(body['ticket'])
        verified_receipt(body['receipt'], student_id, exam_id)
        score = exam_result(exam_id, student_id, name, submission=body)
    except BadSignature:
        return jsonify(success=False, message='考试凭据无效'), 403
    except ExamEntryError as error:
        return jsonify(success=False, message=str(error)), error.status
    return jsonify(success=True, score=score), 200, {'Cache-Control': 'no-store'}


@app.route('/api/exam/result', methods=['GET', 'POST'])
def submit_exam_result():
    try:
        exam_id, student_id, student_name = exam_identity()
        if request.method == 'GET':
            score = exam_result(exam_id, student_id, student_name, check_open=True)
            return jsonify(success=True, score=score), 200, {'Cache-Control': 'no-store'}
        body = request.get_json(silent=True)
        score = exam_result(exam_id, student_id, student_name, submission=body if isinstance(body, dict) else {})
    except ExamEntryError as error:
        return jsonify(success=False, message=str(error)), error.status
    return jsonify(success=True, score=score), 200, {'Cache-Control': 'no-store'}


def render_student_page(student_id, student_name, exam=None, submitted_score=None):
    try:
        with closing(StudentDatabase()) as db:
            rows = db.query(
                'SELECT DISTINCT c.name FROM class_student m JOIN teaching_class c ON c.id=m.class_id '
                'WHERE m.student_no=%s ORDER BY c.name', (student_id,)
            )
        class_label = '、'.join(name for name, in rows) or '暂未分班'
    except RuntimeError:
        app.logger.exception('读取学生班级失败')
        class_label = '暂时无法读取'
    return render_template(
        'index.html',
        local_client_base=LOCAL_CLIENT_BASE,
        selected_exam=exam,
        submitted_score=submitted_score,
        practice_model_settings=public_settings(read_settings(student_id)) if exam is None else None,
        initial_student_info={
            'student_id': student_id,
            'student_name': student_name,
            'class_label': class_label,
        },
    )


@app.route('/api/student_info', methods=['GET'])
def get_student_info():
    """获取本次请求携带的学生信息；不再读取进程级 Login_Session。"""
    return jsonify({
        'student_id': request.args.get('student_id', '').strip(),
        'student_name': request.args.get('student_name', '').strip()
    })


@app.route('/api/rules', methods=['GET'])
def list_rule_files():
    """获取可选考核规则文件列表。"""
    try:
        rule_dir = get_rule_directory()
        default_name = default_rule(rule_dir)
        files = []

        for filename in sorted(os.listdir(rule_dir), key=lambda name: name.lower()):
            if not filename.lower().endswith('.json'):
                continue
            if filename == 'current_rule.json':
                continue
            file_path = os.path.join(rule_dir, filename)
            if not os.path.isfile(file_path):
                continue

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    rules = validate_rule_payload(json.load(f))
                    rule_count = len(rules)
            except Exception:
                rules = None
                rule_count = None

            stat = os.stat(file_path)
            files.append({
                'filename': filename,
                'rule_count': rule_count,
                'size': stat.st_size,
                'modified_time': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                'is_current': filename == default_name
            })

        return jsonify({'success': True, 'files': files, 'total': len(files)})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取规则文件列表失败：{str(e)}'}), 500


@app.post('/api/rules/activate')
def activate_rule_file():
    try:
        name, path = resolve_rule_file((request.get_json(silent=True) or {}).get('filename'))
        if not os.path.isfile(path) or name.lower() == 'current_rule.json':
            return jsonify(success=False, message='所选规则文件不存在'), 404
        return jsonify(success=True, filename=name, download_url=url_for('download_rule_file', filename=name))
    except ValueError as error:
        return jsonify(success=False, message=str(error)), 400


@app.get('/api/rules/files/<filename>/download')
def download_rule_file(filename):
    try:
        name, path = resolve_rule_file(filename)
    except ValueError:
        abort(404)
    if filename != name or name.lower() == 'current_rule.json' or not os.path.isfile(path):
        abort(404)
    try:
        with open(path, encoding='utf-8') as source:
            rules = validate_rule_payload(json.load(source))
    except (ValueError, OSError):
        return jsonify(success=False, message='规则文件无效或无法读取'), 422
    return jsonify(rules), 200, {'Cache-Control': 'no-store'}


@app.get('/api/rules/current')
def get_default_rule():
    name = default_rule(get_rule_directory())
    if not name:
        return jsonify(success=False, message='未选择默认练习规则'), 404
    _, path = resolve_rule_file(name)
    try:
        with open(path, encoding='utf-8') as source:
            raw = source.read()
        rules = validate_rule_payload(json.loads(raw))
    except (OSError, ValueError):
        return jsonify(success=False, message='规则文件无效或无法读取'), 422
    return jsonify(success=True, filename=name, active_filename=name, active_rule_path=path,
                   rules=rules, rules_count=len(rules), raw=raw,
                   download_url=url_for('download_rule_file', filename=name),
                   download_url_absolute=url_for('download_rule_file', filename=name, _external=True))


@app.get('/api/rules/current/download')
def download_default_rule():
    name = default_rule(get_rule_directory())
    if not name:
        return jsonify(success=False, message='未选择默认练习规则'), 404
    return download_rule_file(name)


# 新增：题目生成相关路由
@app.route('/api/get_subjects', methods=['GET'])
def get_subjects():
    """获取可用学科列表"""
    try:
        generator = get_question_generator()
        if generator is None:
            return jsonify({'success': False, 'message': '题目生成器未初始化'})

        subjects = generator.get_available_subjects()
        return jsonify({'success': True, 'subjects': subjects})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取学科列表失败: {str(e)}'})


@app.route('/api/get_topics', methods=['GET'])
def get_topics():
    """根据学科获取知识点列表"""
    try:
        subject = request.args.get('subject', '')
        if not subject:
            return jsonify({'success': False, 'message': '请指定学科'})

        generator = get_question_generator()
        if generator is None:
            return jsonify({'success': False, 'message': '题目生成器未初始化'})

        knowledge_list = generator.get_knowledge_by_subject(subject)
        return jsonify({'success': True, 'topics': knowledge_list})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取知识点列表失败: {str(e)}'})


@app.route('/api/generate_question', methods=['POST'])
def generate_question():
    """生成题目"""
    try:
        data = request.get_json()
        subject = data.get('subject', '')
        knowledge = data.get('knowledge', '')

        generator = get_question_generator()
        if generator is None:
            return jsonify({'success': False, 'message': '题目生成器未初始化'})

        question = generator.generate_question(
            subject=subject if subject else None,
            knowledge=knowledge if knowledge else None
        )

        if "error" in question:
            return jsonify({'success': False, 'message': question['error']})

        return jsonify({'success': True, 'question': question})
    except Exception as e:
        return jsonify({'success': False, 'message': f'生成题目失败: {str(e)}'})


@app.route('/api/generate_multiple_questions', methods=['POST'])
def generate_multiple_questions():
    """生成多道题目"""
    try:
        data = request.get_json()
        count = data.get('count', 5)
        subject = data.get('subject', '')

        generator = get_question_generator()
        if generator is None:
            return jsonify({'success': False, 'message': '题目生成器未初始化'})

        questions = generator.generate_multiple_questions(
            count=count,
            subject=subject if subject else None
        )

        return jsonify({'success': True, 'questions': questions})
    except Exception as e:
        return jsonify({'success': False, 'message': f'生成题目失败: {str(e)}'})


# 新增：数据可视化相关路由
@app.route('/api/get_score_summary', methods=['GET'])
def get_score_summary():
    """获取成绩统计摘要"""
    try:
        visualizer = get_score_visualizer()
        if visualizer is None:
            return jsonify({'success': False, 'message': '数据可视化器未初始化'})

        summary = visualizer.get_score_summary()
        return jsonify({'success': True, 'summary': summary})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取成绩摘要失败: {str(e)}'})


@app.route('/api/get_score_distribution_plot', methods=['GET'])
def get_score_distribution_plot():
    """获取成绩分布图"""
    try:
        visualizer = get_score_visualizer()
        if visualizer is None:
            return jsonify({'success': False, 'message': '数据可视化器未初始化'})

        plot_data = visualizer.create_score_distribution_plot()
        if not plot_data:
            return jsonify({'success': False, 'message': '无法生成分布图'})

        return jsonify({'success': True, 'plot_data': plot_data})
    except Exception as e:
        return jsonify({'success': False, 'message': f'生成分布图失败: {str(e)}'})


@app.route('/api/get_knowledge_analysis_plot', methods=['GET'])
def get_knowledge_analysis_plot():
    """获取知识点分析图"""
    try:
        visualizer = get_score_visualizer()
        if visualizer is None:
            return jsonify({'success': False, 'message': '数据可视化器未初始化'})

        plot_data = visualizer.create_knowledge_analysis_plot()
        if not plot_data:
            return jsonify({'success': False, 'message': '无法生成知识点分析图'})

        return jsonify({'success': True, 'plot_data': plot_data})
    except Exception as e:
        return jsonify({'success': False, 'message': f'生成知识点分析图失败: {str(e)}'})


@app.route('/api/get_student_knowledge_heatmap', methods=['GET'])
def get_student_knowledge_heatmap():
    """获取学生-知识点热力图"""
    try:
        visualizer = get_score_visualizer()
        if visualizer is None:
            return jsonify({'success': False, 'message': '数据可视化器未初始化'})

        plot_data = visualizer.create_student_knowledge_heatmap()
        if not plot_data:
            return jsonify({'success': False, 'message': '无法生成热力图'})

        return jsonify({'success': True, 'plot_data': plot_data})
    except Exception as e:
        return jsonify({'success': False, 'message': f'生成热力图失败: {str(e)}'})


@app.route('/api/get_score_knowledge_correlation', methods=['GET'])
def get_score_knowledge_correlation():
    """获取成绩与知识点相关性分析"""
    try:
        visualizer = get_score_visualizer()
        if visualizer is None:
            return jsonify({'success': False, 'message': '数据可视化器未初始化'})

        plot_data = visualizer.create_score_knowledge_correlation()
        if not plot_data:
            return jsonify({'success': False, 'message': '无法生成相关性分析图'})

        return jsonify({'success': True, 'plot_data': plot_data})
    except Exception as e:
        return jsonify({'success': False, 'message': f'生成相关性分析图失败: {str(e)}'})


@app.route('/api/get_top_students', methods=['GET'])
def get_top_students():
    """获取前N名学生信息"""
    try:
        top_n = request.args.get('top_n', 5, type=int)
        visualizer = get_score_visualizer()
        if visualizer is None:
            return jsonify({'success': False, 'message': '数据可视化器未初始化'})

        top_students = visualizer.get_top_students(top_n)
        return jsonify({'success': True, 'top_students': top_students})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取学生信息失败: {str(e)}'})


@app.route('/api/get_knowledge_analysis', methods=['GET'])
def get_knowledge_analysis():
    """获取知识点分析数据"""
    try:
        visualizer = get_score_visualizer()
        if visualizer is None:
            return jsonify({'success': False, 'message': '数据可视化器未初始化'})

        analysis_data = visualizer.get_knowledge_analysis()
        return jsonify({'success': True, 'analysis': analysis_data})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取知识点分析失败: {str(e)}'})


@app.route('/api/get_knowledge_list', methods=['GET'])
def get_knowledge_list():
    """获取所有知识点列表"""
    try:
        # 直接返回用户提供的知识点列表
        knowledge_list = [
            '电力拖动系统', '负载转矩', '电磁转矩', '机械特性', '固有机械特性', '人为机械特性',
            '启动', '直接启动', '降压启动', '星 - 三角启动', '自耦变压器降压启动', '软启动',
            '调速', '无级调速', '有级调速', '变极调速', '变频调速', '变转差率调速', '串级调速',
            '制动', '能耗制动', '反接制动', '回馈制动', '直流电动机拖动', '交流异步电动机拖动',
            '交流同步电动机拖动', '伺服拖动系统', '步进电动机拖动', '拖动系统稳定性', '电机选型',
            '传动比', '飞轮矩', '动态响应', '静态转速降', '调速范围', '稳速精度', '电枢回路',
            '励磁回路', '变压调速（直流）', '弱磁调速（直流）', 'V/F 控制', '矢量控制',
            '直接转矩控制（DTC）', '负载特性', '恒转矩负载', '恒功率负载', '通风机类负载',
            '启动转矩', '最大转矩', '转差率', '同步转速', '额定转速', '过载能力', '启动电流',
            '制动电阻', '调速装置', '变频器', '伺服驱动器', '电枢电阻调速', '电磁制动',
            '机械制动', '拖动系统效率', '动态调速性能', '静态调速性能', '电机正反转控制',
            '拖动系统建模', '仿真分析', '实际运行调试', '负载匹配', '节能控制'
        ]
        return jsonify({'success': True, 'knowledge_list': knowledge_list})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取知识点列表失败: {str(e)}'})


@app.route('/api/get_air_switch_status', methods=['GET'])
def get_air_switch_status():
    return jsonify({
        "success": False,
        "deprecated": True,
        "message": "空气开关状态属于学生本机实时状态，请由浏览器请求 http://127.0.0.1:6001/api/get_air_switch_status"
    }), 410


@app.route('/api/get_score_and_contact', methods=['GET'])
def get_score_and_contact():
    return jsonify({
        "success": False,
        "deprecated": True,
        "message": "接线实时结果属于学生本机状态，请由浏览器请求 http://127.0.0.1:6001/api/get_score_and_contact"
    }), 410


@app.route('/api/get_wiring_status', methods=['GET'])
def get_wiring_status():
    """旧版接口：完整接线情况应由浏览器直接从学生本机网关读取。"""
    return jsonify({
        "success": False,
        "deprecated": True,
        "message": "接线实时结果属于学生本机状态，请由浏览器请求 http://127.0.0.1:6001/api/get_score_and_contact"
    }), 410


# 新的学生成绩可视化API
@app.route('/api/student/exams', methods=['GET'])
def get_student_exams():
    """获取学生参加过的所有考试"""
    try:
        student_no = get_student_no_from_request()

        if not student_no:
            return jsonify({'success': False, 'message': '缺少 student_no'})

        # 连接数据库查询学生参加过的考试
        connector = MySQLConnector()
        sql = "SELECT DISTINCT test_id, test_name FROM exam_result WHERE student_no = %s ORDER BY test_id"
        results = connector.query(sql, (student_no,))

        # 格式化结果
        exams = []
        for row in results:
            exams.append({
                'test_id': row[0],
                'test_name': row[1]
            })

        return jsonify({'success': True, 'exams': exams})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取考试列表失败: {str(e)}'})


@app.route('/api/student/score', methods=['GET'])
def get_student_score():
    """获取学生的成绩详情"""
    try:
        student_no = get_student_no_from_request()

        if not student_no:
            return jsonify({'success': False, 'message': '缺少 student_no'})

        # 连接数据库查询学生成绩
        connector = MySQLConnector()
        sql = "SELECT test_id, test_name, test_score FROM exam_result WHERE student_no = %s ORDER BY test_id"
        results = connector.query(sql, (student_no,))

        # 格式化结果
        scores = []
        for row in results:
            scores.append({
                'test_id': row[0],
                'test_name': row[1],
                'score': int(row[2])
            })

        return jsonify({'success': True, 'scores': scores})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取成绩详情失败: {str(e)}'})


@app.route('/api/student/knowledge', methods=['GET'])
def get_student_knowledge():
    """获取学生的易错知识点"""
    try:
        student_no = get_student_no_from_request()

        if not student_no:
            return jsonify({'success': False, 'message': '缺少 student_no'})

        # 连接数据库查询学生易错知识点
        connector = MySQLConnector()
        sql = "SELECT knowledge FROM exam_result WHERE student_no = %s AND knowledge IS NOT NULL AND knowledge != ''"
        results = connector.query(sql, (student_no,))

        # 统计知识点出现频率
        knowledge_count = {}
        for row in results:
            # 分割知识点（如果有多个）
            knowledge_list = row[0].split('，')
            for knowledge in knowledge_list:
                knowledge = knowledge.strip()
                if knowledge:
                    knowledge_count[knowledge] = knowledge_count.get(knowledge, 0) + 1

        # 转换为列表格式
        knowledge_list = [{'name': k, 'count': v} for k, v in knowledge_count.items()]
        # 按出现次数排序
        knowledge_list.sort(key=lambda x: x['count'], reverse=True)

        return jsonify({'success': True, 'knowledge': knowledge_list})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取易错知识点失败: {str(e)}'})


@app.route('/api/get_current_score', methods=['GET'])
def get_current_score():
    """旧版接口：实时分数应由浏览器直接从学生本机网关读取。"""
    return jsonify({
        "success": False,
        "deprecated": True,
        "message": "实时分数属于学生本机状态，请由浏览器请求 http://127.0.0.1:6001/api/get_current_score"
    }), 410


@app.route('/api/test_score_update', methods=['POST'])
def test_score_update():
    """旧版测试接口：不再通过服务端全局变量模拟实时分数。"""
    return jsonify({
        "success": False,
        "deprecated": True,
        "message": "实时分数请在学生本机 local_gateway.py 内测试"
    }), 410

@app.route('/api/test_set_contact', methods=['GET', 'POST'])
def test_set_contact():
    """旧版测试接口：不再通过服务端全局变量模拟接线触点。"""
    return jsonify({
        "success": False,
        "deprecated": True,
        "message": "接线触点请在学生本机 local_gateway.py 内测试"
    }), 410

@app.route('/api/test_wired_status', methods=['GET'])
def test_wired_status():
    """旧版测试接口：不再通过服务端全局变量模拟接线状态。"""
    return jsonify({
        "success": False,
        "deprecated": True,
        "message": "wired_status 请在学生本机 local_gateway.py 内测试"
    }), 410


if __name__ == '__main__':
    # 启动模拟线程
    reset_contact_status()
    print("? 启动Web服务器...")
    print(f"? 请在浏览器中访问: http://{STUDENT_WEB_CONFIG['host']}:{STUDENT_WEB_CONFIG['port']}")
    print("=" * 50)

    # 启动Flask应用
    try:
        socketio.run(
            app,
            host=STUDENT_WEB_CONFIG["host"],
            port=STUDENT_WEB_CONFIG["port"],
            debug=False,
        )  # 关闭debug模式提高性能
    except Exception as e:
        print(f"? 启动失败: {e}")
        print(f"请检查端口{STUDENT_WEB_CONFIG['port']}是否被占用")
