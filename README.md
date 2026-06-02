# videoProject — 接线实训考试系统

> 项目名称为仓库目录名 `videoProject`，对外发布时可按需重命名（**待确认**）。

基于计算机视觉与硬件采集的电工 / 电路接线实训考试系统。系统分为「服务器端」和「学生本机客户端」两部分：服务器统一承载登录认证、教师端、学生端页面与后端接口；客户端部署在学生本机，负责摄像头 YOLO 检测、STM32 串口采集与本地实时接线评判，并通过本地网关 API 暴露给学生浏览器调用。

## 项目简介

- **服务器端（`Server/`）**：Flask 应用，提供账号登录 / 注册、人脸识别登录转发、教师端（规则管理、学生管理、注册审批、考试创建、成绩与知识点分析）、学生端（规则下载、AI 答疑、题目生成、成绩可视化、实时接线状态代理）等能力，数据存储于 MySQL。
- **学生本机客户端（`Client/`）**：`local_gateway.py` 本地网关，负责启动 / 停止 YOLO 检测、STM32 串口通信、读取接线状态与实时分数，并向学生浏览器提供本地 HTTP 接口。

> 学生浏览器访问由服务器统一下发的页面；接线检测相关请求由浏览器**直连本机网关**（默认 `http://127.0.0.1:6001`），人脸识别请求则上传到服务器再由服务器转发。

## 核心功能

### 服务器端
- 账号密码登录与注册：`POST /api/auth/login`、`POST /api/auth/register`，兼容旧接口 `POST /login`、`POST /register`
- 人脸识别登录：`POST /recognize_face`（基于 OpenCV LBPH 人脸库匹配，匹配后查库返回跳转地址）
- 用户信息查询：`GET|POST /api/auth/user-info`
- 健康检查：`GET /health`、`GET /api/auth/health`
- 教师端（挂载于 `/teacher`）：评判规则的增删改查 / 重命名 / 激活与下载、学生管理、注册审批、考试创建与查询、成绩汇总与分布、薄弱知识点统计，并通过 Flask-SocketIO 推送实时分数
- 学生端（挂载于 `/student`）：规则查看 / 激活 / 下载、AI 对话与题目生成（对接 Ollama）、成绩与知识点可视化、接线状态与实时分数查询
- 同时支持 HTTP 与 HTTPS（配置证书后以多进程方式同时监听）

### 客户端（本地网关）
- YOLO 检测启停：`POST /api/yolo/start`、`POST /api/yolo/stop`、`GET /api/yolo/status`
- STM32 串口通信：`POST /api/stm/start`、`POST /api/stm/stop`、`GET /api/stm/query`
- 接线状态 / 分数读取：`GET /api/get_air_switch_status`、`GET /api/get_score_and_contact`、`GET /api/get_current_score`、`GET /api/get_wiring_status`
- 规则同步：`POST /api/rules/pull`（从服务器拉取评判规则到本地）
- 上下文管理：`GET|POST /api/context`
- 结果上报（预留）：`POST /api/report/wiring_result`、`POST /api/report/exam_result`
- 健康检查与人脸识别转发：`GET /health`、`POST /recognize_face`

## 技术栈

- **语言 / 运行时**：Python 3（`__pycache__` 中含 3.10–3.13 字节码，推荐版本**待确认**）
- **Web 框架**：Flask 3.1.x、Flask-Cors、Flask-SocketIO（服务器端，搭配 eventlet）
- **数据库**：MySQL（`mysql-connector-python`），库名默认 `multivideo`
- **计算机视觉**：OpenCV（服务器端使用 `opencv-contrib-python-headless`；客户端使用 `opencv-python`）、Ultralytics YOLO（客户端）
- **硬件采集**：`pyserial`（STM32 串口）
- **数据处理**：NumPy、pandas、openpyxl
- **大模型**：Ollama（默认模型 `qwen2.5:1.5b`，用于 AI 答疑与题目生成）
- **其他**：requests、PyQt5（客户端可选本地工具 / 演示）

## 目录结构

```text
videoProject/
├── Server/                          # 服务器端（统一服务）
│   ├── app.py                       # 主入口，挂载 /teacher、/student 子应用
│   ├── db.py                        # MySQL 连接器
│   ├── global_config.py             # 服务器端全局配置
│   ├── config.env                   # 运行配置（含敏感信息，见下文安全提示）
│   ├── requirements.txt             # 服务器端依赖
│   ├── certs/                       # HTTPS 证书与私钥（敏感，见下文）
│   ├── tools/                       # config / 数据库 connector / 人脸识别服务
│   ├── teacher_webui/               # 教师端 Flask 子应用（app.py + templates）
│   ├── student_webui/               # 学生端 Flask 子应用（app.py + templates）
│   ├── templates/                   # 登录页 login.html
│   ├── static/                      # 前端静态资源（css/js/fonts）
│   ├── data/                        # 规则、标签、结果数据
│   ├── server_local_gateway_integration.md   # 服务端与客户端对接文档
│   └── Miniconda3-latest-Linux-x86_64.sh      # 随仓库附带的安装器（约 160MB）
│
└── Client/                          # 学生本机客户端
    ├── local_gateway.py             # 本地网关主入口（默认端口 6001）
    ├── global_config.py             # 客户端全局配置与分数管理
    ├── local_gateway_config.json    # 本地网关运行配置（含服务器地址）
    ├── local_gateway_config.example.json      # 配置示例
    ├── requirements.txt             # 客户端依赖
    ├── script/                      # 检测 / 评分 / 串口 / STM 结果处理脚本
    ├── tools/                       # config / connector / 区域选择等工具
    ├── weights/                     # YOLO 权重文件（*.pt）
    ├── data/                        # 规则、标签、结果数据
    ├── image/                       # 截图 / 实时帧 / 手部抓拍目录
    ├── get-pip.py                   # 随仓库附带的 pip 安装脚本
    └── server_local_gateway_integration.md
```

> 各子目录的进一步用途以 `Server/README.md`、`Client/README.md` 和 `server_local_gateway_integration.md` 为准。

## 安装与运行

> 以下命令会**安装依赖**、**联网下载包**，请在你确认的虚拟环境中执行。仓库中已附带 `Server/Miniconda3-latest-Linux-x86_64.sh` 与 `Client/get-pip.py`，是否使用由你决定（不建议直接随仓库分发，见安全提示）。

### 1. 服务器端

前置：可用的 MySQL 实例（默认库名 `multivideo`），数据库表结构（`student`、`teacher`、`register`、`users` 等）**待确认 / 需自行准备**。

```bash
cd Server
python -m venv .venv && source .venv/bin/activate   # 可选
pip install -r requirements.txt

# 根据实际环境修改 config.env（数据库、端口、Ollama、人脸库路径等）
python app.py
```

启动后默认监听 `0.0.0.0:7001`（HTTP）。若配置了 `SERVER_SSL_CERT` / `SERVER_SSL_KEY`，同时监听 HTTPS（默认 `7443`）。

访问路径：

```text
登录页:   http://<服务器IP>:7001/
学生端:   http://<服务器IP>:7001/student/
教师端:   http://<服务器IP>:7001/teacher/
健康检查: http://<服务器IP>:7001/health
```

### 2. 学生本机客户端

前置：连接好摄像头与 STM32 串口设备；`Client/weights/` 下需有对应的 YOLO 权重；学生本机需安装客户端依赖。

```bash
cd Client
pip install -r requirements.txt

# 修改 local_gateway_config.json，把 server_base 指向服务器地址
python local_gateway.py
```

默认监听 `127.0.0.1:6001`。学生页面由服务器统一提供，接线检测请求由浏览器直连本机网关。

## 配置说明

### 服务器端（`Server/config.env`）
运行配置统一从 `config.env` 读取（由 `tools/config.py` 加载）；同名**环境变量优先级更高**，可用 `SERVER_CONFIG_FILE=/path/to/config.env` 指定其它配置文件。主要项：

| 配置项 | 说明 |
| --- | --- |
| `SERVER_HOST` / `SERVER_PORT` / `SERVER_HTTPS_PORT` | 服务器监听地址与端口 |
| `SERVER_SSL_CERT` / `SERVER_SSL_KEY` | HTTPS 证书与私钥路径（需同时配置） |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` / `DB_AUTH_PLUGIN` | MySQL 连接信息 |
| `LOCAL_CLIENT_BASE` | 学生浏览器直连的本机接线检测网关地址 |
| `FACE_RECOGNITION_BASE` / `FACE_LIBRARY_DIR` / `FACE_MATCH_THRESHOLD` | 人脸识别服务地址、人脸库目录、匹配阈值 |
| `STUDENT_WEB_*` / `TEACHER_WEB_*` | 学生 / 教师子应用监听与密钥（含 `SECRET_KEY`） |
| `STUDENT_WEB_BASE` / `TEACHER_WEB_BASE` | 登录跳转基础地址（留空则用当前服务器主机） |
| `RULE_SERVER_IP` / `RULE_SERVER_PORT` | 规则服务地址 |
| `OLLAMA_CHAT_*` / `OLLAMA_QUESTION_*` / `FRONTEND_OLLAMA_*` | 后端及前端注入的 Ollama 地址 / 端口 / 模型 |

### 客户端（`Client/local_gateway_config.json`）
配置优先级：**环境变量 > `local_gateway_config.json` > 程序默认值**。可参考 `local_gateway_config.example.json`。主要项：

| 配置项 | 说明 |
| --- | --- |
| `server_base` | 服务器基础地址（如 `http://<服务器IP>:7001`） |
| `cors_origins` | 允许访问本地网关的浏览器来源，默认 `*` |
| `student_no` / `student_name` / `test_id` / `test_name` / `rule_filename` | 多学生 / 多考试上下文 |
| `local_rule_path` | 当前评判规则保存路径，默认 `./data/rules/current_rule.json` |
| `stm_port` / `stm_baud` / `stm_timeout` | STM32 串口配置（默认 `COM4` / `38400`） |

对应环境变量：`LOCAL_GATEWAY_CONFIG`、`AUTH_SERVICE_BASE`、`SERVER_BASE`、`CLIENT_HOST`、`CLIENT_PORT`、`LOCAL_GATEWAY_CORS_ORIGINS`、`STUDENT_NO`、`TEST_ID`、`TEST_NAME`、`RULE_FILENAME`、`LOCAL_RULE_PATH`、`STM_PORT`、`STM_BAUD`、`STM_TIMEOUT` 等。

> ⚠️ **安全提示**：`Server/config.env`、`Client/tools/config.py` 当前包含明文数据库口令，`Server/certs/` 内含 HTTPS 私钥。请勿将真实凭据与私钥提交到公开仓库，发布前应替换为示例值并通过环境变量注入（详见仓库维护者说明）。

## 常用命令

```bash
# 服务器端
cd Server && python app.py                 # 启动统一服务（HTTP，配置证书后含 HTTPS）

# 客户端
cd Client && python local_gateway.py       # 启动本地网关（默认 127.0.0.1:6001）

# 依赖安装
pip install -r Server/requirements.txt
pip install -r Client/requirements.txt
```

## 使用示例

学生端接线检测的浏览器调用约定（详见 `Client/README.md`）：

```http
# 1. 点击“开始接线检测”后先启动检测（请求体需带浏览器生成的 session_id）
POST http://127.0.0.1:6001/api/yolo/start
Content-Type: application/json

{ "session_id": "<browser-session-id>" }
```

仅当响应 `success=true` 后再启动轮询：

```text
GET /api/get_air_switch_status?session_id=...   # 每 2500ms
GET /api/get_current_score?session_id=...        # 每 5000ms
GET /api/get_score_and_contact?session_id=...    # 每 5000ms
```

点击「停止检测」并 `POST /api/yolo/stop` 成功后，页面需 `clearInterval` 清理全部轮询；页面关闭或刷新前同样需要清理。

人脸识别登录（服务器端）：

```http
POST http://<服务器IP>:7001/recognize_face
Content-Type: application/json

{ "image": "<base64 编码图片>" }
```

## 测试方式

仓库中**未发现独立的测试目录或测试框架配置**（如 `pytest`、CI 工作流）。现有可手动验证的入口：

- 服务器健康检查：`GET /health`（会实际连接数据库执行 `SELECT 1`）
- 学生端调试接口：如 `POST /api/test_score_update`、`GET|POST /api/test_set_contact`、`GET /api/test_wired_status`
- 客户端调试接口：`POST /api/test/wiring_event`、`GET|POST /api/test_wired_status`
- 客户端串口自测脚本：`Client/script/test_stm32.py`

> 自动化测试覆盖情况**待确认**。

## 部署说明

- 服务器端为自包含包，部署时拷贝整个 `Server/` 目录即可；客户端同理拷贝整个 `Client/` 目录到学生本机。
- 生产环境建议用 `gunicorn + nginx` 承载 `Server/app.py` 并开启 HTTPS（参见 `Server/README.md`）。注意当前入口含 Flask-SocketIO，使用 gunicorn 时需选择与之兼容的 worker（**待确认**）。
- 服务器与客户端的对接细节见 `Server/server_local_gateway_integration.md`。

## 贡献指南

仓库内**未提供** `CONTRIBUTING` 或 issue / PR 模板。如需贡献，建议遵循常规流程：fork → 新建分支 → 提交 PR，并在 PR 中说明变更动机与影响范围。具体规范**待确认**。

## License

仓库内**未发现** LICENSE 文件，授权方式**待确认**。在补充明确许可证之前，请勿默认本项目可自由使用或分发。
