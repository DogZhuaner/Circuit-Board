import os
from pathlib import Path
from urllib.parse import urlsplit


CONFIG_FILE = Path(os.getenv("SERVER_CONFIG_FILE", Path(__file__).resolve().parents[1] / "config.env"))


def _load_config_file(path):
    values = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value

    return values


FILE_CONFIG = _load_config_file(CONFIG_FILE)


def _env(name, default):
    return os.getenv(name, FILE_CONFIG.get(name, default))


def _env_int(name, default):
    value = _env(name, default)
    if value in (None, ""):
        return default
    return int(value)


def _env_float(name, default):
    value = _env(name, default)
    if value in (None, ""):
        return default
    return float(value)


SERVER_CONFIG = {
    "host": _env("SERVER_HOST", "0.0.0.0"),
    "port": _env_int("SERVER_PORT", 7001),
    "https_port": _env_int("SERVER_HTTPS_PORT", 7443),
    "ssl_cert": _env("SERVER_SSL_CERT", ""),
    "ssl_key": _env("SERVER_SSL_KEY", ""),
}

STUDENT_WEB_CONFIG = {
    "host": _env("STUDENT_WEB_HOST", "127.0.0.1"),
    "port": _env_int("STUDENT_WEB_PORT", 8088),
    "secret_key": _env("STUDENT_WEB_SECRET_KEY", "your-secret-key-here"),
}

TEACHER_WEB_CONFIG = {
    "host": _env("TEACHER_WEB_HOST", "127.0.0.1"),
    "port": _env_int("TEACHER_WEB_PORT", 8090),
    "secret_key": _env("TEACHER_WEB_SECRET_KEY", "teacher-secret-key-here"),
}

DB_CONFIG = {
    "host": _env("DB_HOST", "192.168.1.120"),
    "port": _env_int("DB_PORT", 3306),
    "user": _env("DB_USER", "admin"),
    "password": _env("DB_PASSWORD", "a214a214"),
    "database": _env("DB_NAME", "multivideo"),
    "auth_plugin": _env("DB_AUTH_PLUGIN", "mysql_native_password"),
}

EXAM_SCORE_KEY = _env("EXAM_SCORE_KEY", "")

LOCAL_CLIENT_BASE = _env("LOCAL_CLIENT_BASE", "http://127.0.0.1:6001").rstrip("/")
FACE_RECOGNITION_BASE = _env("FACE_RECOGNITION_BASE", "http://127.0.0.1:6001").rstrip("/")
FACE_LIBRARY_DIR = _env("FACE_LIBRARY_DIR", "/home/server/faces")
FACE_MATCH_THRESHOLD = _env_float("FACE_MATCH_THRESHOLD", 85.0)

RULE_SERVER_CONFIG = {
    "ip": _env("RULE_SERVER_IP", "127.0.0.1"),
    "port": _env_int("RULE_SERVER_PORT", 8000),
}

PRACTICE_MODEL_DEFAULTS = {
    "base_url": _env("MODEL_API_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/"),
    "chat": _env("MODEL_CHAT_NAME", ""),
    "question": _env("MODEL_QUESTION_NAME", ""),
}

TEACHER_MODEL = {
    "base_url": _env("TEACHER_MODEL_API_BASE_URL", PRACTICE_MODEL_DEFAULTS["base_url"]).rstrip("/"),
    "chat": _env("TEACHER_MODEL_CHAT_NAME", PRACTICE_MODEL_DEFAULTS["chat"]),
    "api_key": _env("TEACHER_MODEL_API_KEY", ""),
}


def get_student_web_base(host_url):
    return _env("STUDENT_WEB_BASE", f"{host_url.rstrip('/')}/student").rstrip("/")


def get_teacher_web_base(host_url):
    return _env("TEACHER_WEB_BASE", f"{host_url.rstrip('/')}/teacher").rstrip("/")


def portal_login_url(host_url, script_root):
    if script_root:
        return '/'
    host = urlsplit(host_url)
    hostname = host.hostname
    if ':' in hostname:
        hostname = f'[{hostname}]'
    port = SERVER_CONFIG['https_port' if host.scheme == 'https' else 'port']
    return f'{host.scheme}://{hostname}:{port}/'
