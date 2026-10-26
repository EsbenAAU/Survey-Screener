"""Local web server for Survey Screener (standard library only).

    python run.py                 -> http://localhost:8765
    python run.py --port 9000 --projects D:/reviews
"""
import argparse
import json
import mimetypes
import os
import re
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import metadata, pdfs, prisma, terms
from .store import Project, list_projects, slugify, NOT_RETRIEVED, import_legacy_decisions

STATIC = os.path.join(os.path.dirname(__file__), "static")
ROOT = "projects"
_projects, _jobs, _plock = {}, {}, threading.Lock()


def get_project(slug):
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    with _plock:
        if slug not in _projects:
            folder = os.path.join(ROOT, slug)
            if not os.path.exists(os.path.join(folder, "project.json")):
                raise KeyError(slug)
            _projects[slug] = Project(folder)
        return _projects[slug]


# ---------------------------------------------------------------- background jobs
class Job:
    def __init__(self, kind):
        self.kind, self.i, self.n, self.current = kind, 0, 0, ""
        self.lines, self.running, self.stopped, self.error = [], True, False, ""

    def progress(self, i, n, cur):
        self.i, self.n, self.current = i, n, cur

    def log(self, msg):
        self.lines.append(msg)
        self.lines = self.lines[-400:]

    def state(self):
        return {"kind": self.kind, "i": self.i, "n": self.n, "current": self.current, "running": self.running,
                "lines": self.lines[-60:], "error": self.error}


def start_job(slug, kind, fn):
    j = _jobs.get(slug)
    if j and j.running:
        raise RuntimeError(f"A '{j.kind}' job is already running")
    j = Job(kind)
    _jobs[slug] = j

    def work():
        try:
            fn(j)
        except Exception as e:
            j.error = f"{type(e).__name__}: {e}"
            j.log("ERROR: " + j.error)
            traceback.print_exc()
        finally:
            j.running = False
    threading.Thread(target=work, daemon=True).start()
    return j


# ---------------------------------------------------------------- views
_text_cache = {}


def fulltext(p, rid):
    tp = p.text_path(rid)
    if not os.path.exists(tp):
        if p.has_pdf(rid):
            return pdfs.ensure_text(p, rid)
        return ""
    mt = os.path.getmtime(tp)
    c = _text_cache.get(tp)
    if not c or c[0] != mt:
        c = (mt, open(tp, encoding="utf-8", errors="replace").read())
        _text_cache[tp] = c
    return c[1]


def project_view(p):
    inc, exc = p.data["terms"]["include"], p.data["terms"]["exclude"]
    out = []
    for r in p.records:
        x = dict(r)
        x["has_pdf"] = p.has_pdf(r["id"])
        txt = terms.record_text(r)
        x["hits_inc"] = terms.hits(inc, txt)
        x["hits_exc"] = terms.hits(exc, txt)
        if x["has_pdf"] and (inc or exc):
            ft = fulltext(p, r["id"])
            x["hits_inc_ft"] = [t for t in terms.hits(inc, ft) if t not in x["hits_inc"]]
            x["hits_exc_ft"] = [t for t in terms.hits(exc, ft) if t not in x["hits_exc"]]
        out.append(x)
    d = {k: v for k, v in p.data.items() if k != "records"}
    d["records"] = out
    d["counts"] = prisma.counts(p)
    d["not_retrieved_reason"] = NOT_RETRIEVED
    return d


# ---------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    server_version = "SurveyScreener/2"

    def log_message(self, fmt, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def json_body(self):
        b = self.body()
        return json.loads(b) if b else {}

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def route(self, method):
        try:
            u = urllib.parse.urlparse(self.path)
            parts = [urllib.parse.unquote(x) for x in u.path.strip("/").split("/") if x]
            q = urllib.parse.parse_qs(u.query)
            if not parts or parts[0] != "api":
                return self.static(u.path)
            return self.api(method, parts[1:], q)
        except KeyError as e:
            self.send(404, {"error": f"not found: {e}"})
        except Exception as e:
            traceback.print_exc()
            self.send(400, {"error": f"{type(e).__name__}: {e}"})

    def static(self, path):
        path = "index.html" if path in ("", "/") else path.lstrip("/")
        f = os.path.normpath(os.path.join(STATIC, path))
        if not f.startswith(STATIC) or not os.path.isfile(f):
            return self.send(404, "not found", "text/plain")
        self.send(200, open(f, "rb").read(), (mimetypes.guess_type(f)[0] or "application/octet-stream")
                  + ("; charset=utf-8" if f.endswith((".html", ".js", ".css")) else ""))

    def api(self, method, parts, q):
        if parts == ["projects"]:
            if method == "GET":
                return self.send(200, list_projects(ROOT))
            name = (self.json_body().get("name") or "").strip() or "Review"
            slug, n = slugify(name), 1
            base = slug
            while os.path.exists(os.path.join(ROOT, slug)):
                n += 1
                slug = f"{base}-{n}"
            p = Project(os.path.join(ROOT, slug))
            p.data["name"] = name
            p.save()
            return self.send(200, {"slug": slug})
        if len(parts) < 2 or parts[0] != "project":
            raise KeyError("/".join(parts))
        slug, rest = parts[1], parts[2:]
        p = get_project(slug)

        if method == "GET" and not rest:
            return self.send(200, project_view(p))
        if method == "GET" and rest == ["counts"]:
            return self.send(200, prisma.counts(p))
        if method == "GET" and rest == ["job"]:
            j = _jobs.get(slug)
            return self.send(200, j.state() if j else {"running": False, "lines": []})
        if method == "GET" and len(rest) == 2 and rest[0] == "pdf":
            path = p.pdf_path(rest[1])
            if not os.path.exists(path):
                raise KeyError(rest[1])
            return self.send(200, open(path, "rb").read(), "application/pdf")
        if method == "GET" and len(rest) == 2 and rest[0] == "export":
            return self.export(p, rest[1])

        if method == "POST":
            if rest == ["import"]:
                b = self.json_body()
                src = p.import_file(b["filename"], b["content"], b.get("label", ""))
                return self.send(200, src)
            if rest == ["import-decisions"]:
                return self.send(200, import_legacy_decisions(p, json.loads(self.json_body()["content"])))
            if rest == ["rename"]:
                p.data["name"] = self.json_body().get("name") or p.data["name"]
                p.save()
                return self.send(200, {"ok": True})
            if rest == ["terms"]:
                b = self.json_body()
                clean = lambda xs: [x.strip() for x in xs if x and x.strip()]
                p.data["terms"] = {"include": clean(b.get("include", [])), "exclude": clean(b.get("exclude", []))}
                p.save()
                return self.send(200, {"ok": True})
            if rest == ["settings"]:
                b = self.json_body()
                for k in ("email", "browser", "browser_channel", "reasons_ta", "reasons_ft"):
                    if k in b:
                        p.data["settings"][k] = b[k]
                p.save()
                return self.send(200, {"ok": True})
            if rest == ["decide"]:
                b = self.json_body()
                p.decide(b["ids"], b["stage"], b.get("value"), b.get("reason", ""), b.get("note"))
                return self.send(200, {"ok": True, "counts": prisma.counts(p)})
            if rest == ["apply-exclusion-terms"]:
                return self.send(200, self.apply_exclusion(p, self.json_body()))
            if rest == ["undo-automation"]:
                ids = [rid for rid, d in p.data["decisions"].items() if d.get("ta_auto")]
                p.decide(ids, "ta", None)
                return self.send(200, {"undone": len(ids)})
            if len(rest) == 2 and rest[0] == "upload-pdf":
                data = self.body()
                if not data.startswith(b"%PDF"):
                    raise ValueError("not a PDF file")
                rid = rest[1]
                if not p.rec(rid):
                    raise KeyError(rid)
                open(p.pdf_path(rid), "wb").write(data)
                p.rec(rid)["pdf_source"] = "added by hand"
                p.rec(rid).pop("pdf_failed", None)
                pdfs.ensure_text(p, rid)
                p.save()
                return self.send(200, {"ok": True})
            if rest == ["job", "metadata"]:
                b = self.json_body()
                start_job(slug, "metadata", lambda j: metadata.run(p, j, only_missing=not b.get("all")))
                return self.send(200, {"ok": True})
            if rest == ["job", "pdf"]:
                b = self.json_body()
                start_job(slug, "pdf", lambda j: pdfs.run(p, j, scope=b.get("scope", "ta_included"),
                                                          retry_failed=bool(b.get("retry")), max_n=int(b.get("max") or 0)))
                return self.send(200, {"ok": True})
            if rest == ["job", "stop"]:
                j = _jobs.get(slug)
                if j:
                    j.stopped = True
                return self.send(200, {"ok": True})
        raise KeyError("/".join(rest))

    def apply_exclusion(self, p, b):
        """Auto-exclude records whose title/abstract/keywords match an exclusion term (PRISMA: automation tools).
        Records already decided by hand are left alone. With dry_run=True only the count is returned."""
        exc = p.data["terms"]["exclude"]
        inc = p.data["terms"]["include"]
        protect = bool(b.get("protect_included_terms"))
        ids, by_term = [], {}
        for r in p.records:
            if r.get("dup_of") or p.data["decisions"].get(r["id"], {}).get("ta"):
                continue
            txt = terms.record_text(r)
            h = terms.hits(exc, txt)
            if not h or (protect and terms.hits(inc, txt)):
                continue
            ids.append((r["id"], h[0]))
            by_term[h[0]] = by_term.get(h[0], 0) + 1
        if not b.get("dry_run"):
            groups = {}
            for rid, t in ids:
                groups.setdefault(t, []).append(rid)
            for t, rids in groups.items():
                p.decide(rids, "ta", "exclude", f"Automation: exclusion term '{t}'", auto=True)
            p.log(f"Automation: {len(ids)} records excluded by exclusion terms")
            p.save()
        return {"n": len(ids), "by_term": by_term}

    def export(self, p, kind):
        c = prisma.counts(p)
        name = slugify(p.data["name"])
        if kind == "prisma.svg":
            return self.send(200, prisma.svg(c), "image/svg+xml")
        if kind == "prisma.tex":
            return self.send(200, prisma.tikz(c), "text/plain; charset=utf-8",
                             {"Content-Disposition": f'attachment; filename="{name}_prisma.tex"'})
        if kind == "screening.csv":
            return self.send(200, prisma.screening_csv(p), "text/csv; charset=utf-8",
                             {"Content-Disposition": f'attachment; filename="{name}_screening.csv"'})
        if kind == "included.bib":
            return self.send(200, prisma.included_bib(p), "text/plain; charset=utf-8",
                             {"Content-Disposition": f'attachment; filename="{name}_included.bib"'})
        if kind == "methods.txt":
            return self.send(200, prisma.methods_text(p, c), "text/plain; charset=utf-8")
        if kind == "counts.json":
            return self.send(200, c)
        if kind == "project.json":
            return self.send(200, p.data, headers={"Content-Disposition": f'attachment; filename="{name}_project.json"'})
        raise KeyError(kind)


def main():
    global ROOT
    ap = argparse.ArgumentParser(description="Survey Screener — local screening tool for systematic/survey reviews")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--projects", default=os.path.join(os.getcwd(), "projects"), help="folder for review projects")
    ap.add_argument("--no-browser", action="store_true", help="do not open the web browser automatically")
    a = ap.parse_args()
    ROOT = os.path.abspath(a.projects)
    os.makedirs(ROOT, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    url = f"http://localhost:{a.port}/"
    print(f"Survey Screener running at {url}  (projects in {ROOT})  — Ctrl+C to stop")
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        for p in _projects.values():
            p.save()
