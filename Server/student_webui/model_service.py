"""OpenAI-compatible model access and private, per-student practice settings."""
import base64
import binascii
import json
import os
from datetime import datetime
from hashlib import sha256
from ipaddress import ip_address
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

import requests
from flask import Blueprint, current_app, jsonify, request, session

from tools.config import PRACTICE_MODEL_DEFAULTS

models = Blueprint('practice_models', __name__)


class ModelError(Exception):
    def __init__(self, message, status=400, *, requires_key=False):
        super().__init__(message)
        self.status = status
        self.requires_key = requires_key


@models.errorhandler(ModelError)
def model_error(error):
    return jsonify(success=False, message=str(error), requires_key=error.requires_key), error.status


@models.before_request
def require_student():
    if not session.get('student'):
        raise ModelError('请先登录学生账号。', 401)


def settings_path(student_id):
    directory = Path(current_app.config.get('MODEL_SETTINGS_DIR') or
                     Path(__file__).resolve().parents[1] / 'data' / 'model_settings')
    return directory / (sha256(str(student_id).encode()).hexdigest() + '.json')


def read_settings(student_id):
    try:
        return json.loads(settings_path(student_id).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {**PRACTICE_MODEL_DEFAULTS, 'api_key': '', 'saved': False}


def public_settings(config):
    # Older profiles keep their original endpoint for inference until explicitly resaved.
    endpoint = urlsplit(config['base_url'])
    host = endpoint.hostname
    try:
        ip = str(ip_address('127.0.0.1' if host == 'localhost' else host))
    except ValueError:
        ip = ''
    return {name: config[name] for name in ('chat', 'question', 'saved')} | {
        'ip': ip, 'port': endpoint.port or (443 if endpoint.scheme == 'https' else 80),
        'has_key': bool(config.get('api_key'))
    }


def request_fields():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ModelError('请求内容应为 JSON 对象。')
    return data


def endpoint_config(data):
    host = data.get('ip')
    try:
        if not isinstance(host, str) or '%' in host:
            raise ValueError
        ip = ip_address(host.strip())
    except ValueError:
        raise ModelError('请输入 IPv4 或 IPv6 地址，无需协议和路径。') from None
    port = str(data.get('port', ''))
    if not (port.isascii() and port.isdecimal() and len(port) <= 5 and 1 <= int(port) <= 65535):
        raise ModelError('端口号必须是 1 到 65535 之间的整数。')
    host = f'[{ip}]' if ip.version == 6 else str(ip)
    base_url = f'http://{host}:{int(port)}/v1'
    key = data.get('api_key', '')
    if not isinstance(key, str) or any(not 33 <= ord(c) <= 126 for c in key.strip()):
        raise ModelError('API Key 格式不正确。')
    key = key.strip()
    if not key:
        saved = read_settings(session['student']['id'])
        if base_url == saved['base_url']:
            key = saved.get('api_key', '')
    return {'base_url': base_url, 'api_key': key}


def model_request(config, path, payload=None):
    headers = {}
    if config.get('api_key'):
        headers['Authorization'] = 'Bearer ' + config['api_key']
    try:
        response = requests.request('GET' if payload is None else 'POST',
                                    config['base_url'] + path, headers=headers, json=payload,
                                    timeout=(5, 10 if payload is None else 90), allow_redirects=False)
        if response.status_code in (401, 403):
            raise ModelError('模型服务拒绝访问，请检查 API Key 和访问权限。', 502, requires_key=True)
        if not response.ok or response.is_redirect:
            raise ModelError(f'模型服务返回 HTTP {response.status_code}，请检查接口地址和模型能力。', 502)
        result = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ModelError('无法读取模型服务响应，请检查地址、端口及网络。', 502) from exc
    if not isinstance(result, dict):
        raise ModelError('模型服务返回了无法识别的数据。', 502)
    return result


def list_models(config):
    items = model_request(config, '/models').get('data')
    if not isinstance(items, list):
        raise ModelError('模型列表格式不符合 OpenAI 兼容接口。', 502)
    return list(dict.fromkeys(item['id'] for item in items
                              if isinstance(item, dict) and isinstance(item.get('id'), str) and item['id']))


@models.post('/api/models/discover')
def discover():
    config = endpoint_config(request_fields())
    return jsonify(success=True, models=list_models(config))


@models.post('/api/models/settings')
def save_settings():
    sno = session['student']['id']
    data = request_fields()
    config = endpoint_config(data)
    available = list_models(config)
    if data.get('chat') not in available or data.get('question') not in available:
        raise ModelError('所选模型已不可用，请重新获取模型列表。')
    config.update(chat=data['chat'], question=data['question'], saved=True)
    path = settings_path(sno)
    temp = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temp = Path(stream.name)
            json.dump(config, stream, ensure_ascii=False)
        os.replace(temp, path)
    except OSError as exc:
        raise ModelError('设置保存失败，请稍后重试。', 503) from exc
    finally:
        if temp:
            temp.unlink(missing_ok=True)
    return jsonify(success=True, settings=public_settings(config))


def completion(kind, content):
    config = read_settings(session['student']['id'])
    if not config[kind]:
        raise ModelError('请先在「大模型信息设置」中保存模型。')
    result = model_request(config, '/chat/completions', {
        'model': config[kind], 'messages': [{'role': 'user', 'content': content}], 'stream': False
    })
    try:
        answer = result['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        answer = None
    if not isinstance(answer, str) or not answer.strip():
        raise ModelError('模型未返回文本内容，请检查所选模型。', 502)
    return answer


@models.post('/api/ai_chat')
def ai_chat():
    data = request_fields()
    question = data.get('question', '')
    if not isinstance(question, str):
        raise ModelError('请输入文字问题。')
    question = question.strip()
    image = data.get('image')
    if not question and not image:
        raise ModelError('请输入问题或选择图片。')
    content = question
    if image:
        if not isinstance(image, str):
            raise ModelError('无效的图片数据。')
        header, _, encoded = image.partition(',')
        if header not in ('data:image/png;base64', 'data:image/jpeg;base64', 'data:image/webp;base64'):
            raise ModelError('请选择 PNG、JPEG 或 WebP 图片。')
        if len(encoded) > ((5 * 1024 * 1024 + 2) // 3) * 4:
            raise ModelError('图片大小须在 5 MB 以内。')
        try:
            if not base64.b64decode(encoded, validate=True):
                raise ValueError
        except (ValueError, binascii.Error):
            raise ModelError('无效的图片数据。') from None
        content = [{'type': 'text', 'text': question or '请解释这张图片。'},
                   {'type': 'image_url', 'image_url': {'url': image}}]
    return jsonify(success=True, answer=completion('chat', content),
                   timestamp=datetime.now().strftime('%H:%M:%S'))


@models.post('/api/models/question')
def model_question():
    data = request_fields()
    subject_filter = data.get('subject') or '电力拖动系统'
    knowledge_filter = data.get('knowledge') or '电力拖动系统'
    prompt = f"""请根据以下知识点为电力拖动系统专业学生生成2道选择题、2道填空题和1道简答题：

学科：{subject_filter}
知识点：{knowledge_filter}

请严格按照以下格式生成题目，**不要添加任何额外的分隔符、标记或解释性文字**：

选择题1：
题目：题干内容
A. 选项A
B. 选项B
C. 选项C
D. 选项D
答案：A/B/C/D
解析：详细解析

选择题2：
题目：题干内容
A. 选项A
B. 选项B
C. 选项C
D. 选项D
答案：A/B/C/D
解析：详细解析

填空题1：
题目：题干内容
答案：参考答案
解析：详细解析

填空题2：
题目：题干内容
答案：参考答案
解析：详细解析

简答题：
题目：题干内容
答案：参考答案
解析：详细解析

要求：
1. 题目要专业准确，符合电力拖动系统教学要求
2. 选择题选项要合理，有干扰性
3. 填空题要考察学生对知识点的记忆和理解
4. 简答题要考察学生对知识点的深入理解和应用能力
5. 解析要详细，帮助学生理解知识点
6. **非常重要：不要生成任何额外的分隔符（如###、===等）或装饰性文本，只生成符合上述格式的题目内容**"""
    text = completion('question', prompt)
    return jsonify(success=True, question={'subject': subject_filter, 'knowledge': knowledge_filter,
                                          'question': text, 'raw_response': text})
