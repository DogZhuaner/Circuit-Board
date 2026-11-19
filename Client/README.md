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
python -m pip install -r requirements.txt
python local_gateway.py
```

启动后先确认本地网关可访问：

```bash
curl http://127.0.0.1:6001/health
```

如果学生端点击“开始接线检测”时出现 `Connection refused`，说明浏览器访问不到
`127.0.0.1:6001`，通常是本地网关没有启动、启动后立即退出，或依赖/串口配置不正确。

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

## 接线过程记录与导出

通过现有 `POST /api/yolo/start` 开始检测时，网关自动创建独立的 `recording_id` 并在响应中返回。初次有效采集作为 `initial_state`，此后每次有效采集保存完整状态，并逐条记录新增 `add` 和撤线 `remove`。同一次采集发现多条变化时，将该批新增、撤线混合随机排序一次，再追加到已有序列末尾。读取、导出均使用已保存的顺序。

记录写入发生在采集处理阶段，页面关闭或停止轮询不会丢弃已经保存的事件。检测期间调用 `/api/stm/query` 也会保存有效采集结果。停止检测时，等待检测线程退出，再尝试采集最后状态并关闭硬件检测。最后采集失败或发生过存储异常时，会话标为 `interrupted`，已保存数据仍可读取。

本地数据库默认保存在 `Client/data/recordings/wiring_history.sqlite3`。可以通过 `WIRING_RECORDINGS_DB` 环境变量或本地配置 `recordings_db` 改变路径，相对路径按 `Client/` 目录解析。数据库文件夹已加入 Git 忽略规则。网关按单进程运行，每台实训机同时录制一个会话。重启后第一次打开记录库时，将未结束会话标为 `interrupted`，新一轮检测另建记录。

### 读取接口

| 方法与路径 | 返回内容 |
| --- | --- |
| `GET /api/recordings?limit=50&offset=0` | 按开始时间倒序的记录列表、当前录制 ID 和存储错误 |
| `GET /api/recordings/<recording_id>?after_seq=0&limit=500` | 元数据、初始与最新状态、事件增量、相关采集批次 |
| `GET /api/recordings/<recording_id>/export` | 完整 JSON 文件下载，录制中也能导出一致性快照 |
| `GET /api/yolo/status` | 当前 `recording_id` 和 `recording_error` |

`limit` 在列表接口中范围为 1–200，在事件读取接口中范围为 1–2000。`after_seq` 与 `offset` 为非负整数。未知记录返回 404，无效分页参数返回 400。

### 服务端动画与未来云同步的数据约定

导出结构包含 `schema_version=1`、`recording_id`、`metadata`、`initial_state`、`latest_state`、`events` 和 `batches`。元数据保存学生、考试、浏览器会话、规则副本与端子编号映射。端子显示坐标和画板布局由后续服务端播放器配置。

每条事件保存以下字段。

| 字段 | 含义 |
| --- | --- |
| `event_id` | `recording_id:seq`，供上传接收端去重 |
| `seq` | 会话内连续步骤序号，回放的排序依据 |
| `batch_id`、`index_in_batch` | 采集批次及保存时确定的批内顺序 |
| `timestamp` | 带 UTC 时区的记录时间 |
| `elapsed_ms` | 自本次录制开始的单调时钟毫秒数 |
| `operation` | `add` 或 `remove` |
| `terminals` | 归一化的两个端子名，忽略端子对方向 |
| `order_in_batch` | 多事件批为 `randomized`，单事件批为 `single` |

同批事件具有相同的采集时间，服务端动画可按 `seq` 逐步播放，并为每一步设置显示时长。批次保存该次有效采集后的完整端子对、事件数量和 `score_after_batch`。评分对应完整批次，播放器应在该批步骤执行完毕后更新分数。

从 `initial_state.pairs` 开始，按顺序应用 `add` 与 `remove` 即可重建接线状态。首次读取从 `after_seq=0` 开始，以后使用响应的 `next_after_seq` 继续查询，`has_more=true` 时继续取下一页。同一批事件可以跨页，消费者按 `seq` 累积处理。`latest_state` 表示读取时最新完整状态，可能晚于当前分页末尾。

后续上传可复用该结构，并在云端按 `recording_id` 与 `event_id` 去重。当前版本交付本地持久化、读取和导出接口，服务端播放器与云端上传将在后续接入。

记录反映 STM32 有效采集报告的接线对变化，`capture_semantics` 为 `stm32_reported_pairs`。同一批中的先后顺序为随机生成。两次采集之间发生且恢复原状的操作，仍受硬件采样能力限制。

### 验证

```bash
python -m unittest discover -s Client/tests -v
```

### 考试成绩提交

考试页面在确认提交时结束本次检测，从网关的已完成记录取得签名成绩凭据，再由服务端按学号和考试 ID 保存。最终硬件读取失败或记录中断时需要重新检测，练习无需设置密钥。

部署到其他学生机时，将该网关的环境变量 `EXAM_SCORE_KEY` 或 `Client/exam-score.key` 配置为与服务端 `Server/config.env` 中 `EXAM_SCORE_KEY` 相同的密钥。密钥文件通过私下部署分发。更新后重启服务端和网关。
