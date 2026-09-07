# -*- coding: utf-8 -*-
# 本程序及代码是在 AI 工具辅助下完成的。
"""定制协作平台的后端，只用 Python 标准库，跑在 10.16.13.145。

记录存 data/records.json，文件存 data/files/<记录号>/<文件名>，账号存 data/users.json，
登录态存 data/sessions.json。启动：python3 server.py --port 8771
第一次启动没有账号时会建一个 admin，密码写在 data/初始密码.txt。
"""
import argparse
import email.parser
import email.policy
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import shutil
import sys
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
FILES = os.path.join(DATA, "files")
INDEX = os.path.join(HERE, "index.html")
MAX_UPLOAD = 500 * 1024 * 1024
MIN_FREE = 1 * 1024 * 1024 * 1024
STATUSES = ("待做", "在做", "待审", "完成")
LOCK = threading.Lock()


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def load(name, default):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(name, obj):
    p = os.path.join(DATA, name)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def pw_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 100000).hex()


def ensure_admin():
    users = load("users.json", {})
    if users:
        return
    pwd = secrets.token_urlsafe(9)
    salt = secrets.token_hex(8)
    users["admin"] = {"salt": salt, "hash": pw_hash(pwd, salt), "role": "admin", "created": now()}
    save("users.json", users)
    with open(os.path.join(DATA, "初始密码.txt"), "w", encoding="utf-8") as f:
        f.write("admin " + pwd + "\n")
    print("已建管理员 admin，密码见 data/初始密码.txt")


def safe_name(name):
    name = os.path.basename(name.replace("\\", "/")).strip()
    return name.replace("..", "_") or "未命名"


def parse_multipart(ctype, body):
    """用 email 包拆 multipart/form-data，返回 [(字段名, 文件名或 None, 字节)]。"""
    msg = email.parser.BytesParser(policy=email.policy.default).parsebytes(
        b"Content-Type: " + ctype.encode("latin-1") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    out = []
    for part in msg.iter_parts():
        out.append((part.get_param("name", header="content-disposition"), part.get_filename(),
                    part.get_payload(decode=True) or b""))
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "dingzhi/1"

    def log_message(self, fmt, *args):
        sys.stdout.write("%s %s %s\n" % (time.strftime("%H:%M:%S"), self.address_string(), fmt % args))

    # ---- 小工具 ----
    def send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def fail(self, msg, status=400):
        self.send_json({"error": msg}, status)

    def body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            return {}

    def sid(self):
        cookie = self.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "dz_sid":
                return v
        return ""

    def user(self):
        sessions = load("sessions.json", {})
        s = sessions.get(self.sid())
        if not s:
            return None
        users = load("users.json", {})
        u = users.get(s["name"])
        if not u:
            return None
        return {"name": s["name"], "role": u.get("role", "member")}

    def need_user(self):
        u = self.user()
        if not u:
            self.fail("请先登录", 401)
        return u

    # ---- 路由 ----
    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/", "/index.html"):
            return self.send_file(INDEX, "text/html; charset=utf-8")
        if path == "/api/me":
            u = self.user()
            return self.send_json(u or {})
        if path == "/api/data":
            if not self.need_user():
                return
            with LOCK:
                d = load("records.json", {"records": [], "log": []})
            return self.send_json(d)
        if path == "/api/users":
            u = self.need_user()
            if not u:
                return
            if u["role"] != "admin":
                return self.fail("只有管理员能看成员", 403)
            users = load("users.json", {})
            return self.send_json([{"name": k, "role": v.get("role", "member"), "created": v.get("created", "")}
                                   for k, v in users.items()])
        if path.startswith("/files/"):
            if not self.need_user():
                return
            parts = [urllib.parse.unquote(x) for x in path.split("/")[2:]]
            if len(parts) != 2:
                return self.fail("路径不对", 404)
            fp = os.path.join(FILES, safe_name(parts[0]), safe_name(parts[1]))
            if not os.path.isfile(fp):
                return self.fail("文件不存在", 404)
            ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
            return self.send_file(fp, ctype, download=parts[1])
        self.fail("没有这个地址", 404)

    def send_file(self, fp, ctype, download=None):
        size = os.path.getsize(fp)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        if download:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(download))
        self.end_headers()
        with open(fp, "rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/login":
            b = self.body_json()
            name, pwd = str(b.get("name", "")).strip(), str(b.get("password", ""))
            users = load("users.json", {})
            u = users.get(name)
            if not u or not hmac.compare_digest(u["hash"], pw_hash(pwd, u["salt"])):
                return self.fail("名字或密码不对", 401)
            token = secrets.token_urlsafe(24)
            with LOCK:
                sessions = load("sessions.json", {})
                sessions[token] = {"name": name, "at": now()}
                save("sessions.json", sessions)
            data = json.dumps({"name": name, "role": u.get("role", "member")}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie", "dz_sid=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d" % (token, 86400 * 60))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        if path == "/api/logout":
            with LOCK:
                sessions = load("sessions.json", {})
                sessions.pop(self.sid(), None)
                save("sessions.json", sessions)
            return self.send_json({})
        u = self.need_user()
        if not u:
            return
        if path == "/api/password":
            b = self.body_json()
            users = load("users.json", {})
            me = users[u["name"]]
            if not hmac.compare_digest(me["hash"], pw_hash(str(b.get("old", "")), me["salt"])):
                return self.fail("旧密码不对")
            new = str(b.get("new", ""))
            if len(new) < 4:
                return self.fail("新密码至少 4 位")
            me["salt"] = secrets.token_hex(8)
            me["hash"] = pw_hash(new, me["salt"])
            with LOCK:
                save("users.json", users)
            return self.send_json({})
        if path == "/api/users":
            if u["role"] != "admin":
                return self.fail("只有管理员能加成员", 403)
            b = self.body_json()
            name, pwd = str(b.get("name", "")).strip(), str(b.get("password", ""))
            if not name or len(pwd) < 4:
                return self.fail("名字不能空，密码至少 4 位")
            with LOCK:
                users = load("users.json", {})
                if name in users:
                    return self.fail("已经有这个名字")
                salt = secrets.token_hex(8)
                users[name] = {"salt": salt, "hash": pw_hash(pwd, salt), "role": "admin" if b.get("role") == "admin" else "member",
                               "created": now()}
                save("users.json", users)
            return self.send_json({})
        if path == "/api/records":
            b = self.body_json()
            rec = self.clean(b)
            if not rec:
                return self.fail("题目和版本不能空")
            rec.update({"id": secrets.token_hex(4), "files": [], "created": now(), "updated": now(), "updatedBy": u["name"]})
            self.mutate(lambda d: d["records"].append(rec), "新建 %s %s" % (rec["topic"], rec["version"]), u)
            return self.send_json(rec)
        m = path.split("/")
        if len(m) == 5 and m[1:3] == ["api", "records"] and m[4] == "files":
            return self.upload(m[3], u)
        self.fail("没有这个地址", 404)

    def do_PUT(self):
        u = self.need_user()
        if not u:
            return
        m = urllib.parse.urlsplit(self.path).path.split("/")
        if len(m) == 4 and m[1:3] == ["api", "records"]:
            b = self.body_json()
            rid = m[3]
            box = {}

            def f(d):
                r = next((x for x in d["records"] if x["id"] == rid), None)
                if not r:
                    return
                if "status" in b and len(b) == 1:
                    if b["status"] in STATUSES:
                        r["status"] = b["status"]
                    box["msg"] = "%s %s 改为%s" % (r["topic"], r["version"], r["status"])
                else:
                    c = self.clean(b)
                    if c:
                        r.update(c)
                    box["msg"] = "改了 %s %s" % (r["topic"], r["version"])
                r["updated"], r["updatedBy"] = now(), u["name"]
                box["rec"] = r
            self.mutate(f, lambda: box.get("msg", "改记录"), u)
            return self.send_json(box.get("rec") or {})
        self.fail("没有这个地址", 404)

    def do_DELETE(self):
        u = self.need_user()
        if not u:
            return
        m = [urllib.parse.unquote(x) for x in urllib.parse.urlsplit(self.path).path.split("/")]
        if len(m) == 4 and m[1:3] == ["api", "records"]:
            rid = m[3]
            box = {}

            def f(d):
                r = next((x for x in d["records"] if x["id"] == rid), None)
                if r:
                    d["records"].remove(r)
                    box["msg"] = "删除记录 %s %s" % (r["topic"], r["version"])
                    shutil.rmtree(os.path.join(FILES, safe_name(rid)), ignore_errors=True)
            self.mutate(f, lambda: box.get("msg", "删除记录"), u)
            return self.send_json({})
        if len(m) == 6 and m[1:3] == ["api", "records"] and m[4] == "files":
            rid, name = m[3], safe_name(m[5])
            box = {}

            def g(d):
                r = next((x for x in d["records"] if x["id"] == rid), None)
                if not r:
                    return
                r["files"] = [x for x in r.get("files", []) if x["name"] != name]
                fp = os.path.join(FILES, safe_name(rid), name)
                if os.path.exists(fp):
                    os.remove(fp)
                r["updated"], r["updatedBy"] = now(), u["name"]
                box["msg"] = "删除 %s %s" % (r["version"], name)
            self.mutate(g, lambda: box.get("msg", "删除文件"), u)
            return self.send_json({})
        if len(m) == 4 and m[1:3] == ["api", "users"]:
            if u["role"] != "admin":
                return self.fail("只有管理员能删成员", 403)
            with LOCK:
                users = load("users.json", {})
                if m[3] == u["name"]:
                    return self.fail("不能删自己")
                users.pop(m[3], None)
                save("users.json", users)
            return self.send_json({})
        self.fail("没有这个地址", 404)

    # ---- 业务 ----
    def clean(self, b):
        topic, version = str(b.get("topic", "")).strip(), str(b.get("version", "")).strip()
        if not topic or not version:
            return None
        status = b.get("status") if b.get("status") in STATUSES else "待做"
        return {"topic": topic, "version": version, "template": str(b.get("template", ""))[:20],
                "owner": str(b.get("owner", "")).strip()[:30], "status": status,
                "focus": str(b.get("focus", "")).strip()[:100], "note": str(b.get("note", ""))[:2000]}

    def mutate(self, fn, msg, u):
        with LOCK:
            d = load("records.json", {"records": [], "log": []})
            fn(d)
            text = msg() if callable(msg) else msg
            d["log"].insert(0, {"at": now(), "by": u["name"], "text": text})
            d["log"] = d["log"][:300]
            save("records.json", d)

    def upload(self, rid, u):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            return self.fail("一次最多传 500 MB", 413)
        if shutil.disk_usage(DATA).free - n < MIN_FREE:
            return self.fail("服务器磁盘快满了，放不下", 507)
        ctype = self.headers.get("Content-Type") or ""
        if "multipart/form-data" not in ctype:
            return self.fail("要用 multipart 上传")
        body = self.rfile.read(n)
        with LOCK:
            d = load("records.json", {"records": [], "log": []})
            r = next((x for x in d["records"] if x["id"] == rid), None)
            if not r:
                return self.fail("记录不存在", 404)
            folder = os.path.join(FILES, safe_name(rid))
            os.makedirs(folder, exist_ok=True)
            names = []
            for field, fname, data in parse_multipart(ctype, body):
                if not fname:
                    continue
                name = safe_name(fname)
                with open(os.path.join(folder, name), "wb") as f:
                    f.write(data)
                r["files"] = [x for x in r.get("files", []) if x["name"] != name]
                r["files"].append({"name": name, "size": len(data), "by": u["name"], "at": now()})
                names.append(name)
            r["updated"], r["updatedBy"] = now(), u["name"]
            for name in names:
                d["log"].insert(0, {"at": now(), "by": u["name"], "text": "上传 %s %s" % (r["version"], name)})
            d["log"] = d["log"][:300]
            save("records.json", d)
        return self.send_json({"files": names})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8771)
    a = ap.parse_args()
    os.makedirs(FILES, exist_ok=True)
    ensure_admin()
    if not os.path.exists(os.path.join(DATA, "records.json")):
        save("records.json", {"records": [], "log": []})
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print("定制协作平台 http://%s:%d" % (a.host, a.port))
    srv.serve_forever()


if __name__ == "__main__":
    main()
