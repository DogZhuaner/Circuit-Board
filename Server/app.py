import json
import multiprocessing
from pathlib import Path
from datetime import datetime
from urllib.parse import quote
from urllib import request as urllib_request, error as urllib_error

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import run_simple

from db import MySQLConnector
from teacher_webui.app import app as teacher_app
from student_webui.app import app as student_app
from tools.config import (
    FACE_LIBRARY_DIR,
    FACE_MATCH_THRESHOLD,
    LOCAL_CLIENT_BASE,
    SERVER_CONFIG,
    get_student_web_base,
    get_teacher_web_base,
)
from tools.face_recognition_service import FaceRecognitionError, recognize_face_image


app = Flask(__name__, template_folder="templates")
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


@app.route("/", methods=["GET"])
def login_page():
    host_url = request.host_url.rstrip("/")
    return render_template(
        "login.html",
        local_client_base=LOCAL_CLIENT_BASE,
        student_web_base=get_student_web_base(host_url),
        teacher_web_base=get_teacher_web_base(host_url),
    )


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

    user = result.get("user", {})
    role = user.get("role")
    user_id = quote(str(user.get("id", "")))
    user_name = quote(str(user.get("name", "")))
    host_url = request.host_url.rstrip("/")

    if role == "teacher":
        redirect = f"{get_teacher_web_base(host_url)}/?teacher_id={user_id}&teacher_name={user_name}"
    else:
        redirect = f"{get_student_web_base(host_url)}/?student_id={user_id}&student_name={user_name}"

    return jsonify({"success": True, "message": result.get("message"), "redirect": redirect})


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

    host_url = request.host_url.rstrip("/")
    if user["role"] == "teacher":
        redirect = f"{get_teacher_web_base(host_url)}/?teacher_id={quote(user['id'])}&teacher_name={quote(str(user['name']))}"
    else:
        redirect = f"{get_student_web_base(host_url)}/?student_id={quote(user['id'])}&student_name={quote(str(user['name']))}"

    return jsonify({
        "success": True,
        "message": "识别成功",
        "emp_id": user["id"],
        "role": user["role"],
        "name": user["name"],
        "redirect": redirect,
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
