# -*- coding: utf-8 -*-
"""
扣子(Coze)智能体后端代理
- 仅使用 Python 标准库，无需安装任何依赖
- 前端请求 /api/chat -> 本服务携带 PAT 调用扣子 v3/chat (流式) -> SSE 转发回前端
- token 只存在于服务端 .env 文件中，浏览器不可见
"""
import json
import os
import re
import ssl
import http.client
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_env():
    """极简 .env 解析：KEY=VALUE，# 开头为注释"""
    env_path = os.path.join(BASE_DIR, '.env')
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()
BOT_ID = os.environ.get('COZE_BOT_ID', '')
PAT = os.environ.get('COZE_PAT', '')


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    # ---------- 路由 ----------
    def do_POST(self):
        if self.path == '/api/chat':
            self.handle_chat()
        elif self.path.startswith('/api/upload'):
            self.handle_upload()
        else:
            self.send_error(404)

    def end_headers(self):
        # HTML 不缓存，避免更新后访客浏览器仍用旧页面
        path = self.path.split('?')[0]
        if path == '/' or path.endswith('.html'):
            self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def do_GET(self):
        if self.path == '/api/config':
            self.handle_config()
        else:
            super().do_GET()

    # ---------- 智能体公开信息（开场白/推荐问题） ----------
    def handle_config(self):
        if (not BOT_ID or not PAT
                or '在这里填入' in BOT_ID or '在这里填入' in PAT):
            return self.send_json_error(
                500, '服务端未配置：请编辑 .env 文件，填入 COZE_BOT_ID 和 COZE_PAT')
        try:
            conn = http.client.HTTPSConnection(
                'api.coze.cn', 443, timeout=15,
                context=ssl.create_default_context())
            conn.request('GET', '/v1/bots/' + BOT_ID, headers={
                'Authorization': 'Bearer ' + PAT,
            })
            resp = conn.getresponse()
            data = json.loads(resp.read().decode('utf-8', 'replace'))
            conn.close()
        except Exception as e:
            return self.send_json_error(502, '无法获取智能体信息：%s' % e)

        if data.get('code') != 0:
            return self.send_json_error(502, '扣子API：%s' % data.get('msg'))

        info = data.get('data') or {}
        ob = info.get('onboarding_info') or {}
        # 开场白支持 {{name}} 占位符，替换成访客昵称
        prologue = (ob.get('prologue') or '').replace('{{name}}', '朋友')
        out = {
            'name': info.get('name') or '',
            'prologue': prologue,
            'suggested_questions': ob.get('suggested_questions') or [],
        }
        body = json.dumps(out, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'max-age=300')
        self.end_headers()
        self.wfile.write(body)

    # ---------- 图片上传（转发到扣子 /v1/files/upload） ----------
    def handle_upload(self):
        if (not BOT_ID or not PAT
                or '在这里填入' in BOT_ID or '在这里填入' in PAT):
            return self.send_json_error(
                500, '服务端未配置：请编辑 .env 文件，填入 COZE_BOT_ID 和 COZE_PAT')

        length = int(self.headers.get('Content-Length', 0))
        if length <= 0:
            return self.send_json_error(400, '没有收到文件内容')
        if length > 20 * 1024 * 1024:
            return self.send_json_error(400, '图片不能超过 20MB')
        data = self.rfile.read(length)

        # 文件名从 query string 获取
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        filename = (qs.get('filename') or ['image.jpg'])[0]

        # 手动拼 multipart/form-data
        boundary = '----cozeproxyboundary7a9f'
        ctype = self.headers.get('Content-Type', 'image/jpeg')
        body = (
            ('--%s\r\n' % boundary).encode()
            + ('Content-Disposition: form-data; name="file"; filename="%s"\r\n' % filename).encode('utf-8')
            + ('Content-Type: %s\r\n\r\n' % ctype).encode()
            + data
            + ('\r\n--%s--\r\n' % boundary).encode()
        )

        try:
            conn = http.client.HTTPSConnection(
                'api.coze.cn', 443, timeout=60,
                context=ssl.create_default_context())
            conn.request('POST', '/v1/files/upload', body=body, headers={
                'Authorization': 'Bearer ' + PAT,
                'Content-Type': 'multipart/form-data; boundary=' + boundary,
            })
            resp = conn.getresponse()
            result = json.loads(resp.read().decode('utf-8', 'replace'))
            conn.close()
        except Exception as e:
            return self.send_json_error(502, '上传失败：%s' % e)

        if result.get('code') != 0:
            return self.send_json_error(502, '扣子API：%s' % result.get('msg'))

        file_id = (result.get('data') or {}).get('id')
        out = json.dumps({'file_id': file_id}, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    # ---------- 聊天代理 ----------
    def handle_chat(self):
        length = int(self.headers.get('Content-Length', 0))
        try:
            body = json.loads(self.rfile.read(length) or b'{}')
            messages = body.get('messages', [])
        except Exception:
            return self.send_json_error(400, '请求体不是合法 JSON')

        if not messages:
            return self.send_json_error(400, 'messages 不能为空')

        # 访客 ID：前端按浏览器生成，用于隔离不同访客的扣子会话记忆
        # 服务端做白名单校验，防止伪造非法值
        raw_uid = str(body.get('user_id') or '').strip()
        if re.fullmatch(r'[A-Za-z0-9_-]{1,64}', raw_uid):
            user_id = raw_uid
        else:
            user_id = 'web_visitor'

        if (not BOT_ID or not PAT
                or '在这里填入' in BOT_ID or '在这里填入' in PAT):
            return self.send_json_error(
                500, '服务端未配置：请编辑 .env 文件，填入 COZE_BOT_ID 和 COZE_PAT')

        # 组装扣子 v3/chat 请求（取最近 20 条上下文，防止过长）
        additional = []
        for m in messages[-20:]:
            role = m.get('role')
            if role not in ('user', 'assistant'):
                continue
            text = str(m.get('content', ''))
            file_id = m.get('file_id')
            if role == 'user' and file_id:
                # 图片消息：object_string 混合格式
                parts = []
                if text:
                    parts.append({'type': 'text', 'text': text})
                parts.append({'type': 'image', 'file_id': str(file_id)})
                additional.append({
                    'role': 'user',
                    'content': json.dumps(parts, ensure_ascii=False),
                    'content_type': 'object_string',
                })
            else:
                additional.append({
                    'role': role,
                    'content': text,
                    'content_type': 'text',
                })

        payload = {
            'bot_id': BOT_ID,
            'user_id': user_id,
            'stream': True,
            'auto_save_history': True,
            'additional_messages': additional,
        }

        # 请求扣子 API
        try:
            conn = http.client.HTTPSConnection(
                'api.coze.cn', 443, timeout=120,
                context=ssl.create_default_context())
            conn.request('POST', '/v3/chat',
                         body=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                         headers={
                'Authorization': 'Bearer ' + PAT,
                'Content-Type': 'application/json; charset=utf-8',
            })
            resp = conn.getresponse()
        except Exception as e:
            return self.send_json_error(502, '无法连接扣子API：%s' % e)

        if resp.status != 200:
            raw = resp.read().decode('utf-8', 'replace')[:500]
            conn.close()
            try:
                err_obj = json.loads(raw)
                msg = err_obj.get('msg') or raw
            except Exception:
                msg = raw
            return self.send_json_error(502, '扣子API返回 %s：%s' % (resp.status, msg))

        # 建立 SSE 响应
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()

        # 逐行读取上游 SSE，提取回答增量并转发
        event = ''
        try:
            while True:
                line = resp.readline()
                if not line:
                    break
                line = line.decode('utf-8', 'replace').rstrip('\r\n')

                if line.startswith('event:'):
                    event = line[6:].strip()
                elif line.startswith('data:'):
                    data = line[5:].strip()
                    if not data or data == '[DONE]':
                        continue
                    try:
                        obj = json.loads(data)
                    except Exception:
                        continue

                    if event == 'conversation.message.delta' and obj.get('type') == 'answer':
                        content = obj.get('content', '')
                        if content:
                            self._sse({'content': content})
                    elif event == 'conversation.chat.failed':
                        msg = (obj.get('last_error') or {}).get('msg') or '对话失败'
                        self._sse({'error': msg})
                    elif event == 'error':
                        msg = obj.get('msg') or ('错误码 %s' % obj.get('code'))
                        self._sse({'error': msg})
                elif line.startswith('{'):
                    # 鉴权失败等场景：HTTP 200 + 单行 JSON 错误体（非 SSE）
                    try:
                        obj = json.loads(line)
                    except Exception:
                        obj = None
                    if obj and obj.get('code') not in (0, None):
                        self._sse({'error': obj.get('msg') or '扣子API错误'})
                elif line == '':
                    event = ''

            self._sse({'done': True})
        except (BrokenPipeError, ConnectionResetError):
            pass  # 浏览器主动断开
        finally:
            conn.close()

    # ---------- 工具 ----------
    def _sse(self, obj):
        data = json.dumps(obj, ensure_ascii=False)
        self.wfile.write(('data: %s\n\n' % data).encode('utf-8'))
        self.wfile.flush()

    def send_json_error(self, code, msg):
        data = json.dumps({'error': msg}, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass  # 静默日志


if __name__ == '__main__':
    import socket
    port = int(os.environ.get('PORT', '8000'))
    # 获取本机局域网 IP（不会真正发包，仅查询路由）
    lan_ip = '127.0.0.1'
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    print('本机访问:   http://localhost:%d/chat.html' % port)
    print('手机访问:   http://%s:%d/chat.html  （需与电脑连同一 Wi-Fi）' % (lan_ip, port))
    print('按 Ctrl+C 停止')
    # 0.0.0.0 = 允许局域网设备（手机）访问
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
