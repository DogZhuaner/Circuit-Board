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

运行配置统一从根目录 `config.env` 读取，由 `tools/config.py` 加载，包括服务器监听地址、数据库地址/账号/密码、学生端本地检测地址、服务器侧人脸识别地址、规则服务地址、OpenAI 兼容模型接口默认地址和子 WebUI 配置。

同名环境变量优先级高于 `config.env`，可用于临时覆盖。也可以通过 `SERVER_CONFIG_FILE=/path/to/config.env` 指定其他配置文件。

- `SERVER_HOST`、`SERVER_PORT`
- `STUDENT_WEB_HOST`、`STUDENT_WEB_PORT`、`STUDENT_WEB_SECRET_KEY`
- `TEACHER_WEB_HOST`、`TEACHER_WEB_PORT`、`TEACHER_WEB_SECRET_KEY`
- `DB_HOST`、`DB_PORT`、`DB_USER`、`DB_PASSWORD`、`DB_NAME`、`DB_AUTH_PLUGIN`
- `LOCAL_CLIENT_BASE`：学生浏览器直连的本地接线检测服务地址
- `FACE_RECOGNITION_BASE`：服务器调用的人脸识别服务地址
- `RULE_SERVER_IP`、`RULE_SERVER_PORT`
- `MODEL_API_BASE_URL`、`MODEL_CHAT_NAME`、`MODEL_QUESTION_NAME` 为练习端的默认接口地址、对话模型和出题模型。练习页只需输入 vLLM 服务的 IP 与端口，系统自动使用 HTTP 和标准 `/v1` 路径。学生保存的设置优先，按学号存放在 `Server/data/model_settings/`。该目录包含私有凭据，部署迁移时请保留目录权限。
- `STUDENT_WEB_BASE`、`TEACHER_WEB_BASE`

## 部署建议

该目录现在是自包含服务器包，部署时只需拷贝 `server/` 整个目录。
生产环境建议用 `gunicorn + nginx` 承载 `server/app.py`，并开启 HTTPS。

## 考试接线回顾

已有 MySQL 库执行 `migrations/001_exam_recording.sql` 后再更新服务。新导入的 `video_project.sql` 已包含这张表。服务器和网关沿用相同的 `EXAM_SCORE_KEY` 配置。服务器运行账户需有归档目录的读写权限。默认目录为 `Server/data/recordings/`，可用 `WIRING_ARCHIVE_DIR` 指向持久化数据盘。备份时同时保存 MySQL 和归档目录。

学生交卷时，网页从本机取得完整 JSON 和网关签名，一并提交到原有成绩接口。服务器核验学号、考试、分数和文件摘要，将文件原子写入归档目录的 `<摘要前两位>/<SHA256>.json`，再在同一个 MySQL 事务中写入成绩和记录索引。重试沿用现有首份成绩。成绩详情按成绩行主键关联归档，历史成绩没有归档时显示“暂无记录”。

考试开始接线后，关闭或刷新考试页会触发浏览器的离开确认。学生确认离开时，网页通知本机网关停止检测、取最终读数并提交成绩和接线记录。网页意外消失时，网关在页面连接断开 45 秒后接手交卷。待提交任务保存在学生机接线记录的 SQLite 库中，网络暂时中断时会重试。学生机的 `server_base`（或环境变量 `SERVER_BASE`）应指向本次考试的服务器地址，服务器仍按原有截止时间接收成绩。

查询某位考生在某次考试的成绩和记录可使用下列参数化查询。

```sql
SELECT r.id, r.student_no, r.test_id, r.test_score, w.recording_id, w.sha256
FROM exam_result AS r
LEFT JOIN exam_recording AS w ON w.result_id = r.id
WHERE r.student_no = %s AND r.test_id = %s;
```

已有数据库请执行一次 `migrations/002_teaching.sql` 以启用教师发布考试和班级管理。新导入的数据库已包含该结构。考试按数据库本地时间开放，发布时保存规则文件副本；同步更新学生机的 `Client/local_gateway.py`，以便按考试规则检测和计分。

已有库在上述迁移后执行一次 `migrations/003_exam_classes.sql`。新考试须指定至少一个教师名下的班级，学生按当前班级成员关系及开放时间选考。迁移前发布的考试沿用原开放范围。

已有库随后执行一次 `migrations/004_require_exam_rules.sql`。新发布的考试必须指定接线规则文件，并保存至少一条有效规则。已有的无规则考试保留原始数据。
