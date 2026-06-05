import os
from pathlib import Path


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
    "host": _env("DB_HOST", "192.168.1.130"),
    "port": _env_int("DB_PORT", 3306),
    "user": _env("DB_USER", "admin"),
    "password": _env("DB_PASSWORD", "a214a214"),
    "database": _env("DB_NAME", "multivideo"),
    "auth_plugin": _env("DB_AUTH_PLUGIN", "mysql_native_password"),
}

LOCAL_CLIENT_BASE = _env("LOCAL_CLIENT_BASE", "http://127.0.0.1:6001").rstrip("/")
FACE_RECOGNITION_BASE = _env("FACE_RECOGNITION_BASE", "http://127.0.0.1:6001").rstrip("/")
FACE_LIBRARY_DIR = _env("FACE_LIBRARY_DIR", "/home/server/faces")
FACE_MATCH_THRESHOLD = _env_float("FACE_MATCH_THRESHOLD", 85.0)

RULE_SERVER_CONFIG = {
    "ip": _env("RULE_SERVER_IP", "127.0.0.1"),
    "port": _env_int("RULE_SERVER_PORT", 8000),
}

OLLAMA_CHAT_DEFAULTS = {
    "host": _env("OLLAMA_CHAT_HOST", "192.168.1.130"),
    "port": _env_int("OLLAMA_CHAT_PORT", 11434),
    "model": _env("OLLAMA_CHAT_MODEL", "qwen2.5:1.5b"),
}

OLLAMA_QUESTION_DEFAULTS = {
    "host": _env("OLLAMA_QUESTION_HOST", "127.0.0.1"),
    "port": _env_int("OLLAMA_QUESTION_PORT", 11434),
    "model": _env("OLLAMA_QUESTION_MODEL", "qwen2.5:1.5b"),
}

FRONTEND_OLLAMA_DEFAULTS = {
    "host": _env("FRONTEND_OLLAMA_HOST", "localhost"),
    "port": str(_env_int("FRONTEND_OLLAMA_PORT", 11434)),
    "model": _env("FRONTEND_OLLAMA_MODEL", "qwen2.5:1.5b"),
}


def get_student_web_base(host_url):
    return _env("STUDENT_WEB_BASE", f"{host_url.rstrip('/')}/student").rstrip("/")


def get_teacher_web_base(host_url):
    return _env("TEACHER_WEB_BASE", f"{host_url.rstrip('/')}/teacher").rstrip("/")
