# 服务端与本地客户端对接摘要

本文档基于当前 `/home/server/Server` 代码整理，用于服务端与本地客户端 `local_gateway.py` 对接。

## 1. 服务端启动信息

主要入口文件：

- `app.py`

启动命令：

```bash
cd /home/server/Server
python3 app.py
```

配置文件：

- `config.env`

当前关键配置：

```env
SERVER_HOST=0.0.0.0
SERVER_PORT=7001
DB_HOST=192.168.1.120
LOCAL_CLIENT_BASE=http://127.0.0.1:6001
FACE_RECOGNITION_BASE=http://127.0.0.1:6001
```

访问路径：

```text
登录页:   http://服务器IP:7001/
学生端:   http://服务器IP:7001/student/
教师端:   http://服务器IP:7001/teacher/
```

`app.py` 通过 `DispatcherMiddleware` 挂载子应用：

```text
/student -> student_webui/app.py
/teacher -> teacher_webui/app.py
```

## 2. 认证 / 登录 / 人脸识别接口

| Method | Path | 请求参数 | 响应字段 |
|---|---|---|---|
| GET | `/health` | 无 | `success`, `service`, `message`, `time` |
| GET | `/api/auth/health` | 无 | 同 `/health` |
| POST | `/api/auth/login` | JSON/Form: `username`, `password`, `identity=student|teacher` | 成功：`success`, `message`, `user:{id,role,name}`；失败：`success=false`, `message` |
| POST | `/api/auth/register` | JSON/Form: `user_id`, `user_name`, `user_password`, `user_type`, `user_approve` | `success`, `message` |
| POST | `/login` | Form: `username`, `password`, `identity` | 成功：`success`, `message`, `redirect` |
| POST | `/register` | Form: `user_id`, `user_name`, `user_password`, `user_type`, `user_approve` | `success`, `message` |
| POST | `/recognize_face` | JSON: `image`，base64/dataURL | 转发 `FACE_RECOGNITION_BASE/recognize_face` 的结果；页面期望：`success`, `message`, `emp_id`, `role`, `name` |
| GET/POST | `/api/auth/user-info` | GET query 或 JSON/Form: `user_no` | 成功：`success`, `user:{user_no,id,role,name}`；失败：`message` |

已实现：

```text
GET /api/auth/health
GET /api/auth/user-info?user_no=...
```

## 3. 学生端接口

统一服务下路径需要加 `/student` 前缀。

| Method | Path | 请求参数 | 响应字段 |
|---|---|---|---|
| GET | `/student/` | Query: `student_id`, `student_name` | 返回学生端 HTML |
| GET | `/student/api/student_info` | 无 | `student_id`, `student_name` |
| POST | `/student/api/start_detection` | 无 | 代理本地网关 `/api/yolo/start`，透传 `success`, `message` 等 |
| POST | `/student/api/stop_detection` | 无 | 代理本地网关 `/api/yolo/stop` |
| GET | `/student/api/get_detection_status` | 无 | 代理本地网关 `/api/yolo/status` |
| GET | `/student/api/rules` | 无 | `success`, `files:[{filename,rule_count,size,modified_time,is_current}]`, `total` |
| POST | `/student/api/rules/activate` | JSON: `filename` | `success`, `filename`, `download_url` |
| GET | `/student/api/rules/files/<filename>/download` | 文件名 | 所选练习规则 JSON |
| GET | `/student/api/get_air_switch_status` | 无 | `airSwitchClosed`, `errorWiringCount` |
| GET | `/student/api/get_score_and_contact` | 无 | `score`, `contact_A`, `contact_B`, `wired_status` |
| GET | `/student/api/get_wiring_status` | 无 | `success`, `airSwitchClosed`, `errorWiringCount`, `currentContacts`, `wiringResults`, `totalScore` |
| GET | `/student/api/get_current_score` | 无 | `success`, `score` |
| GET | `/student/api/student/exams` | 当前登录学生从内存取 | `success`, `exams:[{test_id,test_name}]` |
| GET | `/student/api/student/score` | 当前登录学生从内存取 | `success`, `scores:[{test_id,test_name,score}]` |
| GET | `/student/api/student/knowledge` | 当前登录学生从内存取 | `success`, `knowledge:[{name,count}]` |
| GET/POST | `/student/api/test_set_contact` | 无 | 测试用：`success`, `message`, `contact_A`, `contact_B`, `score` |
| GET | `/student/api/test_wired_status` | Query: `status`, `contact_a`, `contact_b`, `score` | 测试用：`score`, `contact_A`, `contact_B`, `wired_status` |
| POST | `/student/api/test_score_update` | 无 | 目前调用未定义 `match_subgraphs()`，不可用 |

学生端还有 OpenAI 兼容模型 与可视化接口：

```text
/student/api/ai_chat
/student/api/get_subjects
/student/api/get_topics
/student/api/generate_question
/student/api/generate_multiple_questions
/student/api/models/question
/student/api/models/discover
/student/api/models/settings
/student/api/get_score_summary
/student/api/get_score_distribution_plot
/student/api/get_knowledge_analysis_plot
/student/api/get_student_knowledge_heatmap
/student/api/get_score_knowledge_correlation
/student/api/get_top_students
/student/api/get_knowledge_analysis
/student/api/get_knowledge_list
```

这些接口和本地网关无直接关系。

## 4. 教师端接口

统一服务下路径需要加 `/teacher` 前缀。

| Method | Path | 请求参数 | 响应字段 |
|---|---|---|---|
| GET | `/teacher/` | Query: `teacher_id`, `teacher_name` | 返回教师端 HTML |
| GET | `/teacher/api/teacher_info` | 无 | `teacher_id`, `teacher_name` |
| GET | `/teacher/api/registration_requests` | 当前教师工号 | `success`, `requests:[{user_id,user_name,user_type,user_type_text,user_approve}]`, `total` |
| POST | `/teacher/api/approve_registration` | JSON: `user_id` | `success`, `message`；会写 `users` 和 `student/teacher`，删除 `register` |
| POST | `/teacher/api/reject_registration` | JSON: `user_id`, `reason` | `success`, `message` |
| GET | `/teacher/api/students` | Query: `sort_by=sno|name|class` | `students`, `total`，来源 `students.json` |
| POST | `/teacher/api/student` | JSON: `sno`, `name`, `class_name` | `success`, `message` |
| PUT | `/teacher/api/student/<id>` | JSON: `sno`, `name`, `class_name` | `success`, `message` |
| DELETE | `/teacher/api/student/<id>` | path id | `success`, `message` |
| POST | `/teacher/api/create_exam` | JSON: `test_name`, `exam_content`, `rule_filename`, `class_ids` (int[]), `publish_time`, `deadline_time` | `success`, `exam_id` |
| GET | `/teacher/api/get_exams` | 当前教师工号 | `success`, `exams:[{id,test_name,test_type,duration_minutes,publish_time,deadline_time,create_time,update_time,teacher_info}]`, `total`, `teacher_info` |
| GET | `/teacher/api/student_score/<sno>` | path `sno` | `sno`, `score`，内存演示数据 |
| GET | `/teacher/api/get_score_summary` | 无 | `success`, `summary:{average,highest,lowest,total}`，演示数据 |
| GET | `/teacher/api/get_students_scores` | 无 | `success`, `students:[{id,sno,name,exam_time,duration,score,weak_points}]`，演示数据 |
| GET | `/teacher/api/get_score_distribution` | 无 | `success`, `distribution:[{range,count}]`，固定数据 |
| GET | `/teacher/api/get_weak_knowledge_points` | 无 | `success`, `weak_points:[{point,errorRate}]`，固定数据 |

## 5. 规则 / 接线评分相关接口

| Method | Path | 请求参数 | 响应字段 |
|---|---|---|---|
| GET | `/teacher/api/rule_download_service` | 无 | `title`, `content:{file_path,server_ip,server_port,file_exists,file_size,status}`, `status` |
| POST | `/teacher/api/rules/save` | JSON: `filename`, `rules:[{nodes:[...],score}]` | `success`, `message`, `filename`, `path`, `rules_count` |
| GET | `/teacher/api/rules` | 无 | `success`, `files:[{filename,size,modified_time,rule_count,is_current}]`, `total` |
| GET | `/teacher/api/rules/<filename>` | path filename | `success`, `filename`, `rules`, `raw` |
| PUT | `/teacher/api/rules/<filename>` | JSON: `rules:[{nodes,score}]` | `success`, `message`, `filename`, `rules_count` |
| DELETE | `/teacher/api/rules/<filename>` | path filename | `success`, `message`, `filename` |
| POST | `/teacher/api/rules/<filename>/rename` | JSON: `new_filename` | `success`, `message`, `filename` |
| POST | `/teacher/api/rules/<filename>/activate` | path filename | `success`, `message`, `active_rule_path`, `rules_count` |
| POST | `/teacher/api/rule-server/start` | 无 | 目前模拟：`success`, `message`, `status=running` |
| POST | `/teacher/api/rule-server/stop` | 无 | 目前模拟：`success`, `message`, `status=stopped` |

学生端规则接口：

| Method | Path | 请求参数 | 响应字段 |
|---|---|---|---|
| GET | `/student/api/rules` | 无 | `success`, `files:[{filename,rule_count,size,modified_time,is_current}]`, `total` |
| POST | `/student/api/rules/activate` | JSON: `filename` | `success`, `filename`, `download_url` |
| GET | `/student/api/rules/files/<filename>/download` | 文件名 | 所选练习规则 JSON |

服务端的 `data/rules/` 保存命名规则文件。教师设置默认练习规则时，`.practice-default` 保存文件名。学生点击「设为当前」时，页面把所选文件的下载地址交给本机 `POST /api/rules/pull`。下载成功后，网关将规则保存到本机 `data/rules/current_rule.json`。

选考时，页面调用 `POST /api/exams/<id>/prepare` 获取本场考试的签名规则快照，再调用学生机的 `POST /api/exam/prepare`。网关写入同一份本地规则并返回签名回执。服务端在 `POST /api/exams/<id>/enter` 校验回执和参考资格后才允许进入考试。开始检测时，网关再次核对本机规则和考试、学号。

## 6. Socket.IO

教师端：

```text
path: /teacher/socket.io
```

服务端监听：

```text
student_connect {sno, student_name}
update_score {sno, score}
```

服务端发送：

```text
connection_established {teacher_id}
student_connected {sno, student_name, connected_at}
score_updated {sno, score}
```

学生端页面也初始化了 Socket.IO：

```text
path: /student/socket.io
```

学生端页面监听：

```text
wiring_result
wiring_results_update
```

但当前 `student_webui/app.py` 没有看到对应 `socketio.emit('wiring_result')` 或 `socketio.emit('wiring_results_update')`。

## 7. 学生端页面如何调用本地客户端网关

学生端页面路径：

```text
/student/
```

页面中注入：

```js
const DEFAULT_LOCAL_CLIENT_BASE = "http://127.0.0.1:6001";
const LOCAL_CLIENT_BASE =
  localStorage.getItem("local_client_base") || DEFAULT_LOCAL_CLIENT_BASE;
```

当前页面实际开始/停止检测调用的是服务端相对路径：

```js
fetch("api/start_detection", { method: "POST" })
fetch("api/stop_detection", { method: "POST" })
fetch("api/get_score_and_contact")
fetch("api/get_current_score")
```

服务端 `/student/api/start_detection` 再代理到：

```text
LOCAL_CLIENT_BASE/api/yolo/start
LOCAL_CLIENT_BASE/api/yolo/stop
LOCAL_CLIENT_BASE/api/yolo/status
```

重要结论：

如果 `local_gateway.py` 跑在学生电脑，当前代理模式不正确。因为代理发生在服务器进程里，`127.0.0.1:6001` 指的是服务器本机，不是学生电脑。

若本地客户端运行在学生电脑，应改为浏览器直接请求：

```js
fetch(`${LOCAL_CLIENT_BASE}/api/yolo/start`, { method: "POST" })
fetch(`${LOCAL_CLIENT_BASE}/api/yolo/stop`, { method: "POST" })
fetch(`${LOCAL_CLIENT_BASE}/api/yolo/status`)
fetch(`${LOCAL_CLIENT_BASE}/api/get_score_and_contact`)
fetch(`${LOCAL_CLIENT_BASE}/api/get_current_score`)
fetch(`${LOCAL_CLIENT_BASE}/api/get_air_switch_status`)
```

或改为本地客户端主动上报结果到服务器。

## 8. 人脸识别与人脸库

当前人脸识别流程：

```text
学生浏览器采集照片
  -> POST /recognize_face {image}
  -> 服务端 app.py
  -> POST FACE_RECOGNITION_BASE/recognize_face {image}
  -> 返回识别结果给浏览器
```

页面期望识别服务返回：

```json
{
  "success": true,
  "message": "识别成功",
  "emp_id": "用户编号/学号/工号",
  "role": "student 或 teacher",
  "name": "姓名"
}
```

当前服务端项目没有发现：

```text
faces/
/faces/...
```

也没有人脸库静态路由。人脸库应由 `FACE_RECOGNITION_BASE` 对应的人脸识别服务维护，不在当前 Flask 服务中静态暴露。

## 9. 服务端是否负责接线评分 / 保存成绩 / 接收 STM32/YOLO 结果

当前状态：

- 服务端不完整负责接线评分。
- 服务端有规则文件管理和全局状态展示接口。
- 服务端没有正式的本地结果接收接口，例如没有：
  - `POST /student/api/wiring_result`
  - `POST /student/api/yolo_result`
  - `POST /student/api/stm32_result`
- 服务端没有看到“提交本次接线成绩并写入 `exam_result`”的正式接口。
- 学生端 `/student/api/student/score` 只查询 `exam_result`。
- 教师端成绩看板大量使用内存演示数据或固定数据。

当前与接线状态相关的全局变量在 `global_config.py`：

```text
Global_Config.total_score
Global_Config.current_A
Global_Config.current_B
Global_Config.wired_status
Global_Config.switch_status
Global_Config.error_wiring_count
Global_Config.wiring_results
```

这些变量目前没有正式的本地客户端上报入口来驱动。

## 10. local_gateway.py 对接未完成 / 需要修改点

1. 明确部署模式。

如果 `local_gateway.py` 跑在学生电脑，学生页面应直接请求学生本机：

```text
http://127.0.0.1:6001
```

当前服务端代理会访问服务器自己的 `127.0.0.1:6001`，不适合每个学生电脑独立运行本地网关。

2. 如果 `local_gateway.py` 跑在服务器，当前代理可用，但所有学生共用同一个检测客户端，不适合多学生并发。

3. 缺少本地结果上报协议。建议新增服务端接口：

```text
POST /student/api/wiring_result
```

建议请求参数：

```json
{
  "student_no": "20261001",
  "test_id": 1,
  "contact_A": "A1",
  "contact_B": "B1",
  "wired_status": "add | sub | error",
  "score_delta": 10,
  "total_score": 80,
  "timestamp": "2026-06-02 10:00:00",
  "raw_yolo": {},
  "raw_stm32": {}
}
```

建议响应：

```json
{
  "success": true,
  "message": "接线结果已接收",
  "score": 80,
  "contact_A": "A1",
  "contact_B": "B1",
  "wired_status": "add"
}
```

4. 缺少保存成绩接口。建议新增：

```text
POST /student/api/exam_result
```

建议请求参数：

```json
{
  "student_no": "20261001",
  "test_id": 1,
  "test_name": "电机正反转控制电路考试",
  "test_score": 85,
  "knowledge": "电机控制，互锁原理",
  "details": {}
}
```

写入表：

```text
exam_result
```

5. `/student/api/test_score_update` 当前调用未定义 `match_subgraphs()`，应删除或替换为真实评分函数。

6. 人脸识别已独立为：

```text
FACE_RECOGNITION_BASE
```

不要再和：

```text
LOCAL_CLIENT_BASE
```

混用。`LOCAL_CLIENT_BASE` 应只用于学生端本地接线检测网关。

7. 学生机使用服务端返回的命名文件地址下载练习规则。考试入口使用本场考试的签名快照和本机下载回执。
