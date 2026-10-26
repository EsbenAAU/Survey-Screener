"""Project storage: one folder per review project.

projects/<slug>/
    project.json      records, decisions, terms, settings, import log
    pdf/<id>.pdf      full texts (downloaded or added by hand)
    text/<id>.txt     extracted full text (cache, used for term search)
"""
import datetime
import json
import os
import re
import threading
import unicodedata

from . import importers

DEFAULT_SETTINGS = {
    "email": "",                                   # sent to OpenAlex / Crossref / Unpaywall
    "browser": False,                              # use Playwright (Chrome) for PDFs that block scripts
    "browser_channel": "chrome",
    "reasons_ta": ["Not relevant", "Wrong topic", "Wrong publication type", "Not in English"],
    "reasons_ft": ["Not relevant", "No dataset / no method of interest", "Insufficient detail",
                   "Duplicate publication"],
}
NOT_RETRIEVED = "Not retrieved"                   # special full-text reason (PRISMA: reports not retrieved)


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def slugify(s, maxlen=40):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s[:maxlen] or "project"


def title_key(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", t)


class Project:
    def __init__(self, folder):
        self.folder = folder
        self.lock = threading.RLock()
        self.path = os.path.join(folder, "project.json")
        os.makedirs(os.path.join(folder, "pdf"), exist_ok=True)
        os.makedirs(os.path.join(folder, "text"), exist_ok=True)
        if os.path.exists(self.path):
            self.data = json.load(open(self.path, encoding="utf-8"))
        else:
            self.data = {"name": os.path.basename(folder), "created": now()}
        d = self.data
        d.setdefault("settings", {})
        for k, v in DEFAULT_SETTINGS.items():
            d["settings"].setdefault(k, v)
        d.setdefault("terms", {"include": [], "exclude": []})
        d.setdefault("sources", [])
        d.setdefault("records", [])
        d.setdefault("decisions", {})
        d.setdefault("log", [])

    # ------------------------------------------------------------ persistence
    def save(self):
        with self.lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)

    def log(self, msg):
        self.data["log"].append([now(), msg])
        self.data["log"] = self.data["log"][-500:]

    @property
    def records(self):
        return self.data["records"]

    def rec(self, rid):
        return next((r for r in self.records if r["id"] == rid), None)

    def pdf_path(self, rid):
        return os.path.join(self.folder, "pdf", re.sub(r"[^A-Za-z0-9._-]", "_", rid) + ".pdf")

    def text_path(self, rid):
        return os.path.join(self.folder, "text", re.sub(r"[^A-Za-z0-9._-]", "_", rid) + ".txt")

    def has_pdf(self, rid):
        return os.path.exists(self.pdf_path(rid))

    # ------------------------------------------------------------ import
    def _new_id(self, r, taken):
        au = r["authors"][0] if r["authors"] else ""
        last = (au.split(",")[0] if "," in au else (au.split()[-1] if au.split() else "")) or "anon"
        word = next((w for w in re.findall(r"[A-Za-z]{4,}", r["title"])
                     if w.lower() not in {"with", "from", "using", "based", "towards", "toward"}), "x")
        base = slugify(f"{last}{r['year']}{word}", 30).replace("-", "")
        rid, n = base, 1
        while rid in taken:
            n += 1
            rid = f"{base}_{n}"
        taken.add(rid)
        return rid

    def import_file(self, filename, text, label=""):
        fmt, items = importers.parse_any(filename, text)
        with self.lock:
            taken = {r["id"] for r in self.records}
            by_doi = {r["doi"]: r["id"] for r in self.records if r["doi"] and not r.get("dup_of")}
            by_title = {title_key(r["title"]) + r["year"]: r["id"] for r in self.records
                        if r["title"] and not r.get("dup_of")}
            src = {"label": label or os.path.splitext(filename)[0], "file": filename, "format": fmt,
                   "n": len(items), "imported": now()}
            n_dup = 0
            for it in items:
                if not it["title"] and not it["doi"]:
                    continue
                r = dict(it)
                r["id"] = self._new_id(r, taken)
                r["source"] = src["label"]
                tk = title_key(r["title"]) + r["year"]
                dup = (r["doi"] and by_doi.get(r["doi"])) or (len(tk) > 15 and by_title.get(tk))
                if dup:
                    r["dup_of"] = dup
                    n_dup += 1
                else:
                    if r["doi"]:
                        by_doi[r["doi"]] = r["id"]
                    if len(tk) > 15:
                        by_title[tk] = r["id"]
                self.records.append(r)
            src["duplicates"] = n_dup
            self.data["sources"].append(src)
            self.log(f"Imported {len(items)} records from {filename} ({fmt}) as '{src['label']}', {n_dup} duplicates")
            self.save()
        return src

    # ------------------------------------------------------------ decisions
    def decide(self, ids, stage, value, reason="", note=None, auto=False):
        """stage 'ta' (title/abstract) or 'ft' (full text); value 'include' | 'exclude' | 'maybe' | None."""
        assert stage in ("ta", "ft")
        with self.lock:
            for rid in ids:
                d = self.data["decisions"].setdefault(rid, {})
                if value is None:
                    d.pop(stage, None)
                    d.pop(stage + "_reason", None)
                    d.pop(stage + "_auto", None)
                else:
                    d[stage] = value
                    d[stage + "_reason"] = reason if value == "exclude" else ""
                    if auto:
                        d[stage + "_auto"] = True
                    else:
                        d.pop(stage + "_auto", None)
                if note is not None:
                    d["note"] = note
                d["t"] = now()
                if not any(k in d for k in ("ta", "ft", "note")):
                    self.data["decisions"].pop(rid, None)
            self.save()


def import_legacy_decisions(project, data):
    """Import decisions from an earlier screening file. Supported:
    - a Survey Screener project.json (its "decisions", matched by DOI / title)
    - umod_decisions.json from the earlier UMOD-H review page ({"refs": {id: {excluded, reason, done, doi}}})
    Records are matched by DOI, then by the original record id from the import file.
    Existing decisions in this project are not overwritten."""
    by_doi = {r["doi"]: r for r in project.records if r["doi"] and not r.get("dup_of")}
    by_orig = {}
    for r in project.records:
        if r.get("orig_id") and not r.get("dup_of"):
            by_orig.setdefault(r["orig_id"], r)
    by_title = {title_key(r["title"]): r for r in project.records if r["title"] and not r.get("dup_of")}
    n, miss = 0, 0
    if "records" in data and "decisions" in data:                      # Survey Screener project
        old = {r["id"]: r for r in data["records"]}
        items = []
        for rid, d in data["decisions"].items():
            o = old.get(rid, {})
            r = by_doi.get(o.get("doi")) or by_title.get(title_key(o.get("title", "")))
            items.append((r, d))
        convert = lambda d: d
    else:                                                              # legacy umod_decisions.json
        refs = data.get("refs", data)
        items = []
        for rid, d in refs.items():
            r = by_doi.get((d.get("doi") or "").lower()) or by_orig.get(rid) or by_orig.get(re.sub(r"_[0-9a-f]{4}$", "", rid))
            items.append((r, d))

        def convert(d):
            if d.get("excluded"):
                if (d.get("reason") or "") == "Unavailable":
                    return {"ta": "include", "ta_reason": "", "ft": "exclude", "ft_reason": NOT_RETRIEVED}
                return {"ta": "exclude", "ta_reason": d.get("reason") or "Not relevant"}
            if d.get("done"):
                return {"ta": "include", "ta_reason": "", "ft": "include", "ft_reason": ""}
            return {}
    with project.lock:
        for r, d in items:
            if r is None:
                miss += 1
                continue
            new = {k: v for k, v in convert(d).items() if k in ("ta", "ta_reason", "ft", "ft_reason", "note")}
            if not new:
                continue
            cur = project.data["decisions"].setdefault(r["id"], {})
            if cur.get("ta") or cur.get("ft"):
                continue
            cur.update(new)
            cur["t"] = now()
            cur["imported"] = True
            n += 1
        project.log(f"Imported {n} earlier decisions ({miss} could not be matched)")
        project.save()
    return {"imported": n, "unmatched": miss}


def list_projects(root):
    out = []
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            p = os.path.join(root, name, "project.json")
            if os.path.exists(p):
                try:
                    d = json.load(open(p, encoding="utf-8"))
                    out.append({"slug": name, "name": d.get("name", name), "created": d.get("created", ""),
                                "records": len(d.get("records", []))})
                except Exception:
                    pass
    return out
