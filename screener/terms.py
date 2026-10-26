"""Search terms.

A term is matched case-insensitively on whole words. Syntax:
    underwater          word / phrase ("object detection")
    fish*               prefix wildcard (fish, fishes, fishery ...)
    /sonar|acoustic/    raw regular expression
"""
import re

_cache = {}


def compile_term(t):
    t = (t or "").strip()
    if t in _cache:
        return _cache[t]
    if len(t) > 2 and t.startswith("/") and t.endswith("/"):
        try:
            rx = re.compile(t[1:-1], re.I)
        except re.error:
            rx = re.compile(re.escape(t[1:-1]), re.I)
    else:
        parts = [re.escape(p).replace(r"\*", r"\w*") for p in t.split()]
        rx = re.compile(r"(?<!\w)" + r"[\s\-]+".join(parts) + r"(?!\w)", re.I)
    _cache[t] = rx
    return rx


def hits(terms, *texts):
    blob = " ".join(x for x in texts if x)
    return [t for t in terms if t and compile_term(t).search(blob)]


def record_text(r):
    return " ".join([r.get("title", ""), r.get("abstract", ""), " ".join(r.get("keywords", []))])
