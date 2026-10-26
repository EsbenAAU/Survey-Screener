"""Metadata update: fill missing abstracts, DOIs, years, venues and authors.

Sources, in order: OpenAlex (by DOI, or by title if no DOI), Semantic Scholar, Crossref,
and finally the IEEE Xplore page (abstracts are public there). Existing values are never
overwritten — only empty fields are filled.
"""
import html
import json
import re
import urllib.parse

from . import net
from .store import title_key


def clean(t):
    t = re.sub(r"<[^>]+>", " ", t or "")
    t = html.unescape(t)
    t = re.sub(r"^\s*(abstract|summary)\s*[:.\-—]?\s*", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()


def _inv(inv):
    pos = {i: w for w, ii in (inv or {}).items() for i in ii}
    return clean(" ".join(pos[i] for i in sorted(pos)))


def openalex(r, email):
    mail = f"mailto={urllib.parse.quote(email)}" if email else ""
    if r["doi"]:
        s, w = net.get_json(f"https://api.openalex.org/works/doi:{urllib.parse.quote(r['doi'])}?{mail}", delay=0.2)
    else:
        q = urllib.parse.quote(r["title"][:250])
        s, res = net.get_json(f"https://api.openalex.org/works?search={q}&per-page=3&{mail}", delay=0.2)
        w = None
        for cand in (res or {}).get("results", []):
            if title_key(cand.get("title") or "") == title_key(r["title"]):
                w = cand
                break
    if not w:
        return {}
    loc = (w.get("primary_location") or {}).get("source") or {}
    return {
        "abstract": _inv(w.get("abstract_inverted_index")),
        "doi": (w.get("doi") or "").replace("https://doi.org/", "").lower(),
        "year": str(w.get("publication_year") or ""),
        "venue": loc.get("display_name") or "",
        "authors": [a["author"]["display_name"] for a in w.get("authorships", []) if a.get("author")][:50],
        "oa_pdf": ((w.get("best_oa_location") or {}).get("pdf_url") or ""),
    }


def semantic_scholar(r):
    if not r["doi"]:
        return {}
    s, w = net.get_json(f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(r['doi'])}"
                        "?fields=abstract,year,venue", delay=1.1)
    if not w:
        return {}
    return {"abstract": clean(w.get("abstract") or ""), "year": str(w.get("year") or ""), "venue": w.get("venue") or ""}


def crossref(r, email):
    if not r["doi"]:
        return {}
    mail = f"?mailto={urllib.parse.quote(email)}" if email else ""
    s, w = net.get_json(f"https://api.crossref.org/works/{urllib.parse.quote(r['doi'])}{mail}", delay=0.3)
    m = (w or {}).get("message") or {}
    if not m:
        return {}
    yr = ((m.get("issued") or {}).get("date-parts") or [[None]])[0][0]
    return {"abstract": clean(m.get("abstract") or ""), "year": str(yr or ""),
            "venue": (m.get("container-title") or [""])[0],
            "authors": [f"{a.get('family', '')}, {a.get('given', '')}".strip(", ") for a in m.get("author", [])][:50]}


META_RX = re.compile(r"xplGlobal\.document\.metadata\s*=\s*(\{.*?\});\s*\n", re.S)


def ieee_page(r):
    if not r["doi"].startswith(("10.1109/", "10.23919/")):
        return {}
    s, final, b, _ = net.get("https://doi.org/" + urllib.parse.quote(r["doi"], safe="/"), accept="text/html", delay=2)
    if s != 200 or "ieeexplore" not in final:
        return {}
    m = META_RX.search(b.decode("utf-8", "replace"))
    if not m:
        return {}
    try:
        return {"abstract": clean(json.loads(m.group(1)).get("abstract") or "")}
    except Exception:
        return {}


def run(project, ctl, only_missing=True):
    email = project.data["settings"].get("email", "")
    recs = [r for r in project.records if not r.get("dup_of")
            and project.data["decisions"].get(r["id"], {}).get("ta") != "exclude"]
    if only_missing:
        recs = [r for r in recs if not r["abstract"] or not r["doi"] or not r["year"]]
    n_upd = 0
    for i, r in enumerate(recs, 1):
        if ctl.stopped:
            break
        ctl.progress(i, len(recs), r["id"])
        filled = []
        for name, fn in (("openalex", lambda: openalex(r, email)), ("semanticscholar", lambda: semantic_scholar(r)),
                         ("crossref", lambda: crossref(r, email)), ("ieee", lambda: ieee_page(r))):
            need_abs = len(r["abstract"]) < 100
            if not need_abs and r["doi"] and r["year"] and r["venue"] and r["authors"]:
                break
            if name == "ieee" and not need_abs:
                continue
            try:
                m = fn()
            except Exception:
                m = {}
            for k in ("abstract", "doi", "year", "venue", "authors"):
                v = m.get(k)
                if not v:
                    continue
                if k == "abstract" and (len(v) < 100 or not need_abs):
                    continue
                if k != "abstract" and r.get(k):
                    continue
                r[k] = v
                filled.append(f"{k}<{name}")
            if m.get("oa_pdf") and not r.get("oa_pdf"):
                r["oa_pdf"] = m["oa_pdf"]
        if filled:
            n_upd += 1
            r.setdefault("meta_sources", [])
            r["meta_sources"] = sorted(set(r["meta_sources"] + [f.split("<")[1] for f in filled]))
            ctl.log(f"{r['id']}: " + ", ".join(filled))
        if i % 20 == 0:
            project.save()
    project.log(f"Metadata update: {n_upd} of {len(recs)} records updated")
    project.save()
    ctl.log(f"Done — {n_upd} of {len(recs)} records updated.")
