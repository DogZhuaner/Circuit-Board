# 服务器端代码说明

该目录用于部署到服务器，统一承载登录/注册、教师端、学生端页面与后端接口：

- 登录页面（账号登录、注册、本地人脸入口）：`/`
- 兼容旧前端接口：`POST /login`、`POST /register`、`POST /recognize_face`
- 登录认证 API：`POST /api/auth/login`
- 注册 API：`POST /api/auth/register`
- 用户信息 API：`GET|POST /api/auth/user-info`
- 健康检查：`GET /health`
- 教师端页面：`/teacher/`
- 学生端页面：`/student/`
- 服务器内已包含依赖目录：`teacher_webui/`、`student_webui/`、`tools/`、`global_config.py`、`data/`、`static/`

## 启动

```bash
python server/app.py
```

- 统一服务监听地址从 `tools/config.py` 的 `SERVER_CONFIG` 读取

## 配置

运行配置统一从根目录 `config.env` 读取，由 `tools/config.py` 加载，包括服务器监听地址、数据库地址/账号/密码、学生端本地检测地址、服务器侧人脸识别地址、规则服务地址、Ollama 默认地址和子 WebUI 配置。

同名环境变量优先级高于 `config.env`，可用于临时覆盖。也可以通过 `SERVER_CONFIG_FILE=/path/to/config.env` 指定其他配置文件。

- `SERVER_HOST`、`SERVER_PORT`
- `STUDENT_WEB_HOST`、`STUDENT_WEB_PORT`、`STUDENT_WEB_SECRET_KEY`
- `TEACHER_WEB_HOST`、`TEACHER_WEB_PORT`、`TEACHER_WEB_SECRET_KEY`
- `DB_HOST`、`DB_PORT`、`DB_USER`、`DB_PASSWORD`、`DB_NAME`、`DB_AUTH_PLUGIN`
- `LOCAL_CLIENT_BASE`：学生浏览器直连的本地接线检测服务地址
- `FACE_RECOGNITION_BASE`：服务器调用的人脸识别服务地址
- `RULE_SERVER_IP`、`RULE_SERVER_PORT`
- `OLLAMA_CHAT_HOST`、`OLLAMA_CHAT_PORT`、`OLLAMA_CHAT_MODEL`
- `OLLAMA_QUESTION_HOST`、`OLLAMA_QUESTION_PORT`、`OLLAMA_QUESTION_MODEL`
- `FRONTEND_OLLAMA_HOST`、`FRONTEND_OLLAMA_PORT`、`FRONTEND_OLLAMA_MODEL`
- `STUDENT_WEB_BASE`、`TEACHER_WEB_BASE`

## 部署建议

该目录现在是自包含服务器包，部署时只需拷贝 `server/` 整个目录。
生产环境建议用 `gunicorn + nginx` 承载 `server/app.py`，并开启 HTTPS。
