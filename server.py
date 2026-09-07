# -*- coding: utf-8 -*-
# 本程序及代码是在 AI 工具辅助下完成的。
"""定制协作平台的后端，只用 Python 标准库，跑在 10.16.13.145 的 8771，由 8080 代理 /dz。

三个人 ltr、qyh、zjl 输名字就能进。A、B、C 三道题各一页，每一行是一个客户的需求，
做完的沉到下面，每一行挂一个文件包。
记录存 data/records.json，登录态存 data/sessions.json；文件存在 /data1/liutianrui/定制文件/<题>题/<序号>/，
每一行有三个勾：定金、结账、完成。
启动：python3 server.py --port 8771
"""
import argparse
import email.parser
import email.policy
import json
import mimetypes
import os
import secrets
import shutil
import sys
import threading
import time
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
FILES = os.path.join(os.path.dirname(HERE), "定制文件")   # 服务器上就是 /data1/liutianrui/定制文件
LIB = os.path.join(os.path.dirname(HERE), "文件库")        # 原稿、定制稿、代码
LIB_TOP = ("原稿", "定制稿", "代码")
LIB_FIXED = LIB_TOP + tuple(top + "/" + k + "题" for top in LIB_TOP for k in "ABC")   # 固定目录，不能删
INDEX = os.path.join(HERE, "index.html")
PREFIX = "/dz"
USERS = ("ltr", "qyh", "zjl")
TOPICS = ("A", "B", "C")
MAX_UPLOAD = 500 * 1024 * 1024
MIN_FREE = 1 * 1024 * 1024 * 1024
TEXT_EXT = (".txt", ".md", ".tex", ".py", ".json", ".csv", ".log", ".html", ".htm", ".js", ".css", ".bib", ".m", ".cls", ".sty", ".bat", ".sh", ".yml", ".yaml", ".ini", ".cfg")
INLINE_EXT = (".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp") + TEXT_EXT
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


def folder_of(r):
    return os.path.join(FILES, r["topic"] + "题", str(r.get("seq", r["id"])))


def safe_name(name):
    name = os.path.basename(name.replace("\\", "/")).strip()
    return name.replace("..", "_") or "未命名"


def safe_rel(path):
    """带子目录的相对路径，去掉 .. 和空段，统一用 / 连。"""
    parts = [safe_name(p) for p in path.replace("\\", "/").split("/") if p.strip() and p.strip() not in (".", "..")]
    return "/".join(parts) or "未命名"


def lib_path(rel):
    rel = safe_rel(rel) if rel else ""
    if rel == "未命名":
        rel = ""
    parts = [p for p in rel.split("/") if p]
    if any(p.startswith(".") for p in parts):
        return None, rel
    return os.path.join(LIB, *parts) if parts else LIB, "/".join(parts)


def zip_name(info):
    n = info.filename
    if not (info.flag_bits & 0x800):
        try:
            n = n.encode("cp437").decode("gbk")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return n


def inline_type(name):
    ext = os.path.splitext(name)[1].lower()
    if ext in TEXT_EXT:
        return "text/plain; charset=utf-8"
    if ext in INLINE_EXT:
        return mimetypes.guess_type(name)[0] or "application/octet-stream"
    return None


def parse_multipart(ctype, body):
    msg = email.parser.BytesParser(policy=email.policy.default).parsebytes(
        b"Content-Type: " + ctype.encode("latin-1") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    return [(p.get_filename(), p.get_payload(decode=True) or b"") for p in msg.iter_parts()]


class Handler(BaseHTTPRequestHandler):
    server_version = "dingzhi/2"

    def log_message(self, fmt, *args):
        sys.stdout.write("%s %s %s\n" % (time.strftime("%H:%M:%S"), self.address_string(), fmt % args))

    def route(self):
        p = urllib.parse.urlsplit(self.path).path
        if p == PREFIX:
            return None
        if p.startswith(PREFIX + "/"):
            p = p[len(PREFIX):]
        return p

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

    def user(self):
        cookie = self.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "dz_sid":
                name = load("sessions.json", {}).get(v)
                return name if name in USERS else None
        return None

    def need_user(self):
        u = self.user()
        if not u:
            self.fail("请先登录", 401)
        return u

    # ---- GET ----
    def do_GET(self):
        path = self.route()
        if path is None:
            self.send_response(302)
            self.send_header("Location", PREFIX + "/")
            self.send_header("Content-Length", "0")
            return self.end_headers()
        if path in ("/", "/index.html"):
            return self.send_file(INDEX, "text/html; charset=utf-8")
        if path == "/api/me":
            return self.send_json({"name": self.user() or ""})
        if path == "/api/data":
            if not self.need_user():
                return
            with LOCK:
                d = load("records.json", {"records": []})
                d.setdefault("trash", [])
                return self.send_json(d)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        if path.startswith("/files/"):
            if not self.need_user():
                return
            parts = [urllib.parse.unquote(x) for x in path.split("/")[2:]]
            if len(parts) < 2:
                return self.fail("路径不对", 404)
            rel = safe_rel("/".join(parts[1:]))
            with LOCK:
                r = next((x for x in load("records.json", {"records": []})["records"] if x["id"] == parts[0]), None)
            fp = os.path.join(folder_of(r), *rel.split("/")) if r else ""
            if not fp or not os.path.isfile(fp):
                return self.fail("文件不存在", 404)
            entry = q.get("entry", [""])[0]
            if entry:
                return self.send_zip_entry(fp, entry)
            base = rel.split("/")[-1]
            ctype = inline_type(base) if q.get("inline") else None
            return self.send_file(fp, ctype or mimetypes.guess_type(fp)[0] or "application/octet-stream",
                                  download=None if ctype else base)
        if path == "/api/lib":
            if not self.need_user():
                return
            fp, rel = lib_path(urllib.parse.unquote(q.get("path", [""])[0]))
            if fp is None or not os.path.isdir(fp):
                return self.fail("没有这个目录", 404)
            dirs, files = [], []
            for name in sorted(os.listdir(fp)):
                if name.startswith("."):
                    continue
                full = os.path.join(fp, name)
                if os.path.isdir(full):
                    cnt = sum(1 for x in os.listdir(full) if not x.startswith("."))
                    dirs.append({"name": name, "count": cnt})
                else:
                    st = os.stat(full)
                    files.append({"name": name, "size": st.st_size, "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime))})
            if not rel:
                dirs.sort(key=lambda x: LIB_TOP.index(x["name"]) if x["name"] in LIB_TOP else 99)
            return self.send_json({"path": rel, "dirs": dirs, "files": files})
        if path == "/api/lib/zip":
            if not self.need_user():
                return
            fp, rel = lib_path(urllib.parse.unquote(q.get("path", [""])[0]))
            if fp is None or not os.path.isfile(fp):
                return self.fail("文件不存在", 404)
            try:
                with zipfile.ZipFile(fp) as z:
                    items = [{"name": zip_name(i), "size": i.file_size} for i in z.infolist() if not i.is_dir()]
            except zipfile.BadZipFile:
                return self.fail("不是 zip 文件")
            return self.send_json({"entries": items})
        if path.startswith("/lib/"):
            if not self.need_user():
                return
            fp, rel = lib_path(urllib.parse.unquote(path[5:]))
            if fp is None or not os.path.isfile(fp):
                return self.fail("文件不存在", 404)
            entry = q.get("entry", [""])[0]
            if entry:
                return self.send_zip_entry(fp, entry)
            base = rel.split("/")[-1]
            ctype = inline_type(base) if q.get("inline") else None
            return self.send_file(fp, ctype or mimetypes.guess_type(fp)[0] or "application/octet-stream",
                                  download=None if ctype else base)
        m = path.split("/")
        if len(m) == 5 and m[1:3] == ["api", "records"] and m[4] == "zip":
            if not self.need_user():
                return
            rel = safe_rel(urllib.parse.unquote(q.get("name", [""])[0]))
            with LOCK:
                r = next((x for x in load("records.json", {"records": []})["records"] if x["id"] == m[3]), None)
            fp = os.path.join(folder_of(r), *rel.split("/")) if r else ""
            if not fp or not os.path.isfile(fp):
                return self.fail("文件不存在", 404)
            try:
                with zipfile.ZipFile(fp) as z:
                    items = [{"name": zip_name(i), "size": i.file_size} for i in z.infolist() if not i.is_dir()]
            except zipfile.BadZipFile:
                return self.fail("不是 zip 文件")
            return self.send_json({"entries": items})
        self.fail("没有这个地址", 404)

    def send_zip_entry(self, fp, entry):
        try:
            with zipfile.ZipFile(fp) as z:
                info = next((i for i in z.infolist() if zip_name(i) == entry), None)
                if info is None:
                    return self.fail("压缩包里没有这个文件", 404)
                data = z.read(info)
        except zipfile.BadZipFile:
            return self.fail("不是 zip 文件")
        base = entry.split("/")[-1]
        ctype = inline_type(base)
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        if not ctype:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(base))
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, fp, ctype, download=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(os.path.getsize(fp)))
        if download:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(download))
        self.end_headers()
        with open(fp, "rb") as f:
            shutil.copyfileobj(f, self.wfile)

    # ---- POST ----
    def do_POST(self):
        path = self.route() or ""
        if path == "/api/login":
            name = str(self.body_json().get("name", "")).strip().lower()
            if name not in USERS:
                return self.fail("密码不对", 401)
            token = secrets.token_urlsafe(24)
            with LOCK:
                sessions = load("sessions.json", {})
                sessions[token] = name
                save("sessions.json", sessions)
            data = json.dumps({"name": name}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie", "dz_sid=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d" % (token, 86400 * 365))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        u = self.need_user()
        if not u:
            return
        if path == "/api/logout":
            return self.send_json({})
        if path == "/api/records":
            b = self.body_json()
            topic = str(b.get("topic", "")).strip().upper()
            customer = str(b.get("customer", "")).strip()[:60]
            need = str(b.get("need", "")).strip()[:2000]
            if topic not in TOPICS:
                return self.fail("题号不对")
            rec = {"id": secrets.token_hex(4), "topic": topic, "customer": customer, "need": need,
                   "owner": str(b.get("owner", u)).strip()[:20] or u, "done": False, "deposit": False,
                   "paid": False, "price": 0, "proof": {}, "files": [], "created": now(), "updated": now(), "updatedBy": u}

            def f(d):
                used = [x.get("seq", 0) for x in d["records"] if x["topic"] == topic]
                used += [t["rec"].get("seq", 0) for t in d.get("trash", []) if t["kind"] == "row" and t["rec"]["topic"] == topic]
                rec["seq"] = 1 + max(used or [0])
                d["records"].append(rec)
            self.mutate(f)
            return self.send_json(rec)
        m = path.split("/")
        if len(m) == 5 and m[1:3] == ["api", "records"] and m[4] == "fromlib":
            return self.from_lib(m[3], u)
        if len(m) == 5 and m[1:3] == ["api", "records"] and m[4] == "files":
            return self.upload(m[3], u)
        if len(m) == 6 and m[1:3] == ["api", "records"] and m[4] == "proof" and m[5] in ("done", "deposit", "paid"):
            return self.upload(m[3], u, proof=m[5])
        if len(m) == 5 and m[1:3] == ["api", "trash"] and m[4] == "restore":
            return self.restore(m[3], u)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        if path == "/api/lib/mkdir":
            b = self.body_json()
            fp, rel = lib_path(str(b.get("path", "")))
            name = safe_name(str(b.get("name", "")))
            if fp is None or not os.path.isdir(fp) or name.startswith("."):
                return self.fail("目录不对")
            os.makedirs(os.path.join(fp, name), exist_ok=True)
            return self.send_json({})
        if path == "/api/lib/upload":
            fp, rel = lib_path(urllib.parse.unquote(q.get("path", [""])[0]))
            if fp is None or not os.path.isdir(fp):
                return self.fail("目录不对")
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_UPLOAD:
                return self.fail("一次最多传 500 MB", 413)
            if shutil.disk_usage(LIB).free - n < MIN_FREE:
                return self.fail("服务器磁盘快满了", 507)
            ctype = self.headers.get("Content-Type") or ""
            if "multipart/form-data" not in ctype:
                return self.fail("要用 multipart 上传")
            body = self.rfile.read(n)
            names = []
            for fname, data in parse_multipart(ctype, body):
                if not fname:
                    continue
                name = safe_rel(fname)
                if any(p.startswith(".") for p in name.split("/")):
                    continue
                dst = os.path.join(fp, *name.split("/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as f:
                    f.write(data)
                names.append(name)
            return self.send_json({"files": names})
        self.fail("没有这个地址", 404)

    def do_PUT(self):
        u = self.need_user()
        if not u:
            return
        m = (self.route() or "").split("/")
        if len(m) == 4 and m[1:3] == ["api", "records"]:
            b = self.body_json()
            box = {}

            def f(d):
                r = next((x for x in d["records"] if x["id"] == m[3]), None)
                if not r:
                    return
                if "customer" in b:
                    r["customer"] = str(b["customer"]).strip()[:60]
                if "need" in b:
                    r["need"] = str(b["need"]).strip()[:2000]
                if "note" in b:
                    r["note"] = str(b["note"]).strip()[:500]
                if "owner" in b:
                    r["owner"] = str(b["owner"]).strip()[:20]
                if "price" in b:
                    try:
                        r["price"] = max(0.0, float(b["price"] or 0))
                    except (TypeError, ValueError):
                        pass
                for k in ("done", "deposit", "paid"):
                    if k in b:
                        if b[k] and not r.get("proof", {}).get(k):
                            box["err"] = "先传凭证照片"
                            return
                        r[k] = bool(b[k])
                r["updated"], r["updatedBy"] = now(), u
                box["rec"] = r
            self.mutate(f)
            if box.get("err"):
                return self.fail(box["err"])
            return self.send_json(box.get("rec") or {})
        self.fail("没有这个地址", 404)

    def do_DELETE(self):
        u = self.need_user()
        if not u:
            return
        m = [urllib.parse.unquote(x) for x in (self.route() or "").split("/")]
        if len(m) == 4 and m[1:3] == ["api", "records"]:
            def f(d):
                for x in d["records"]:
                    if x["id"] == m[3]:
                        d["trash"].insert(0, {"id": secrets.token_hex(4), "kind": "row", "at": now(), "by": u, "rec": x})
                d["records"] = [x for x in d["records"] if x["id"] != m[3]]
            self.mutate(f)
            return self.send_json({})
        if len(m) >= 6 and m[1:3] == ["api", "records"] and m[4] == "files":
            rid, rel = m[3], safe_rel("/".join(m[5:]))
            is_dir = "dir=1" in urllib.parse.urlsplit(self.path).query

            def g(d):
                r = next((x for x in d["records"] if x["id"] == rid), None)
                if not r:
                    return
                hit = [x for x in r.get("files", []) if (x["name"].startswith(rel + "/") if is_dir else x["name"] == rel)]
                for x in hit:
                    src = os.path.join(folder_of(r), *x["name"].split("/"))
                    dst = os.path.join(folder_of(r), ".回收站", *x["name"].split("/"))
                    if os.path.exists(src):
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        os.replace(src, dst)
                    item = {"id": secrets.token_hex(4), "kind": "file", "at": now(), "by": u, "rid": r["id"],
                            "topic": r["topic"], "seq": r.get("seq"), "file": x}
                    for k, v in list(r.get("proof", {}).items()):
                        if v == x["name"]:
                            item["proof"] = k
                            del r["proof"][k]
                            r[k] = False
                    d["trash"].insert(0, item)
                names = {x["name"] for x in hit}
                r["files"] = [x for x in r.get("files", []) if x["name"] not in names]
                if is_dir:
                    shutil.rmtree(os.path.join(folder_of(r), *rel.split("/")), ignore_errors=True)
                r["updated"], r["updatedBy"] = now(), u
            self.mutate(g)
            return self.send_json({})
        if m[1:3] == ["api", "lib"] and len(m) == 3:
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            fp, rel = lib_path(urllib.parse.unquote(q.get("path", [""])[0]))
            if fp is None or not rel or rel in LIB_FIXED or not os.path.exists(fp):
                return self.fail("不能删这个")
            tid = secrets.token_hex(4)
            dst = os.path.join(LIB, ".回收站", tid, rel.split("/")[-1])
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            isdir = os.path.isdir(fp)
            size = os.path.getsize(fp) if not isdir else 0
            os.replace(fp, dst)
            self.mutate(lambda d: d["trash"].insert(0, {"id": tid, "kind": "lib", "at": now(), "by": u, "path": rel,
                                                         "isdir": isdir, "size": size}))
            return self.send_json({})
        if len(m) == 4 and m[1:3] == ["api", "trash"]:
            def h(d):
                t = next((x for x in d["trash"] if x["id"] == m[3]), None)
                if not t:
                    return
                if t["kind"] == "row":
                    shutil.rmtree(folder_of(t["rec"]), ignore_errors=True)
                elif t["kind"] == "lib":
                    shutil.rmtree(os.path.join(LIB, ".回收站", t["id"]), ignore_errors=True)
                else:
                    fp = os.path.join(FILES, t["topic"] + "题", str(t["seq"]), ".回收站", *t["file"]["name"].split("/"))
                    if os.path.exists(fp):
                        os.remove(fp)
                d["trash"] = [x for x in d["trash"] if x["id"] != m[3]]
            self.mutate(h)
            return self.send_json({})
        self.fail("没有这个地址", 404)

    def restore(self, tid, u):
        box = {}

        def f(d):
            t = next((x for x in d["trash"] if x["id"] == tid), None)
            if not t:
                box["err"] = "回收站里没有这一条"
                return
            if t["kind"] == "row":
                r = t["rec"]
                r["updated"], r["updatedBy"] = now(), u
                d["records"].append(r)
            elif t["kind"] == "lib":
                src = os.path.join(LIB, ".回收站", t["id"], t["path"].split("/")[-1])
                dst = os.path.join(LIB, *t["path"].split("/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.exists(dst):
                    stem, ext = os.path.splitext(dst)
                    dst = stem + "-恢复" + ext
                if os.path.exists(src):
                    os.replace(src, dst)
                shutil.rmtree(os.path.join(LIB, ".回收站", t["id"]), ignore_errors=True)
            else:
                r = next((x for x in d["records"] if x["id"] == t["rid"]), None)
                if not r:
                    box["err"] = "这个文件所在的行还在回收站里，先恢复那一行"
                    return
                x = t["file"]
                src = os.path.join(folder_of(r), ".回收站", *x["name"].split("/"))
                dst = os.path.join(folder_of(r), *x["name"].split("/"))
                if os.path.exists(src):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    os.replace(src, dst)
                r["files"] = [y for y in r.get("files", []) if y["name"] != x["name"]] + [x]
                if t.get("proof"):
                    r.setdefault("proof", {})[t["proof"]] = x["name"]
                    r[t["proof"]] = True
                r["updated"], r["updatedBy"] = now(), u
            d["trash"] = [y for y in d["trash"] if y["id"] != tid]
        self.mutate(f)
        if box.get("err"):
            return self.fail(box["err"])
        return self.send_json({})

    def mutate(self, fn):
        with LOCK:
            d = load("records.json", {"records": []})
            d.setdefault("trash", [])
            fn(d)
            save("records.json", d)

    def from_lib(self, rid, u):
        """把文件库里选中的文件或文件夹拷进这一行的文件包。"""
        paths = [str(x) for x in (self.body_json().get("paths") or [])][:200]
        added = []
        with LOCK:
            d = load("records.json", {"records": []})
            r = next((x for x in d["records"] if x["id"] == rid), None)
            if not r:
                return self.fail("这一行不存在", 404)
            folder = folder_of(r)
            for p in paths:
                src, rel = lib_path(p)
                if src is None or not rel or not os.path.exists(src):
                    continue
                base = rel.split("/")[-1]
                pairs = []
                if os.path.isdir(src):
                    for root, dirs, files in os.walk(src):
                        dirs[:] = [x for x in dirs if not x.startswith(".")]
                        for fn in files:
                            if fn.startswith("."):
                                continue
                            full = os.path.join(root, fn)
                            relname = base + "/" + os.path.relpath(full, src).replace(os.sep, "/")
                            pairs.append((full, relname))
                else:
                    pairs.append((src, base))
                for full, relname in pairs:
                    dst = os.path.join(folder, *relname.split("/"))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(full, dst)
                    r["files"] = [x for x in r.get("files", []) if x["name"] != relname]
                    r["files"].append({"name": relname, "size": os.path.getsize(dst), "by": u, "at": now()})
                    added.append(relname)
            r["updated"], r["updatedBy"] = now(), u
            save("records.json", d)
        return self.send_json({"files": added})

    def upload(self, rid, u, proof=None):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            return self.fail("一次最多传 500 MB", 413)
        if shutil.disk_usage(DATA).free - n < MIN_FREE:
            return self.fail("服务器磁盘快满了", 507)
        ctype = self.headers.get("Content-Type") or ""
        if "multipart/form-data" not in ctype:
            return self.fail("要用 multipart 上传")
        body = self.rfile.read(n)
        with LOCK:
            d = load("records.json", {"records": []})
            r = next((x for x in d["records"] if x["id"] == rid), None)
            if not r:
                return self.fail("这一行不存在", 404)
            folder = folder_of(r)
            os.makedirs(folder, exist_ok=True)
            names = []
            for fname, data in parse_multipart(ctype, body):
                if not fname:
                    continue
                name = safe_rel(fname)
                if proof:
                    ext = os.path.splitext(name)[1].lower() or ".jpg"
                    name = "凭证/%s-%s%s" % ({"done": "完成", "deposit": "定金", "paid": "结账"}[proof],
                                             time.strftime("%Y%m%d-%H%M%S"), ext)
                fp = os.path.join(folder, *name.split("/"))
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, "wb") as f:
                    f.write(data)
                r["files"] = [x for x in r.get("files", []) if x["name"] != name]
                r["files"].append({"name": name, "size": len(data), "by": u, "at": now()})
                names.append(name)
                if proof:
                    r.setdefault("proof", {})[proof] = name
                    r[proof] = True
            r["updated"], r["updatedBy"] = now(), u
            save("records.json", d)
        return self.send_json({"files": names})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8771)
    a = ap.parse_args()
    os.makedirs(FILES, exist_ok=True)
    os.makedirs(DATA, exist_ok=True)
    for top in LIB_FIXED:
        os.makedirs(os.path.join(LIB, *top.split("/")), exist_ok=True)
    if not os.path.exists(os.path.join(DATA, "records.json")):
        save("records.json", {"records": []})
    print("定制协作平台 http://%s:%d" % (a.host, a.port))
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
