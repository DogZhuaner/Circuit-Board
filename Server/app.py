import json
import multiprocessing
import secrets
from collections import Counter
from pathlib import Path
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode
from urllib import request as urllib_request, error as urllib_error

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from flask_cors import CORS
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import run_simple

from recording_archive import archive_path
from db import MySQLConnector
from exam_access import ExamEntryError, exam_ticket, exam_rule_ticket, check_install_receipt, open_exams, require_open_exam
from teacher_webui.app import app as teacher_app
from student_webui.app import app as student_app
from tools.config import (
    LOCAL_CLIENT_BASE,
    FACE_LIBRARY_DIR,
    FACE_MATCH_THRESHOLD,
    SERVER_CONFIG,
    STUDENT_WEB_CONFIG,
    get_student_web_base,
    get_teacher_web_base,
)
from tools.face_recognition_service import FaceRecognitionError, recognize_face_image


app = Flask(__name__, template_folder="templates")
app.config.update(SECRET_KEY=STUDENT_WEB_CONFIG["secret_key"], SESSION_COOKIE_NAME="circuit_entry")
CORS(app)


PROJECT_ROOT = Path(__file__).resolve().parent


def resolve_project_path(path_value):
    path_value = str(path_value or "").strip()
    if not path_value:
        return None

    path = Path(path_value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def get_ssl_context():
    cert_path = resolve_project_path(SERVER_CONFIG.get("ssl_cert"))
    key_path = resolve_project_path(SERVER_CONFIG.get("ssl_key"))
    if not cert_path and not key_path:
        return None
    if not cert_path or not key_path:
        raise RuntimeError("SERVER_SSL_CERT 和 SERVER_SSL_KEY 必须同时配置")
    if not cert_path.exists():
        raise RuntimeError(f"HTTPS 证书文件不存在: {cert_path}")
    if not key_path.exists():
        raise RuntimeError(f"HTTPS 私钥文件不存在: {key_path}")
    return str(cert_path), str(key_path)


def create_unified_app():
    return DispatcherMiddleware(
        app,
        {
            "/teacher": teacher_app,
            "/student": student_app,
        },
    )


def run_http_server():
    unified_app = create_unified_app()
    print(f"Starting HTTP server: http://{SERVER_CONFIG['host']}:{SERVER_CONFIG['port']}", flush=True)
    run_simple(
        SERVER_CONFIG["host"],
        SERVER_CONFIG["port"],
        unified_app,
        use_reloader=False,
        threaded=True,
    )


def run_https_server(ssl_context):
    unified_app = create_unified_app()
    print(f"Starting HTTPS server: https://{SERVER_CONFIG['host']}:{SERVER_CONFIG['https_port']}", flush=True)
    run_simple(
        SERVER_CONFIG["host"],
        SERVER_CONFIG["https_port"],
        unified_app,
        use_reloader=False,
        threaded=True,
        ssl_context=ssl_context,
    )


def get_payload():
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form.to_dict() or {}


def json_http_request(url, method="GET", payload=None, timeout=8):
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib_request.Request(url=url, data=body, headers=headers, method=method)
    try:
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.getcode()
    except urllib_error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    except Exception as exc:
        return 500, {"success": False, "message": str(exc)}

    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {"success": False, "message": raw}
    return status, data


def perform_login(username, password, identity):
    username = str(username or "").strip()
    password = str(password or "").strip()
    identity = str(identity or "").strip().lower()

    if not username or not password or identity not in {"student", "teacher"}:
        return 400, {"success": False, "message": "参数不完整或身份类型错误"}

    connector = MySQLConnector()
    try:
        if identity == "student":
            sql = "SELECT sno, student_password, name FROM student WHERE sno = %s LIMIT 1"
        else:
            sql = "SELECT tno, teacher_password, name FROM teacher WHERE tno = %s LIMIT 1"

        rows = connector.query(sql, (username,))
        if not rows:
            return 404, {"success": False, "message": "账号不存在"}

        uid, db_password, name = rows[0]
        if str(db_password) != password:
            return 401, {"success": False, "message": "账号或密码错误"}

        return 200, {
            "success": True,
            "message": "登录成功",
            "user": {"id": str(uid), "role": identity, "name": name},
        }
    except Exception as exc:
        return 500, {"success": False, "message": f"登录失败: {exc}"}
    finally:
        connector.close()


def perform_register(user_id, user_name, user_password, user_type, user_approve):
    user_id = str(user_id or "").strip()
    user_name = str(user_name or "").strip()
    user_password = str(user_password or "").strip()
    user_type = str(user_type or "").strip().lower()
    user_approve = str(user_approve or "").strip()

    if not all([user_id, user_name, user_password, user_type, user_approve]):
        return 400, {"success": False, "message": "请填写所有必填字段"}
    if user_type not in {"student", "teacher"}:
        return 400, {"success": False, "message": "注册身份类型错误"}

    connector = MySQLConnector()
    try:
        approver = connector.query("SELECT tno FROM teacher WHERE tno = %s LIMIT 1", (user_approve,))
        if not approver:
            return 400, {"success": False, "message": "审批者工号不存在或不是有效教师账号"}

        exists = connector.query("SELECT user_id FROM register WHERE user_id = %s LIMIT 1", (user_id,))
        if exists:
            return 409, {"success": False, "message": "用户已存在，请勿重复注册"}

        sql = (
            "INSERT INTO register (user_id, user_name, user_password, user_type, user_approve) "
            "VALUES (%s, %s, %s, %s, %s)"
        )
        connector.execute(sql, (user_id, user_name, user_password, user_type, user_approve))
        return 200, {"success": True, "message": "注册成功，请等待教师审核"}
    except Exception as exc:
        return 500, {"success": False, "message": f"注册失败: {exc}"}
    finally:
        connector.close()


def find_user_identity(user_no):
    user_no = str(user_no or "").strip()
    if not user_no:
        return None

    connector = MySQLConnector()
    try:
        rows = connector.query("SELECT sno, name FROM student WHERE sno = %s LIMIT 1", (user_no,))
        if rows:
            uid, name = rows[0]
            return {"id": str(uid), "role": "student", "name": name}

        rows = connector.query("SELECT tno, name FROM teacher WHERE tno = %s LIMIT 1", (user_no,))
        if rows:
            uid, name = rows[0]
            return {"id": str(uid), "role": "teacher", "name": name}

        return None
    finally:
        connector.close()


def login_destination(user: dict) -> str:
    session.clear()
    session["portal_root"] = request.url_root.rstrip("/")
    if user["role"] == "teacher":
        session["teacher_id"] = user["id"]
        session["teacher_name"] = user["name"]
        return f"{get_teacher_web_base(request.host_url)}/"

    session["student"] = {"id": user["id"], "name": user["name"]}
    return url_for("student_entry")


@app.errorhandler(ExamEntryError)
def exam_login_error(error):
    return jsonify(success=False, message=str(error)), error.status


@app.get("/api/exams/open")
def available_exams():
    if "student" not in session:
        return jsonify(success=False, message="请先登录学生账号"), 401
    return jsonify(exams=open_exams(session["student"]["id"])), 200, {"Cache-Control": "no-store"}


@app.route("/", methods=["GET"])
def login_page():
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    response = redirect(url_for("login_page"), code=303)
    response.cache_control.no_store = True
    return response


@app.get("/entry")
def student_entry():
    student = session.get("student")
    if not student:
        return redirect(url_for("login_page"))

    mode = request.args.get("mode")
    student_base = get_student_web_base(request.host_url)
    if mode == "practice":
        return redirect(f"{student_base}/")

    notice = "请选择考试并下载本场规则" if mode == "exam" else ""
    return render_template("entry.html", student=student, notice=notice,
                           local_client_base=LOCAL_CLIENT_BASE), 200, {"Cache-Control": "no-store"}


@app.post("/api/exams/<int:exam_id>/prepare")
def prepare_exam_entry(exam_id):
    student = session.get("student")
    if not student:
        return jsonify(success=False, message="请先登录学生账号"), 401
    session.pop("exam_entry_ticket", None)
    session.pop("exam_prepare", None)
    challenge = secrets.token_urlsafe(24)
    bundle = exam_rule_ticket(exam_id, student["id"], challenge=challenge)
    session["exam_prepare"] = {"exam": str(exam_id), "student": str(student["id"]), "challenge": challenge}
    return jsonify(success=True, rule_ticket=bundle, student_no=student["id"]), 200, {"Cache-Control": "no-store"}


@app.post("/api/exams/<int:exam_id>/enter")
def enter_prepared_exam(exam_id):
    student = session.get("student")
    if not student:
        return jsonify(success=False, message="请先登录学生账号"), 401
    expected = session.get("exam_prepare")
    if not expected or expected["exam"] != str(exam_id) or expected["student"] != str(student["id"]):
        raise ExamEntryError("请先下载所选考试的规则", 409)
    check_install_receipt((request.get_json(silent=True) or {}).get("receipt"), expected)
    require_open_exam(exam_id, student["id"])
    ticket = exam_ticket.dumps([exam_id, student["id"], student["name"]])
    session["exam_entry_ticket"] = ticket
    session.pop("exam_prepare")
    base = get_student_web_base(request.host_url)
    return jsonify(success=True, url=f"{base}/exam?{urlencode({'ticket': ticket})}"), 200, {"Cache-Control": "no-store"}


def score_view_student(sno):
    if sno is None:
        return session.get("student")
    if not session.get("teacher_id"):
        abort(403)
    connector = MySQLConnector()
    try:
        students = connector.query("SELECT sno,name FROM student WHERE sno=%s", (sno,))
    except RuntimeError:
        abort(503)
    finally:
        connector.close()
    if not students:
        abort(404)
    number, name = students[0]
    return {"id": str(number), "name": name}


@app.get("/staff/students/<int:sno>/scores")
@app.get("/scores")
def student_scores(sno=None):
    student = score_view_student(sno)
    if not student:
        return redirect(url_for("login_page"))
    back_url = (get_teacher_web_base(request.host_url).rstrip("/") + "/?panel=students"
                if sno is not None else url_for("student_entry"))
    navigation = dict(back_url=back_url, back_label="返回学生名册" if sno is not None else "返回选择页")
    connector = MySQLConnector()
    try:
        rows = connector.query(
            "SELECT r.id, r.test_id, r.test_name, r.test_score, r.knowledge, w.result_id "
            "FROM exam_result r LEFT JOIN exam_recording w ON w.result_id=r.id "
            "WHERE r.student_no=%s AND r.test_score IS NOT NULL ORDER BY r.created_at,r.id",
            (student["id"],),
        )
    except RuntimeError:
        app.logger.exception("读取学生成绩失败")
        return render_template("scores.html", error="暂时无法读取成绩，请稍后重试。", **navigation), 503, {"Cache-Control": "no-store"}
    finally:
        connector.close()

    scores = []
    counts = Counter()
    for row_id, exam_id, name, score, knowledge, review_id in rows:
        scores.append({"id": row_id, "test_id": exam_id, "test_name": name, "score": float(score),
                       "review_url": url_for("score_review", result_id=row_id, sno=sno) if review_id else None})
        points = (knowledge or "").replace("，", ",").split(",")
        counts.update(point.strip() for point in points if point.strip())
    return render_template(
        "scores.html", student=student, scores=scores, **navigation,
        knowledge=[{"name": name, "count": count} for name, count in counts.most_common()],
        exam_count=len({row["test_id"] for row in scores}),
        average=round(sum(row["score"] for row in scores) / len(scores), 2) if scores else "—",
    ), 200, {"Cache-Control": "no-store"}


@app.get("/staff/students/<int:sno>/scores/<int:result_id>/review")
@app.get("/scores/<int:result_id>/review")
def score_review(result_id, sno=None):
    student = score_view_student(sno)
    if not student:
        return redirect(url_for("login_page"))
    db = MySQLConnector()
    try:
        rows = db.query(
            "SELECT r.test_name,w.sha256,r.test_id,e.rule_snapshot FROM exam_result r "
            "JOIN exam_recording w ON w.result_id=r.id "
            "LEFT JOIN exam_test e ON BINARY r.test_id=BINARY CAST(e.id AS CHAR) "
            "WHERE r.id=%s AND r.student_no=%s", (result_id, student["id"]))
    except RuntimeError:
        abort(503)
    finally:
        db.close()
    if not rows:
        abort(404)
    return render_wiring_review(*rows[0], scores_url=url_for("student_scores", sno=sno))


@app.get("/staff/exams/<int:exam_id>/scores/<int:result_id>/review")
def exam_score_review(exam_id: int, result_id: int):
    if not session.get("teacher_id"):
        abort(403)
    db = MySQLConnector()
    try:
        rows = db.query(
            "SELECT e.test_name,w.sha256,r.test_id,e.rule_snapshot FROM exam_test e "
            "JOIN exam_result r ON r.test_id=%s "
            "JOIN exam_recording w ON w.result_id=r.id "
            "WHERE e.id=%s AND e.issuer_tno=%s AND e.deadline_time<=NOW() "
            "AND r.id=%s AND r.test_score IS NOT NULL", (str(exam_id), exam_id, session["teacher_id"], result_id))
    except RuntimeError:
        abort(503)
    finally:
        db.close()
    if not rows:
        abort(404)
    return render_wiring_review(*rows[0])


def review_correct_pairs(record: dict, rules):
    if isinstance(rules, dict):
        rules = rules.get("data") if isinstance(rules.get("data"), list) else rules.get("items")
    if not isinstance(rules, list):
        return None

    # The scorer ignores terminal order and surrounding whitespace, including for zero-point rules.
    def pair_key(pair):
        return tuple(sorted(str(node).strip() for node in pair))

    answers = {pair_key(rule["nodes"]) for rule in rules if isinstance(rule, dict)
               and isinstance(rule.get("nodes"), list) and len(rule["nodes"]) == 2}
    # Send only matches that actually appear in this recording.
    observed = {tuple(pair) for pair in record["initial_state"]["pairs"]}
    observed.update(tuple(event["terminals"]) for event in record["events"])
    return sorted(pair for pair in observed if pair_key(pair) in answers)


def render_wiring_review(name: str, digest: str, exam_id: str, snapshot: Optional[str], scores_url: Optional[str] = None):
    try:
        record = json.loads(archive_path(digest).read_bytes())
        captured_rules = record["metadata"].pop("rule_snapshot", None)
        rules = None
        if snapshot is not None:
            rules = json.loads(snapshot)
        elif str(record["metadata"].get("test_id")) == str(exam_id):
            rules = captured_rules
        correct_pairs = review_correct_pairs(record, rules)
    except (OSError, ValueError):
        app.logger.exception("读取接线归档 %s 失败", digest)
        return "暂时无法读取接线记录，请稍后重试。", 503, {"Cache-Control": "no-store"}
    return render_template("review.html", name=name, record=record, correct_pairs=correct_pairs,
                           scores_url=scores_url), 200, {"Cache-Control": "no-store"}


@app.route("/health", methods=["GET"])
def health():
    connector = MySQLConnector()
    try:
        connector.query("SELECT 1")
        return jsonify(
            {
                "success": True,
                "service": "server",
                "message": "ok",
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500
    finally:
        connector.close()


@app.route("/api/auth/health", methods=["GET"])
def auth_health():
    return health()


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = get_payload()
    status, result = perform_login(
        data.get("username"),
        data.get("password"),
        data.get("identity"),
    )
    if result.get("success"):
        result["redirect"] = login_destination(result["user"])
    return jsonify(result), status


@app.route("/api/auth/register", methods=["POST"])
def auth_register():
    data = get_payload()
    status, result = perform_register(
        data.get("user_id"),
        data.get("user_name"),
        data.get("user_password"),
        data.get("user_type"),
        data.get("user_approve"),
    )
    return jsonify(result), status


@app.route("/login", methods=["POST"])
def legacy_login():
    data = get_payload()
    status, result = perform_login(
        data.get("username"),
        data.get("password"),
        data.get("identity"),
    )
    if not result.get("success"):
        return jsonify(result), status

    return jsonify(success=True, message=result["message"], redirect=login_destination(result["user"]))


@app.route("/register", methods=["POST"])
def legacy_register():
    data = get_payload()
    status, result = perform_register(
        data.get("user_id"),
        data.get("user_name"),
        data.get("user_password"),
        data.get("user_type"),
        data.get("user_approve"),
    )
    return jsonify(result), status


@app.route("/recognize_face", methods=["POST"])
def recognize_face():
    payload = request.get_json(silent=True) or {}
    if "image" not in payload:
        return jsonify({"success": False, "message": "缺少 image"}), 400

    try:
        match = recognize_face_image(payload.get("image"), FACE_LIBRARY_DIR, FACE_MATCH_THRESHOLD)
    except FaceRecognitionError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": f"人脸识别失败: {exc}"}), 500

    if not match.get("matched"):
        return jsonify({
            "success": False,
            "message": "未匹配到可信人脸",
            "matched_filename": match.get("filename"),
            "matched_user_no": match.get("user_no"),
            "distance": match.get("distance"),
            "similarity": match.get("similarity"),
            "threshold": match.get("threshold"),
        }), 401

    user = find_user_identity(match.get("user_no"))
    if not user:
        return jsonify({
            "success": False,
            "message": f"识别到人脸库编号 {match.get('user_no')}，但数据库中未找到对应学生/教师账号",
            "matched_filename": match.get("filename"),
            "matched_user_no": match.get("user_no"),
            "distance": match.get("distance"),
            "similarity": match.get("similarity"),
            "threshold": match.get("threshold"),
        }), 404

    return jsonify({
        "success": True,
        "message": "识别成功",
        "emp_id": user["id"],
        "role": user["role"],
        "name": user["name"],
        "redirect": login_destination(user),
        "matched_filename": match.get("filename"),
        "distance": match.get("distance"),
        "similarity": match.get("similarity"),
        "threshold": match.get("threshold"),
    })


@app.route("/api/auth/user-info", methods=["GET", "POST"])
def auth_user_info():
    user_no = (
        request.args.get("user_no")
        or (request.get_json(silent=True) or {}).get("user_no")
        or request.form.get("user_no")
    )
    user_no = str(user_no or "").strip()
    if not user_no:
        return jsonify({"success": False, "message": "缺少 user_no"}), 400

    connector = MySQLConnector()
    sql = """
    SELECT
        u.user_no,
        u.user_id,
        u.role,
        CASE
            WHEN u.role = 'student' THEN s.name
            WHEN u.role = 'teacher' THEN t.name
        END AS name
    FROM users u
    LEFT JOIN student s ON u.user_id = s.user_id AND u.role = 'student'
    LEFT JOIN teacher t ON u.user_id = t.user_id AND u.role = 'teacher'
    WHERE u.user_no = %s
    LIMIT 1
    """
    try:
        rows = connector.query(sql, (user_no,))
        if not rows:
            return jsonify({"success": False, "message": "未找到对应用户"}), 404

        user_no_val, uid, role, name = rows[0]
        return jsonify(
            {
                "success": True,
                "user": {
                    "user_no": str(user_no_val),
                    "id": str(uid),
                    "role": role,
                    "name": name,
                },
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "message": f"查询失败: {exc}"}), 500
    finally:
        connector.close()


if __name__ == "__main__":
    ssl_context = get_ssl_context()
    if ssl_context:
        http_process = multiprocessing.Process(target=run_http_server, name="server-http")
        https_process = multiprocessing.Process(target=run_https_server, args=(ssl_context,), name="server-https")
        processes = [http_process, https_process]
        for process in processes:
            process.start()

        try:
            for process in processes:
                process.join()
        except KeyboardInterrupt:
            print("Stopping HTTP/HTTPS servers...", flush=True)
            for process in processes:
                if process.is_alive():
                    process.terminate()
            for process in processes:
                process.join(timeout=5)
    else:
        run_http_server()
