# 客户端（本地）代码说明

该目录用于部署到学生本机，负责接线检测相关的本地硬件和实时能力：

- YOLO检测启动/停止：`/api/yolo/start`、`/api/yolo/stop`
- STM32 串口通信：`/api/stm/start`、`/api/stm/stop`、`/api/stm/query`
- 接线状态读取：`/api/get_air_switch_status`、`/api/get_score_and_contact`、`/api/get_current_score`
- 结果上报预留：`/api/report/wiring_result`、`/api/report/exam_result`
- 客户端内已包含运行依赖目录：`script/`、`tools/`、`weights/`、`data/`、`image/`、`global_config.py`

人脸识别不走本地网关。学生浏览器应把照片上传到服务端 `/recognize_face`，由服务端转发到 `FACE_RECOGNITION_BASE`。

## 启动顺序

1. 启动本地网关（YOLO/STM/接线状态）：

```bash
python local_gateway.py
```

2. 学生端页面由服务器统一提供（访问 `server/app.py` 的 `/student/`）。

## 本地配置文件

默认读取同目录下的 `local_gateway_config.json`。部署到学生电脑后，优先修改这里的服务端地址：

```json
{
  "server_base": "http://服务器IP:7001",
  "cors_origins": "*",
  "student_no": "",
  "test_id": "",
  "test_name": "",
  "rule_filename": "",
  "local_rule_path": "./data/rules/current_rule.json",
  "stm_port": "COM4",
  "stm_baud": 38400,
  "stm_timeout": 3
}
```

配置优先级：环境变量 > `local_gateway_config.json` > 程序默认值。

## 关键环境变量

- `LOCAL_GATEWAY_CONFIG`：指定配置文件路径，默认 `local_gateway_config.json`
- `AUTH_SERVICE_BASE`：服务器认证地址，默认 `http://127.0.0.1:7001`
- `SERVER_BASE`：服务端基础地址，默认沿用 `AUTH_SERVICE_BASE` 或 `http://127.0.0.1:7001`
- `CLIENT_HOST`、`CLIENT_PORT`：本地网关监听地址，默认 `127.0.0.1:6001`
- `LOCAL_GATEWAY_CORS_ORIGINS`：允许访问本地网关的浏览器来源，默认 `*`
- `STUDENT_NO`、`TEST_ID`、`TEST_NAME`、`RULE_FILENAME`：多学生/多考试上下文，可由环境变量或 `/api/yolo/start` 请求体传入
- `LOCAL_RULE_PATH`：当前评判规则保存路径，默认 `data/rules/current_rule.json`
- `STM_PORT`、`STM_BAUD`、`STM_TIMEOUT`：串口配置

规则同步时，服务端学生页面通常不需要传 `save_path`；本地网关默认保存到相对路径 `./data/rules/current_rule.json`。如果确实要传 `save_path`，优先使用相对路径，不要硬编码 `C:\VideoClient\...` 这类绝对路径。

## 学生页面轮询约定

学生页面不要在加载后立即轮询本地网关。点击“开始接线检测”后，先调用：

```http
POST http://127.0.0.1:6001/api/yolo/start
```

请求体必须带浏览器生成的 `session_id`。只有响应 `success=true` 后才启动轮询：

```text
GET /api/get_air_switch_status?session_id=...
GET /api/get_current_score?session_id=...
GET /api/get_score_and_contact?session_id=...
```

轮询频率：

- 空气开关状态：`/api/get_air_switch_status`，每 `2500ms` 一次。
- 实时分数：`/api/get_current_score`，建议随接线查询每 `5000ms` 一次。
- 接线事件：`/api/get_score_and_contact`，每 `5000ms` 一次。

点击“停止检测”并且 `POST /api/yolo/stop` 成功后，页面必须 `clearInterval` 清理全部轮询。页面关闭或刷新前也应清理轮询。

## 注意

该目录现在是自包含客户端包，部署时只需拷贝 `client/` 整个目录。
