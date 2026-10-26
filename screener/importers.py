"""Import bibliographic exports: RIS (.ris), BibTeX (.bib) and EndNote XML (.xml).

Every parser returns a list of plain dicts with the same keys:
    title, authors (list), year, venue, doi, abstract, keywords (list), url, type
"""
import html
import re
import xml.etree.ElementTree as ET

FIELDS = ("title", "authors", "year", "venue", "doi", "abstract", "keywords", "url", "type")


def blank():
    return {"title": "", "authors": [], "year": "", "venue": "", "doi": "", "abstract": "",
            "keywords": [], "url": "", "type": "", "orig_id": ""}


def norm_doi(d):
    d = (d or "").strip()
    d = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", d, flags=re.I)
    d = re.sub(r"^doi:\s*", "", d, flags=re.I)
    return d.strip().rstrip(".").lower()


def clean(s):
    s = html.unescape(s or "")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def year_of(s):
    m = re.search(r"(1[89]\d\d|20\d\d)", s or "")
    return m.group(1) if m else ""


# ---------------------------------------------------------------- RIS
RIS_LINE = re.compile(r"^([A-Z][A-Z0-9])  -\s?(.*)$")


def parse_ris(text):
    out, cur, last = [], None, None
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        m = RIS_LINE.match(line)
        if not m:
            if cur is not None and last and line.strip():       # continuation line
                cur.setdefault(last, [""])
                cur[last][-1] += " " + line.strip()
            continue
        tag, val = m.group(1), m.group(2).strip()
        if tag == "TY":
            cur, last = {"TY": [val]}, "TY"
            continue
        if cur is None:
            continue
        if tag == "ER":
            out.append(_ris_record(cur))
            cur, last = None, None
            continue
        cur.setdefault(tag, []).append(val)
        last = tag
    if cur:
        out.append(_ris_record(cur))
    return out


def _ris_record(t):
    g = lambda *tags: next((t[k][0] for k in tags if t.get(k) and t[k][0]), "")
    r = blank()
    r["type"] = g("TY")
    r["orig_id"] = g("ID")
    r["title"] = clean(g("TI", "T1", "CT"))
    r["authors"] = [clean(a) for k in ("AU", "A1", "A2") for a in t.get(k, []) if a][:50]
    r["year"] = year_of(g("PY", "Y1", "DA", "Y2"))
    r["venue"] = clean(g("T2", "JO", "JF", "JA", "BT", "T3", "PB"))
    r["doi"] = norm_doi(g("DO", "DI"))
    if not r["doi"]:
        for u in t.get("UR", []) + t.get("L2", []):
            m = re.search(r"doi\.org/(10\.\S+)", u)
            if m:
                r["doi"] = norm_doi(m.group(1))
                break
    r["abstract"] = clean(" ".join(t.get("AB", []) or t.get("N2", [])))
    r["keywords"] = [clean(k) for k in t.get("KW", []) if k]
    r["url"] = g("UR", "L2")
    return r


# ---------------------------------------------------------------- BibTeX
def _read_braced(s, i):
    """s[i] is '{' or '"'; return (value, index after it)."""
    if s[i] == '"':
        j, depth = i + 1, 0
        while j < len(s):
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
            elif s[j] == '"' and depth == 0:
                return s[i + 1:j], j + 1
            j += 1
        return s[i + 1:], len(s)
    depth, j = 0, i
    while j < len(s):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    return s[i + 1:], len(s)


LATEX = {r"\&": "&", r"\%": "%", r"\_": "_", r"\$": "$", "--": "–", r"\textendash": "–", "~": " "}


def unlatex(s):
    s = re.sub(r"\\[`'^\"~=.uvHcdbtk]\{?\\?([A-Za-z])\}?", r"\1", s)     # accents -> base letter
    for k, v in LATEX.items():
        s = s.replace(k, v)
    s = re.sub(r"\\(emph|textit|textbf|mathrm|text)\{([^}]*)\}", r"\2", s)
    return clean(s.replace("{", "").replace("}", ""))


def parse_bib(text):
    out, i = [], 0
    while True:
        m = re.compile(r"@(\w+)\s*[{(]", re.S).search(text, i)
        if not m:
            break
        typ = m.group(1).lower()
        start = m.end()
        # find end of entry via brace matching from the opening brace
        val, end = _read_braced(text, m.end() - 1) if text[m.end() - 1] == "{" else (text[start:], len(text))
        i = end
        if typ in ("comment", "string", "preamble"):
            continue
        body = val.split(",", 1)[1] if "," in val else ""
        fields, j = {}, 0
        while j < len(body):
            fm = re.compile(r"\s*([\w\-:]+)\s*=\s*", re.S).match(body, j)
            if not fm:
                nxt = body.find(",", j)
                if nxt < 0:
                    break
                j = nxt + 1
                continue
            key = fm.group(1).lower()
            j = fm.end()
            if j < len(body) and body[j] in "{\"":
                v, j = _read_braced(body, j)
            else:
                vm = re.compile(r"[^,]*").match(body, j)
                v, j = vm.group(0), vm.end()
            fields[key] = v.strip()
            nxt = body.find(",", j)
            j = len(body) if nxt < 0 else nxt + 1
        r = blank()
        r["type"] = typ
        r["orig_id"] = val.split(",", 1)[0].strip()
        r["title"] = unlatex(fields.get("title", ""))
        r["authors"] = [unlatex(a) for a in re.split(r"\s+and\s+", fields.get("author", "")) if a.strip()][:50]
        r["year"] = year_of(fields.get("year", "") or fields.get("date", ""))
        r["venue"] = unlatex(fields.get("journal") or fields.get("booktitle") or fields.get("publisher") or "")
        r["doi"] = norm_doi(unlatex(fields.get("doi", "")))
        r["abstract"] = unlatex(fields.get("abstract", ""))
        r["keywords"] = [unlatex(k) for k in re.split(r"[;,]", fields.get("keywords", "")) if k.strip()]
        r["url"] = unlatex(fields.get("url", ""))
        out.append(r)
    return out


# ---------------------------------------------------------------- EndNote XML
def fix_mojibake(t):
    if "\u00e2\u20ac" in t or "\u00c3" in t:
        try:
            return t.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return t


def parse_endnote_xml(text):
    """Supports both EndNote XML flavours:
       <xml><records><record> (EndNote desktop 'XML' export) and
       <endnotefusion><reference> with short tags (t1, a1, yr, ab, do ...).
    Large exports are often several XML documents glued together and may contain control
    characters that XML forbids; both are handled."""
    text = text.lstrip("\ufeff")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    text = re.sub(r"<\?xml[^>]*\?>", "", text)
    text = re.sub(r"<!DOCTYPE[^>]*>", "", text)
    text = re.sub(r"</?(?:endnotefusion|xml|records)\b[^>]*>", "", text)
    root = ET.fromstring("<exports>" + text + "</exports>")

    def txt(e):
        return fix_mojibake(clean("".join(e.itertext()))) if e is not None else ""

    out = []
    for rec in root.iter("record"):
        r = blank()
        r["title"] = txt(rec.find("titles/title"))
        r["authors"] = [txt(a) for a in rec.findall("contributors/authors/author")][:50]
        r["year"] = year_of(txt(rec.find("dates/year")))
        r["venue"] = txt(rec.find("titles/secondary-title")) or txt(rec.find("periodical/full-title"))
        r["doi"] = norm_doi(txt(rec.find("electronic-resource-num")))
        r["abstract"] = txt(rec.find("abstract"))
        r["keywords"] = [txt(k) for k in rec.findall("keywords/keyword")]
        r["url"] = txt(rec.find("urls/related-urls/url"))
        r["orig_id"] = txt(rec.find("rec-number"))
        rt = rec.find("ref-type")
        r["type"] = rt.get("name", "") if rt is not None else ""
        out.append(r)
    for ref in root.iter("reference"):
        g = lambda k: txt(ref.find(k))
        r = blank()
        r["type"] = g("rt")
        r["orig_id"] = g("id")
        r["title"] = g("t1") or g("ti")
        r["authors"] = [txt(a) for a in ref.findall("a1")][:50]
        r["year"] = year_of(g("yr"))
        r["venue"] = g("jf") or g("jo") or g("t2")
        r["doi"] = norm_doi(g("do"))
        r["abstract"] = g("ab")
        r["keywords"] = [txt(k) for k in ref.findall("k1")]
        r["url"] = g("ul") or g("lk")
        out.append(r)
    return out


def parse_any(filename, text):
    name = (filename or "").lower()
    head = text.lstrip()[:200]
    if name.endswith(".bib") or head.startswith("@"):
        return "bibtex", parse_bib(text)
    if name.endswith(".xml") or head.startswith("<"):
        return "endnote-xml", parse_endnote_xml(text)
    if name.endswith((".ris", ".txt")) or re.search(r"^TY  -", text, re.M):
        return "ris", parse_ris(text)
    raise ValueError("Unknown file format - use .ris, .bib or EndNote .xml")
