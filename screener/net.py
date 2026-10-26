"""Small HTTP helpers (standard library only)."""
import time
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))
_last = {}


def get(url, accept="*/*", referer=None, timeout=45, delay=1.0, maxbytes=60_000_000):
    """GET with a polite per-host delay. Returns (status, final_url, body_bytes, content_type)."""
    host = urllib.parse.urlparse(url).netloc
    wait = _last.get(host, 0) + delay - time.time()
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.time()
    h = {"User-Agent": UA, "Accept": accept, "Accept-Language": "en"}
    if referer:
        h["Referer"] = referer
    try:
        with _opener.open(urllib.request.Request(url, headers=h), timeout=timeout) as r:
            return r.status, r.geturl(), r.read(maxbytes), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, url, b"", ""
    except Exception as e:
        return 0, url, b"", type(e).__name__


def get_json(url, **kw):
    import json
    s, _, b, _ = get(url, accept="application/json", **kw)
    if s != 200:
        return s, None
    try:
        return s, json.loads(b)
    except Exception:
        return s, None
