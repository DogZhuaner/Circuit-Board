"""Non-streaming model transport shared by practice, vision and the skill CLI."""
from urllib.parse import quote, urlsplit

import requests


class ProviderError(ValueError):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


class ModelClient:
    def __init__(self, base, key="", protocol="auto"):
        parts = urlsplit(base)
        if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ProviderError("请输入 HTTP(S) 服务基础地址，密钥请单独填写。")
        path = parts.path.rstrip("/")
        if protocol == "auto":
            if parts.hostname == "api.anthropic.com" or path.endswith("/messages"):
                protocol = "anthropic"
            elif parts.hostname == "generativelanguage.googleapis.com" or path.endswith("/v1beta"):
                protocol = "gemini"
            elif path.endswith(("/api", "/api/chat")) or (not path and parts.port == 11434):
                protocol = "ollama"
            else:
                protocol = "openai"
        if protocol not in ("openai", "ollama", "anthropic", "gemini"):
            raise ProviderError("不支持的模型接口类型。")
        self.protocol = protocol
        suffix = {"openai": "/chat/completions", "ollama": "/chat", "anthropic": "/messages"}.get(protocol)
        if suffix and path.endswith(suffix):
            path = path[:-len(suffix)]
        if not path:
            path = {"openai": "/v1", "ollama": "/api", "anthropic": "/v1", "gemini": "/v1beta"}[protocol]
        self.base = f"{parts.scheme}://{parts.netloc}{path}"
        self.headers = {"anthropic-version": "2023-06-01"} if protocol == "anthropic" else {}
        if key:
            name = {"anthropic": "x-api-key", "gemini": "x-goog-api-key"}.get(protocol, "Authorization")
            self.headers[name] = ("Bearer " if name == "Authorization" else "") + key

    def request(self, path, body=None, timeout=90):
        options = dict(headers=self.headers, timeout=(5, timeout), allow_redirects=False)
        try:
            if body is None:
                response = requests.get(self.base + path, **options)
            else:
                response = requests.post(self.base + path, json=body, **options)
            if response.status_code != 200:
                raise ProviderError(f"模型服务返回 HTTP {response.status_code}", response.status_code)
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError("模型服务连接失败或返回无效 JSON。") from exc
        if not isinstance(data, dict):
            raise ProviderError("模型响应应为 JSON 对象。")
        return data

    def models(self):
        fields = {"ollama": ("/tags", "models", "name"), "gemini": ("/models", "models", "name")}
        path, field, name = fields.get(self.protocol, ("/models", "data", "id"))
        items = self.request(path, timeout=10).get(field)
        if not isinstance(items, list):
            raise ProviderError("无法识别模型列表。")
        return [i[name].removeprefix("models/") if self.protocol == "gemini" else i[name]
                for i in items if isinstance(i, dict) and isinstance(i.get(name), str)
                and (self.protocol != "gemini" or "generateContent" in i.get("supportedGenerationMethods", []))]

    def complete(self, payload, timeout=90):
        kind = self.protocol
        model = payload["model"]
        limit = payload.get("max_tokens", 4096)
        if kind == "openai":
            body = dict(payload)
            path = "/chat/completions"
        else:
            messages, system = [], []
            for msg in payload["messages"]:
                content = msg["content"]
                if msg["role"] == "system":
                    system.append(content)
                    continue
                parts = [{"type":"text", "text":content}] if isinstance(content, str) else content
                blocks, images, texts = [], [], []
                for part in parts:
                    if part["type"] == "text":
                        texts.append(part["text"])
                        blocks.append({"text":part["text"]} if kind == "gemini" else part)
                    else:
                        header, data = part["image_url"]["url"].split(",", 1)
                        mime = header.split(";")[0].removeprefix("data:")
                        images.append(data)
                        blocks.append({"inline_data":{"mime_type":mime,"data":data}} if kind == "gemini" else
                                      {"type":"image","source":{"type":"base64","media_type":mime,"data":data}})
                if kind == "ollama":
                    messages.append(dict(role=msg["role"], content="\n".join(texts)))
                    if images:
                        messages[-1]["images"] = images
                elif kind == "gemini":
                    messages.append(dict(role="model" if msg["role"] == "assistant" else "user", parts=blocks))
                else:
                    messages.append(dict(role=msg["role"], content=blocks))
            instruction = "\n".join(system)
            temperature = {"temperature":payload["temperature"]} if "temperature" in payload else {}
            fmt = payload.get("response_format", {})
            if kind == "ollama":
                path = "/chat"
                if instruction:
                    messages.insert(0, dict(role="system", content=instruction))
                body = dict(model=model, messages=messages, stream=False, options=dict(num_predict=limit, **temperature))
                if fmt:
                    body["format"] = fmt.get("json_schema", {}).get("schema", "json")
            elif kind == "anthropic":
                path = "/messages"
                body = dict(model=model, messages=messages, max_tokens=limit, **temperature)
                if instruction:
                    body["system"] = instruction
            else:
                path = "/models/" + quote(model.removeprefix("models/"), safe="") + ":generateContent"
                body = dict(contents=messages, generationConfig=dict(maxOutputTokens=limit, **temperature))
                if fmt:
                    body["generationConfig"]["responseMimeType"] = "application/json"
                if instruction:
                    body["systemInstruction"] = {"parts":[{"text":instruction}]}
        try:
            result = self.request(path, body, timeout)
        except ProviderError as exc:
            # Compatible servers may reject structured output or Qwen-specific options.
            optional = {"response_format", "chat_template_kwargs"}
            if kind != "openai" or exc.status not in (400, 422) or optional.isdisjoint(body):
                raise
            result = self.request(path, {k: v for k, v in body.items() if k not in optional}, timeout)
        try:
            if kind == "openai":
                choice = result["choices"][0]
                text, reason = choice["message"]["content"], choice.get("finish_reason")
            elif kind == "ollama":
                text, reason = result["message"]["content"], result.get("done_reason")
            elif kind == "anthropic":
                text = "".join(p["text"] for p in result["content"] if p.get("type") == "text")
                reason = result.get("stop_reason")
            else:
                candidate = result["candidates"][0]
                text = "".join(p.get("text","") for p in candidate["content"]["parts"] if not p.get("thought"))
                reason = candidate.get("finishReason")
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ProviderError("模型响应缺少有效的文本结果。") from exc
        if reason in ("length", "MAX_TOKENS", "max_tokens"):
            raise ProviderError("模型输出被截断，请提高输出上限或缩小输入范围。")
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("模型未返回文本。")
        return text
