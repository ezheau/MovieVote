#!/usr/bin/env python3
# ══════════════════════════════════════════════════════════════
#  MovieVote — локальный сервер: раздача страницы + ИИ-прокси.
#
#  Запуск:   python server.py          (порт 8765 по умолчанию)
#  или:      python server.py 8080
#  Страница: http://127.0.0.1:8765/index.html
#
#  Зачем прокси: браузеры блокируют прямые запросы со страницы
#  к api.z.ai / api.openai.com / api.deepseek.com (CORS) или эти
#  хосты могут быть недоступны без VPN. Прокси выполняет запрос
#  с локальной машины, страница обращается сама к себе.
#  Ключ из страницы передаётся дальше без изменений и нигде
#  не сохраняется. Служит только на 127.0.0.1.
# ══════════════════════════════════════════════════════════════
import json
import sys
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
ROOT = Path(__file__).resolve().parent

PROVIDERS = {
    'zai': 'https://api.z.ai/api/paas/v4/chat/completions',
    'anthropic': 'https://api.anthropic.com/v1/messages',
    'openai': 'https://api.openai.com/v1/chat/completions',
    'deepseek': 'https://api.deepseek.com/chat/completions',
}
# во внешний мир — только эти хосты (localhost — для тестов)
ALLOWED = {'api.z.ai', 'api.anthropic.com', 'api.openai.com', 'api.deepseek.com'}
LOCAL = {'127.0.0.1', 'localhost', '::1'}

# GET-списки моделей провайдеров
MODELS_URLS = {
    'zai': 'https://api.z.ai/api/paas/v4/models',
    'anthropic': 'https://api.anthropic.com/v1/models',
    'openai': 'https://api.openai.com/v1/models',
    'deepseek': 'https://api.deepseek.com/models',
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        pass  # тихий лог

    # ── CORS (на случай открытия страницы с другого порта) ──
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type, X-Target-Url')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    # ── пинг прокси ──
    def do_GET(self):
        path, _, query = self.path.partition('?')
        if path == '/ai-proxy/ping':
            self._json(200, {'proxy': True})
            return
        if path == '/ai-proxy/models':
            slug = (parse_qs(query).get('provider') or [''])[0]
            target = MODELS_URLS.get(slug)
            if not target:
                self._json(404, {'error': {'message': 'Неизвестный провайдер: ' + slug}})
                return
            headers = {}
            for h in ('Authorization', 'x-api-key', 'anthropic-version'):
                if self.headers.get(h):
                    headers[h] = self.headers.get(h)
            try:
                req = urllib.request.Request(target, headers=headers, method='GET')
                with urllib.request.urlopen(req, timeout=30) as up:
                    self._raw(up.status, up.read(), 'application/json')
            except urllib.error.HTTPError as e:
                ctype = e.headers.get('Content-Type', 'application/json') if e.headers else 'application/json'
                self._raw(e.code, e.read(), ctype)
            except Exception as e:
                self._json(502, {'error': {'message': f'Нет связи с провайдером: {e}. Проверьте сеть/VPN.'}})
            return
        super().do_GET()

    # ── пересылка запроса к ИИ ──
    def do_POST(self):
        path, _, query = self.path.partition('?')
        if not path.startswith('/ai-proxy/'):
            self.send_error(404)
            return
        slug = path[len('/ai-proxy/'):]
        if slug == 'ping':
            self._json(200, {'proxy': True})
            return
        target = PROVIDERS.get(slug)
        if slug == 'custom':
            target = (parse_qs(query).get('target') or [''])[0]
        if not target:
            self._json(404, {'error': {'message': 'Неизвестный провайдер: ' + slug}})
            return
        host = (urlparse(target).hostname or '').lower()
        if not ((target.startswith('https://') and host in ALLOWED) or host in LOCAL):
            self._json(403, {'error': {'message': 'Хост не разрешён: ' + host}})
            return

        length = int(self.headers.get('Content-Length') or 0)
        data = self.rfile.read(length) if length else b''
        headers = {'Content-Type': self.headers.get('Content-Type', 'application/json')}
        for h in ('Authorization', 'x-api-key', 'anthropic-version'):
            if self.headers.get(h):
                headers[h] = self.headers.get(h)

        req = urllib.request.Request(target, data=data, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=120) as up:
                self._raw(up.status, up.read(), up.headers.get('Content-Type', 'application/json'))
        except urllib.error.HTTPError as e:
            ctype = e.headers.get('Content-Type', 'application/json') if e.headers else 'application/json'
            self._raw(e.code, e.read(), ctype)
        except Exception as e:
            self._json(502, {'error': {'message': f'Нет связи с {host}: {e}. Проверьте сеть/VPN.'}})

    def _raw(self, code, payload, ctype):
        self.send_response(code)
        self._cors()
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, code, obj):
        self._raw(code, json.dumps(obj, ensure_ascii=False).encode('utf-8'),
                  'application/json; charset=utf-8')


if __name__ == '__main__':
    print(f'MovieVote: http://127.0.0.1:{PORT}/index.html  (статика + ИИ-прокси), Ctrl+C — остановить')
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
