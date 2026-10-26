"""Full-text (PDF) retrieval and text extraction.

Order per record: open-access PDF (OpenAlex / Unpaywall) -> publisher patterns -> the
citation_pdf_url on the DOI landing page -> optionally a real Chrome/Edge window (Playwright)
that uses your own (institutional) login. Run it on your university network/VPN to use
subscriptions. Only records included at title/abstract stage are fetched by default.
"""
import html
import os
import re
import subprocess
import time
import urllib.parse

from . import net

DIRECT = {
    "10.1007": lambda d: f"https://link.springer.com/content/pdf/{d}.pdf",
    "10.1038": lambda d: f"https://www.nature.com/articles/{d.split('/', 1)[1]}.pdf",
    "10.1049": lambda d: f"https://ietresearch.onlinelibrary.wiley.com/doi/pdfdirect/{d}",
    "10.1002": lambda d: f"https://onlinelibrary.wiley.com/doi/pdfdirect/{d}",
    "10.1111": lambda d: f"https://onlinelibrary.wiley.com/doi/pdfdirect/{d}",
    "10.1145": lambda d: f"https://dl.acm.org/doi/pdf/{d}",
    "10.1088": lambda d: f"https://iopscience.iop.org/article/{d}/pdf",
}
IEEE = ("10.1109", "10.23919")


# ---------------------------------------------------------------- text extraction
def pdf_to_text(path):
    try:
        o = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, timeout=120)
        if o.returncode == 0 and o.stdout.strip():
            return o.stdout
    except Exception:
        pass
    try:
        from pypdf import PdfReader
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(path).pages)
    except Exception:
        return ""


def ensure_text(project, rid):
    """Extract and cache full text for a record that has a PDF. Returns the text ('' if none)."""
    tp, pp = project.text_path(rid), project.pdf_path(rid)
    if os.path.exists(tp) and (not os.path.exists(pp) or os.path.getmtime(tp) >= os.path.getmtime(pp)):
        return open(tp, encoding="utf-8", errors="replace").read()
    if not os.path.exists(pp):
        return ""
    t = pdf_to_text(pp)
    t = re.split(r"\n\s*(References|REFERENCES|Bibliography)\s*\n", t)[0]     # drop reference list
    t = re.sub(r"-\n(\w)", r"\1", t)
    t = re.sub(r"\s+", " ", t)
    open(tp, "w", encoding="utf-8").write(t)
    return t


# ---------------------------------------------------------------- plain HTTP
def candidates(r, email):
    d = urllib.parse.quote(r["doi"], safe="/")
    if r.get("oa_pdf"):
        yield "open access (OpenAlex)", r["oa_pdf"], None
    if email:
        s, j = net.get_json(f"https://api.unpaywall.org/v2/{d}?email={urllib.parse.quote(email)}", delay=0.2)
        for loc in ((j or {}).get("oa_locations") or []):
            if loc.get("url_for_pdf"):
                yield "open access (Unpaywall)", loc["url_for_pdf"], None
    prefix = r["doi"].split("/")[0]
    if prefix in DIRECT:
        yield "publisher", DIRECT[prefix](d), None
    s, landing, body, _ = net.get("https://doi.org/" + d, accept="text/html")
    if body.startswith(b"%PDF"):
        yield "doi", landing, None
    m = re.search(r"ieeexplore\.ieee\.org/(?:abstract/)?document/(\d+)", landing)
    if m:
        yield "IEEE", f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={m.group(1)}", landing
    text = body[:600_000].decode("utf-8", "replace")
    for mm in re.finditer(r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]*>', text, re.I):
        c = re.search(r'content=["\']([^"\']+)', mm.group(0))
        if c:
            yield "citation_pdf_url", urllib.parse.urljoin(landing, html.unescape(c.group(1))), landing


def fetch_http(r, dest, email):
    tried = []
    for src, url, ref in candidates(r, email):
        if url in tried:
            continue
        tried.append(url)
        s, final, body, _ = net.get(url, accept="application/pdf,*/*;q=0.8", referer=ref)
        if body.startswith(b"%PDF"):
            open(dest, "wb").write(body)
            return True, src
    return False, f"no PDF via {len(tried)} URL(s)"


# ---------------------------------------------------------------- browser (Playwright)
class Browser:
    """A real Chrome/Edge window with a persistent profile, so your institutional logins
    (e.g. IEEE Xplore 'Institutional Sign In') are reused between runs."""

    def __init__(self, profile, channel="chrome", ctl=None):
        from playwright.sync_api import sync_playwright
        self.ctl = ctl
        self.pw = sync_playwright().start()
        last = None
        for ch in [channel, "msedge", "chrome", None]:
            try:
                self.ctx = self.pw.chromium.launch_persistent_context(
                    profile, channel=ch, headless=False, accept_downloads=True, viewport={"width": 1200, "height": 900})
                break
            except Exception as e:
                last = e
        else:
            self.pw.stop()
            raise RuntimeError(f"Could not start a browser ({last}). Install Chrome or run: python -m playwright install chromium")
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.ieee_blocked = False

    def close(self):
        try:
            self.ctx.close()
            self.pw.stop()
        except Exception:
            pass

    def _goto(self, url):
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        for _ in range(30):            # wait for Cloudflare-style checks
            t = ""
            try:
                t = (self.page.title() or "").lower()
            except Exception:
                pass
            if not any(k in t for k in ("just a moment", "attention required", "checking your browser")):
                break
            time.sleep(1)

    def _req(self, url, referer):
        try:
            return self.ctx.request.get(url, headers={"Referer": referer}, timeout=90000).body()
        except Exception:
            return b""

    def fetch_ieee(self, r, dest):
        if self.ieee_blocked:
            return False, "IEEE concurrency limit reached earlier in this run"
        self._goto("https://doi.org/" + urllib.parse.quote(r["doi"], safe="/"))
        m = re.search(r"/document/(\d+)", self.page.url)
        if not m:
            return False, "IEEE: no document number"
        arn = m.group(1)
        landing = f"https://ieeexplore.ieee.org/document/{arn}"
        urls = [f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={arn}&ref="]
        stamp = self._req(f"https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber={arn}", landing)
        for src in re.findall(rb'<iframe[^>]+src="([^"]+)"', stamp or b""):
            urls.append(urllib.parse.urljoin("https://ieeexplore.ieee.org/", html.unescape(src.decode("utf-8", "replace"))))
        for u in urls:
            body = self._req(u, landing)
            if body.startswith(b"%PDF"):
                open(dest, "wb").write(body)
                return True, "browser (IEEE login)"
            if b"concurrency limit" in body[:200000].lower():
                self.ieee_blocked = True
                if self.ctl:
                    self.ctl.log("IEEE: 'institution concurrency limit reached' — skipping IEEE for the rest of "
                                 "this run. Close other IEEE sessions and try again later.")
                return False, "IEEE concurrency limit"
        return False, "IEEE: no PDF (not signed in in the browser window?)"

    def fetch(self, r, dest):
        if r["doi"].split("/")[0] in IEEE:
            return self.fetch_ieee(r, dest)
        d = urllib.parse.quote(r["doi"], safe="/")
        try:
            self._goto("https://doi.org/" + d)
            self.page.wait_for_load_state("load", timeout=20000)
        except Exception:
            pass
        try:
            landing = self.page.url
            cands = self.page.eval_on_selector_all('meta[name="citation_pdf_url"]', "e => e.map(x => x.content)")
            cands = self.page.eval_on_selector_all('a.UD_ArticlePDF', "e => e.map(x => x.href)") + cands
            cands += self.page.eval_on_selector_all('a[href*=".pdf"], a[href$="/pdf"], a[href*="/pdf/"]',
                                                    "e => e.map(x => x.href)")[:3]
        except Exception:
            return False, "browser: page could not be read"
        prefix = r["doi"].split("/")[0]
        if prefix in DIRECT:
            cands.append(DIRECT[prefix](d))
        if prefix == "10.3390":
            cands.append(landing.rstrip("/") + "/pdf")
        seen = set()
        for u in cands:
            u = urllib.parse.urljoin(landing, u)
            if u in seen:
                continue
            seen.add(u)
            body = self._req(u, landing)
            if body.startswith(b"%PDF"):
                open(dest, "wb").write(body)
                return True, "browser"
            try:                      # forced downloads (MDPI etc.)
                with self.page.expect_download(timeout=15000) as dl:
                    try:
                        self.page.goto(u, wait_until="commit", timeout=30000)
                    except Exception:
                        pass
                tmp = dest + ".part"
                dl.value.save_as(tmp)
                if open(tmp, "rb").read(4) == b"%PDF":
                    os.replace(tmp, dest)
                    return True, "browser (download)"
                os.remove(tmp)
            except Exception:
                pass
        return False, f"browser: no PDF on {urllib.parse.urlparse(landing).netloc}"


# ---------------------------------------------------------------- job
def run(project, ctl, scope="ta_included", retry_failed=False, max_n=0):
    s = project.data["settings"]
    dec = project.data["decisions"]
    recs = [r for r in project.records if not r.get("dup_of") and r["doi"] and not project.has_pdf(r["id"])]
    if scope == "ta_included":
        recs = [r for r in recs if dec.get(r["id"], {}).get("ta") == "include"]
    elif scope == "not_excluded":
        recs = [r for r in recs if dec.get(r["id"], {}).get("ta") != "exclude"]
    if not retry_failed:
        recs = [r for r in recs if not r.get("pdf_failed")]
    if max_n:
        recs = recs[:max_n]
    ctl.log(f"{len(recs)} records to fetch (scope: {scope}{', retrying failed' if retry_failed else ''})")
    browser, n_ok = None, 0
    try:
        if s.get("browser"):
            try:
                browser = Browser(os.path.join(project.folder, "browser_profile"), s.get("browser_channel", "chrome"), ctl)
                ctl.log("Browser window opened. Sign in to sites that need it (e.g. IEEE Xplore -> Institutional "
                        "Sign In) — the login is kept in the project's browser profile.")
            except Exception as e:
                ctl.log(f"Browser not available: {e}")
        for i, r in enumerate(recs, 1):
            if ctl.stopped:
                break
            ctl.progress(i, len(recs), r["id"])
            dest = project.pdf_path(r["id"])
            ok, how = fetch_http(r, dest, s.get("email", ""))
            if not ok and browser:
                try:
                    ok, how2 = browser.fetch(r, dest)
                    how = how2 if ok else f"{how}; {how2}"
                except Exception as e:
                    how += f"; browser error {type(e).__name__}"
            if ok:
                n_ok += 1
                r.pop("pdf_failed", None)
                r["pdf_source"] = how
                ensure_text(project, r["id"])
                ctl.log(f"{r['id']}: OK ({how})")
            else:
                r["pdf_failed"] = how
                ctl.log(f"{r['id']}: not found — {how}")
            if i % 10 == 0:
                project.save()
    finally:
        if browser:
            browser.close()
    project.log(f"PDF download: {n_ok} of {len(recs)} retrieved")
    project.save()
    ctl.log(f"Done — {n_ok} of {len(recs)} PDFs retrieved.")
