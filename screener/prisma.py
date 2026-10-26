"""PRISMA 2020 counts and exports (flow diagram as SVG / TikZ, screening record CSV, BibTeX, methods text)."""
import csv
import io
from collections import Counter, OrderedDict
from xml.sax.saxutils import escape

from .store import NOT_RETRIEVED


def counts(p):
    d = p.data["decisions"]
    recs = p.records
    uniq = [r for r in recs if not r.get("dup_of")]
    c = OrderedDict()
    c["sources"] = OrderedDict()
    for s in p.data["sources"]:
        c["sources"][s["label"]] = c["sources"].get(s["label"], 0) + s["n"]
    c["identified"] = len(recs)
    c["duplicates"] = len(recs) - len(uniq)
    auto = [r for r in uniq if d.get(r["id"], {}).get("ta") == "exclude" and d[r["id"]].get("ta_auto")]
    c["automation"] = len(auto)
    screened = [r for r in uniq if r not in auto]
    c["screened"] = len(screened)
    ta = Counter(d.get(r["id"], {}).get("ta") or "pending" for r in screened)
    c["ta_excluded"] = ta["exclude"]
    c["ta_excluded_reasons"] = dict(Counter(d[r["id"]].get("ta_reason") or "Unspecified" for r in screened
                                            if d.get(r["id"], {}).get("ta") == "exclude"))
    c["ta_pending"] = ta["pending"] + ta["maybe"]
    c["ta_maybe"] = ta["maybe"]
    sought = [r for r in screened if d.get(r["id"], {}).get("ta") == "include"]
    c["sought"] = len(sought)
    c["sought_with_pdf"] = sum(1 for r in sought if p.has_pdf(r["id"]))
    ft = lambda r: d.get(r["id"], {}).get("ft")
    ftr = lambda r: d.get(r["id"], {}).get("ft_reason") or "Unspecified"
    c["not_retrieved"] = sum(1 for r in sought if ft(r) == "exclude" and ftr(r) == NOT_RETRIEVED)
    assessed = [r for r in sought if ft(r) in ("include", "exclude") and not (ft(r) == "exclude" and ftr(r) == NOT_RETRIEVED)]
    c["assessed"] = len(assessed)
    c["ft_excluded"] = sum(1 for r in assessed if ft(r) == "exclude")
    c["ft_excluded_reasons"] = dict(Counter(ftr(r) for r in assessed if ft(r) == "exclude"))
    c["ft_pending"] = sum(1 for r in sought if ft(r) not in ("include", "exclude"))
    c["included"] = sum(1 for r in assessed if ft(r) == "include")
    c["included_with_pdf"] = sum(1 for r in assessed if ft(r) == "include" and p.has_pdf(r["id"]))
    decided = c["ta_excluded"] + c["sought"]
    c["progress_ta"] = round(100 * decided / c["screened"], 1) if c["screened"] else 0
    c["progress_ft"] = round(100 * (c["sought"] - c["ft_pending"]) / c["sought"], 1) if c["sought"] else 0
    return c


# ---------------------------------------------------------------- flow diagram (SVG)
def _wrap(text, width):
    out = []
    for para in text.split("\n"):
        line = ""
        for w in para.split():
            if len(line) + len(w) + 1 > width and line:
                out.append(line)
                line = w
            else:
                line = (line + " " + w).strip()
        out.append(line)
    return out


def _boxes(c):
    src = "\n".join(f"{k} (n = {v})" for k, v in c["sources"].items()) or "Databases (n = 0)"
    reasons = lambda dct: "\n".join(f"{k} (n = {v})" for k, v in sorted(dct.items(), key=lambda kv: -kv[1]))
    L = [
        ("Identification", f"Records identified from:\n{src}",
         f"Records removed before screening:\nDuplicate records removed (n = {c['duplicates']})\n"
         f"Records marked as ineligible by automation tools (n = {c['automation']})"),
        ("Screening", f"Records screened\n(n = {c['screened']})", f"Records excluded\n(n = {c['ta_excluded']})"),
        ("", f"Reports sought for retrieval\n(n = {c['sought']})", f"Reports not retrieved\n(n = {c['not_retrieved']})"),
        ("", f"Reports assessed for eligibility\n(n = {c['assessed']})",
         f"Reports excluded:\n{reasons(c['ft_excluded_reasons'])}" if c["ft_excluded_reasons"] else "Reports excluded\n(n = 0)"),
        ("Included", f"Studies included in review\n(n = {c['included']})", None),
    ]
    return L


def svg(c, pending_note=True):
    W, colx, colw, gap, lh, pad = 760, 70, 300, 50, 16, 10
    rx = colx + colw + gap
    rows, y = [], 20
    parts = []
    for phase, left, right in _boxes(c):
        ll, rl = _wrap(left, 40), (_wrap(right, 40) if right else [])
        h = max(len(ll), len(rl)) * lh + 2 * pad
        rows.append((phase, ll, rl, y, h))
        y += h + 34
    H = y + (40 if pending_note else 0)
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
                 f'font-family="Helvetica, Arial, sans-serif" font-size="12.5">')
    parts.append('<defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
                 '<path d="M0,0 L8,4 L0,8 z" fill="#333"/></marker></defs><rect width="100%" height="100%" fill="#fff"/>')

    def box(x, yy, w, h, lines, fill):
        s = [f'<rect x="{x}" y="{yy}" width="{w}" height="{h}" rx="3" fill="{fill}" stroke="#333"/>']
        for i, t in enumerate(lines):
            s.append(f'<text x="{x + pad}" y="{yy + pad + 12 + i * lh}" fill="#111">{escape(t)}</text>')
        return "".join(s)

    # phase bands
    groups = {}
    for phase, ll, rl, yy, h in rows:
        key = phase or list(groups)[-1]
        g = groups.setdefault(key, [yy, yy + h])
        g[1] = yy + h
    for name, (y0, y1) in groups.items():
        parts.append(f'<rect x="10" y="{y0}" width="40" height="{y1 - y0}" rx="3" fill="#cfe0f1" stroke="#333"/>')
        cy = (y0 + y1) / 2
        parts.append(f'<text x="30" y="{cy}" transform="rotate(-90 30 {cy})" text-anchor="middle" '
                     f'font-weight="bold">{escape(name)}</text>')
    for i, (phase, ll, rl, yy, h) in enumerate(rows):
        parts.append(box(colx, yy, colw, h, ll, "#fff"))
        if rl:
            parts.append(box(rx, yy, colw + 40, h, rl, "#fff"))
            parts.append(f'<line x1="{colx + colw}" y1="{yy + h / 2}" x2="{rx - 2}" y2="{yy + h / 2}" '
                         f'stroke="#333" marker-end="url(#a)"/>')
        if i + 1 < len(rows):
            ny = rows[i + 1][3]
            parts.append(f'<line x1="{colx + colw / 2}" y1="{yy + h}" x2="{colx + colw / 2}" y2="{ny - 2}" '
                         f'stroke="#333" marker-end="url(#a)"/>')
    if pending_note and (c["ta_pending"] or c["ft_pending"]):
        parts.append(f'<text x="{colx}" y="{H - 16}" fill="#a33">Screening not finished: {c["ta_pending"]} records awaiting '
                     f'title/abstract decision, {c["ft_pending"]} reports awaiting full-text decision.</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------- TikZ
def _tex(s):
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("_", r"\_"), ("#", r"\#"),
                 ("$", r"\$"), ("{", r"\{"), ("}", r"\}")):
        s = s.replace(a, b)
    return s


def tikz(c):
    b = _boxes(c)
    t = lambda s: r" \\ ".join(_tex(x) for x in s.split("\n"))
    out = [r"% PRISMA 2020 flow diagram - generated by Survey Screener",
           r"% \usepackage{tikz} \usetikzlibrary{positioning,arrows.meta}",
           r"\begin{tikzpicture}[node distance=7mm and 12mm, >={Stealth[length=2mm]},",
           r"  box/.style={draw, align=left, text width=62mm, inner sep=5pt, font=\footnotesize},",
           r"  phase/.style={draw, fill=blue!12, font=\footnotesize\bfseries, rotate=90, minimum height=6mm}]"]
    names = ["id", "scr", "sought", "ass", "inc"]
    for i, (phase, left, right) in enumerate(b):
        pos = "" if i == 0 else f", below=of {names[i - 1]}"
        out.append(rf"\node[box{pos}] ({names[i]}) {{{t(left)}}};")
        if right:
            out.append(rf"\node[box, right=of {names[i]}] ({names[i]}x) {{{t(right)}}};")
            out.append(rf"\draw[->] ({names[i]}) -- ({names[i]}x);")
        if i:
            out.append(rf"\draw[->] ({names[i - 1]}) -- ({names[i]});")
    out.append(r"\end{tikzpicture}")
    return "\n".join(out)


# ---------------------------------------------------------------- tables / text
def screening_csv(p):
    d = p.data["decisions"]
    f = io.StringIO()
    w = csv.writer(f, delimiter=";")
    w.writerow(["id", "source", "year", "doi", "title", "duplicate_of", "ta_decision", "ta_reason", "ta_automation",
                "ft_decision", "ft_reason", "full_text", "note"])
    for r in p.records:
        x = d.get(r["id"], {})
        w.writerow([r["id"], r.get("source", ""), r["year"], r["doi"], r["title"], r.get("dup_of", ""),
                    x.get("ta", ""), x.get("ta_reason", ""), "yes" if x.get("ta_auto") else "",
                    x.get("ft", ""), x.get("ft_reason", ""), "yes" if p.has_pdf(r["id"]) else "", x.get("note", "")])
    return "﻿" + f.getvalue()


def included_bib(p):
    d = p.data["decisions"]
    out = []
    for r in p.records:
        if d.get(r["id"], {}).get("ft") != "include":
            continue
        f = OrderedDict(title=r["title"], author=" and ".join(r["authors"]), year=r["year"],
                        journal=r["venue"], doi=r["doi"], url=r.get("url", ""))
        body = ",\n".join(f"  {k} = {{{v}}}" for k, v in f.items() if v)
        out.append(f"@article{{{r['id']},\n{body}\n}}")
    return "\n\n".join(out) + "\n"


def methods_text(p, c):
    srcs = ", ".join(f"{k} (n = {v})" for k, v in c["sources"].items())
    tar = "; ".join(f"{k.lower()}: {v}" for k, v in sorted(c["ta_excluded_reasons"].items(), key=lambda kv: -kv[1]))
    ftr = "; ".join(f"{k.lower()}: {v}" for k, v in sorted(c["ft_excluded_reasons"].items(), key=lambda kv: -kv[1]))
    inc = "; ".join(p.data["terms"]["include"]) or "—"
    exc = "; ".join(p.data["terms"]["exclude"]) or "—"
    txt = (f"The search identified {c['identified']} records ({srcs}). After removing {c['duplicates']} duplicates"
           + (f" and {c['automation']} records flagged as ineligible by automated keyword screening (exclusion terms: {exc})"
              if c["automation"] else "")
           + f", {c['screened']} records were screened on title and abstract, of which {c['ta_excluded']} were excluded"
           + (f" ({tar})" if tar else "") + f". Full texts were sought for {c['sought']} reports; "
           f"{c['not_retrieved']} could not be retrieved. Of the {c['assessed']} reports assessed for eligibility, "
           f"{c['ft_excluded']} were excluded" + (f" ({ftr})" if ftr else "")
           + f", leaving {c['included']} studies included in the review.")
    if c["ta_pending"] or c["ft_pending"]:
        txt += (f"\n\n[NOTE: screening is not finished — {c['ta_pending']} records await title/abstract screening and "
                f"{c['ft_pending']} reports await full-text assessment. Numbers above will change.]")
    txt += f"\n\nInclusion search terms used to support screening: {inc}."
    return txt
