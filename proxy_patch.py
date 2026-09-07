# -*- coding: utf-8 -*-
"""给 tuimian-web/serve.py 加一段反向代理：/dz 转到本机 8771 的定制协作平台。
校园网只放行 8080 和 22，两个站只能挤一个端口。在服务器上跑：python3 proxy_patch.py"""
import io, sys

P = "/data1/liutianrui/tuimian-web/serve.py"
s = io.open(P, encoding="utf-8").read()
if "PROXY = {" in s:
    print("already patched"); sys.exit(0)

s = s.replace("import hashlib, hmac, os, sys, urllib.parse\n",
              "import hashlib, hmac, http.client, os, sys, urllib.parse\n", 1)
s = s.replace('COOKIE = "tm"\n', 'COOKIE = "tm"\nPROXY = {"/dz": ("127.0.0.1", 8771)}   # 定制协作平台，/dz 原样转过去\n', 1)

methods = '''    def proxy_of(self):
        p = self.path.split("?")[0]
        for pre, tgt in PROXY.items():
            if p == pre or p.startswith(pre + "/"):
                return tgt
        return None

    def forward(self):
        host, port = self.proxy_of()
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else None
        hdrs = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "connection")}
        hdrs["X-Forwarded-For"] = self.client_address[0]
        try:
            conn = http.client.HTTPConnection(host, port, timeout=900)
            conn.request(self.command, self.path, body=body, headers=hdrs)
            resp = conn.getresponse()
        except Exception:
            self.plain(502, "后面的服务没起来")
            return
        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() in ("transfer-encoding", "connection", "cache-control"):
                continue
            self.send_header(k, v)
        self.end_headers()
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            self.wfile.write(chunk)
        conn.close()

    def do_PUT(self):
        if self.proxy_of():
            return self.forward()
        self.plain(404, "没有这个页面")

    def do_DELETE(self):
        if self.proxy_of():
            return self.forward()
        self.plain(404, "没有这个页面")

    def site_of(self, path):'''
s = s.replace("    def site_of(self, path):", methods, 1)
s = s.replace("    def do_GET(self):\n        self.handle_req(True)",
              "    def do_GET(self):\n        if self.proxy_of():\n            return self.forward()\n        self.handle_req(True)", 1)
s = s.replace("    def do_HEAD(self):\n        self.handle_req(False)",
              "    def do_HEAD(self):\n        if self.proxy_of():\n            return self.forward()\n        self.handle_req(False)", 1)
s = s.replace('    def do_POST(self):\n        path = self.path.split("?")[0]\n',
              '    def do_POST(self):\n        if self.proxy_of():\n            return self.forward()\n        path = self.path.split("?")[0]\n', 1)
assert s.count("return self.forward()") == 5, s.count("return self.forward()")
io.open(P, "w", encoding="utf-8").write(s)
print("patched")
