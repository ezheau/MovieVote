#!/usr/bin/env python3
"""Тестовый мок OpenAI-совместимого API: POST /v1/chat/completions -> фиксированный ответ."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        self.rfile.read(n)
        body = json.dumps({
            'choices': [{'message': {'content':
                '```json\n{"titles":["Тест-фильм Альфа","Тест-фильм Бета"]}\n```'}}]
        }).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

HTTPServer(('127.0.0.1', 9999), H).serve_forever()
