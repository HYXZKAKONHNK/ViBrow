from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import urllib.request
import random
import re

class ProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def do_PUT(self):
        self.handle_request()

    def do_DELETE(self):
        self.handle_request()

    def do_HEAD(self):
        self.handle_request()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, POST, OPTIONS, PUT, DELETE')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()

    def handle_request(self):
        parsed_path = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed_path.query)
        url_str = query_params.get('url', [None])[0]

        # Автоматический рендеринг картинок и стилей сайтов внутри iframe через Referer
        if not url_str:
            referer = self.headers.get('Referer')
            if referer and parsed_path.path in referer:
                try:
                    ref_parsed = urllib.parse.urlparse(referer)
                    ref_query = urllib.parse.parse_qs(ref_parsed.query)
                    actual_target = ref_query.get('url', [None])[0]
                    if actual_target:
                        origin_url = urllib.parse.urlparse(actual_target)
                        base_origin = f"{origin_url.scheme}://{origin_url.netloc}"
                        url_str = base_origin + parsed_path.path
                        if parsed_path.query:
                            url_str += f"?{parsed_path.query}"
                except Exception:
                    pass

        if not url_str:
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write('ViBrow Ultra-Proxy v5.1 is Active! (Python version)'.encode('utf-8'))
            return

        try:
            # 🛡️ 1. МАСКИРОВКА IP И ДЕПАКЕТИЗАЦИЯ
            random_ip = f"{random.randint(20, 159)}.{random.randint(0, 199)}.{random.randint(0, 199)}.{random.randint(10, 249)}"
            
            headers = {
                'X-Forwarded-For': random_ip,
                'X-Real-IP': random_ip,
                'True-Client-IP': random_ip,
                'Client-IP': random_ip,
                # 🛡️ 2. МАСКИРОВКА ЦИФРОВОГО ОТПЕЧАТКА
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                'Cache-Control': 'max-age=0',
                'Sec-Ch-Ua': '"Chromium";v="124", "Google Chrome";v="124"',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none'
            }

            # Передаем тело запроса для POST / PUT
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length) if content_length > 0 else None

            req = urllib.request.Request(url_str, data=body, headers=headers, method=self.command)
            
            with urllib.request.urlopen(req) as resp:
                resp_body = resp.read()
                resp_status = resp.status
                resp_headers = resp.headers

                # 🛡️ 3. ОБРАБОТКА ЗАГОЛОВКОВ И СТИРАНИЕ CORS
                self.send_response(resp_status)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, POST, OPTIONS, PUT, DELETE')
                self.send_header('Access-Control-Allow-Headers', '*')

                excluded_headers = {'x-frame-options', 'content-security-policy', 'x-content-type-options', 'transfer-encoding', 'content-encoding'}
                for key, val in resp_headers.items():
                    if key.lower() not in excluded_headers:
                        self.send_header(key, val)

                content_type = resp_headers.get('Content-Type', '')

                # Обработка HTML для исправления относительных путей
                if 'text/html' in content_type:
                    try:
                        body_text = resp_body.decode('utf-8', errors='ignore')
                        target_parsed = urllib.parse.urlparse(url_str)
                        target_origin = f"{target_parsed.scheme}://{target_parsed.netloc}"
                        
                        proxy_prefix = f"/?url={target_origin}"
                        body_text = re.sub(r'(src|href)=["\']/(?!/)(.*?)["\']', r'\1="' + proxy_prefix + r'/\2"', body_text)
                        
                        resp_body = body_text.encode('utf-8')
                        self.send_header('Content-Length', len(resp_body))
                        self.end_headers()
                        self.wfile.write(resp_body)
                        return
                    except Exception:
                        pass

                self.send_header('Content-Length', len(resp_body))
                self.end_headers()
                self.wfile.write(resp_body)

        except Exception as err:
            self.send_response(500)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(f'Secure Proxy Error: {str(err)}'.encode('utf-8'))

if __name__ == '__main__':
    server_address = ('', 8080)
    httpd = HTTPServer(server_address, ProxyHandler)
    print("ViBrow Ultra-Proxy v5.1 (Python) is running on http://localhost:8080")
    httpd.serve_forever()
