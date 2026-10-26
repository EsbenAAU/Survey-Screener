/* Survey Screener — front end (vanilla JS, no build step). */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const S = {slug: null, P: null, view: "setup", tab: "ta", q: "", pdf: "", hit: "", sort: "default", shown: 40, sel: 0, open: new Set(), poll: null};

async function api(path, opt = {}) {
  const o = {method: opt.method || (opt.body !== undefined ? "POST" : "GET"), headers: {}};
  if (opt.body !== undefined) {
    if (opt.raw) { o.body = opt.body; o.headers["Content-Type"] = "application/octet-stream"; }
    else { o.body = JSON.stringify(opt.body); o.headers["Content-Type"] = "application/json"; }
  }
  const r = await fetch("/api/" + path, o);
  const ct = r.headers.get("Content-Type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.error) || r.statusText);
  return data;
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 2600); }
const P = () => S.P;
const dec = id => P().decisions[id] || {};

/* ------------------------------------------------------------ routing */
window.addEventListener("hashchange", route);
async function route() {
  const m = location.hash.match(/^#\/p\/([^/]+)\/?(\w+)?/);
  if (!m) { S.slug = null; S.P = null; return home(); }
  if (S.slug !== m[1] || !S.P) { S.slug = m[1]; await load(); }
  S.view = m[2] || "setup";
  render();
}
async function load() {
  S.P = await api("project/" + S.slug);
  $("#pname").textContent = S.P.name;
}
function nav() {
  if (!S.slug) { $("#nav").innerHTML = ""; $("#pname").textContent = ""; return; }
  const c = P().counts;
  const items = [["setup", "1 · Import & terms"], ["screen", `2 · Screen <span class="mut">(${c.ta_pending + c.ft_pending})</span>`], ["prisma", "3 · PRISMA & export"]];
  $("#nav").innerHTML = items.map(([k, l]) => `<a href="#/p/${S.slug}/${k}" class="${S.view === k ? "on" : ""}">${l}</a>`).join("");
}
function render() {
  nav();
  if (S.view === "screen") return screen();
  if (S.view === "prisma") return prismaView();
  return setup();
}

/* ------------------------------------------------------------ home */
async function home() {
  nav();
  const list = await api("projects");
  if (S.slug) return;                       // user navigated away while loading
  $("#app").innerHTML = `
  <h1>Review projects</h1>
  <p class="mut">A local helper for the record selection of survey / systematic reviews: import your search results,
  screen titles and abstracts, retrieve full texts, and export a PRISMA 2020 flow diagram and screening record.</p>
  <div class="panel"><h3>New project</h3><div class="row">
    <input type="text" id="newname" placeholder="e.g. Underwater datasets survey" style="min-width:320px">
    <button class="pri" id="create">Create</button></div></div>
  <div class="panel"><h3>Existing projects</h3>${list.length ? `<table><tr><th>Name</th><th>Records</th><th>Created</th></tr>
    ${list.map(p => `<tr><td><a href="#/p/${p.slug}/screen">${esc(p.name)}</a></td><td class="n">${p.records}</td><td class="mut">${esc(p.created.slice(0, 10))}</td></tr>`).join("")}</table>`
    : `<p class="mut">No projects yet.</p>`}</div>`;
  $("#create").onclick = async () => {
    const r = await api("projects", {body: {name: $("#newname").value}});
    location.hash = `#/p/${r.slug}/setup`;
  };
}

/* ------------------------------------------------------------ setup */
function setup() {
  const p = P(), c = p.counts, st = p.settings;
  const uniq = p.records.filter(r => !r.dup_of);
  const noAbs = uniq.filter(r => (r.abstract || "").length < 100 && dec(r.id).ta !== "exclude").length;
  const pdfN = uniq.filter(r => r.has_pdf).length;
  $("#app").innerHTML = `
  <h1>${esc(p.name)}</h1>
  <div class="grid2">
   <div class="panel"><h3>Import search results</h3>
    <p class="small mut">RIS (.ris), BibTeX (.bib) or EndNote XML (.xml) — exported from Scopus, Web of Science, IEEE Xplore,
    Zotero, Mendeley, RefWorks, EndNote … Give each file the name of the database it came from; that name is used as
    the source in the PRISMA diagram. Duplicates (same DOI, or same title + year) are flagged automatically.</p>
    <div class="row" style="margin-bottom:8px"><input type="text" id="srclabel" placeholder="Source / database name, e.g. Scopus" style="flex:1"></div>
    <div class="drop" id="drop">Drop files here or <label class="btn">choose files<input type="file" id="file" multiple accept=".ris,.bib,.xml,.txt" hidden></label></div>
    ${p.sources.length ? `<table style="margin-top:12px"><tr><th>Source</th><th>File</th><th>Records</th><th>Duplicates</th></tr>
     ${p.sources.map(s => `<tr><td>${esc(s.label)}</td><td class="mut small">${esc(s.file)}</td><td class="n">${s.n}</td><td class="n">${s.duplicates}</td></tr>`).join("")}
     <tr><td><b>Total</b></td><td></td><td class="n"><b>${c.identified}</b></td><td class="n"><b>${c.duplicates}</b></td></tr></table>` : ""}
    <details style="margin-top:12px"><summary class="small">Import decisions from an earlier screening</summary>
     <p class="small mut">A Survey Screener <code>project.json</code>, or <code>umod_decisions.json</code> from the earlier review page.
     Records are matched by DOI / original id; decisions already made here are kept.</p>
     <label class="btn">Choose file<input type="file" id="decfile" accept=".json" hidden></label> <span id="decinfo" class="small mut"></span></details>
   </div>
   <div class="panel"><h3>Search terms</h3>
    <p class="small mut">One term per line. Matching is case-insensitive on whole words; <code>fish*</code> matches word
    starts, <code>/sonar|acoustic/</code> is a regular expression. Inclusion terms are highlighted and can be used to sort
    and filter. Exclusion terms are highlighted in red and can auto-exclude records (reported in PRISMA as
    "records marked as ineligible by automation tools").</p>
    <div class="grid2" style="gap:10px"><div><b class="small">Inclusion terms</b><textarea id="tinc">${esc(p.terms.include.join("\n"))}</textarea></div>
     <div><b class="small">Exclusion terms</b><textarea id="texc">${esc(p.terms.exclude.join("\n"))}</textarea></div></div>
    <div class="row" style="margin-top:8px"><button class="pri" id="saveterms">Save terms</button>
     <label class="small"><input type="checkbox" id="protect" checked> don't auto-exclude records that also match an inclusion term</label></div>
    <div class="row" style="margin-top:8px"><button id="previewexc">Preview auto-exclusion</button><button class="exc" id="applyexc">Apply auto-exclusion</button>
     <button id="undoauto">Undo all auto-exclusions (${c.automation})</button></div>
    <div id="excinfo" class="small mut" style="margin-top:6px"></div>
   </div>
  </div>
  <div class="grid2">
   <div class="panel"><h3>Metadata & full texts</h3>
    <p class="small mut">${noAbs} records still lack an abstract · ${pdfN} of ${uniq.length} records have a PDF ·
     ${c.sought} records included at title/abstract stage (${c.sought_with_pdf} with PDF).</p>
    <div class="row"><button id="meta">Update metadata & abstracts</button>
     <label class="small"><input type="checkbox" id="metaall"> also records that already look complete</label></div>
    <p class="small mut">Fills empty fields from OpenAlex, Semantic Scholar, Crossref and IEEE Xplore. Existing values are kept.</p>
    <div class="row" style="margin-top:10px"><button id="pdf">Download PDFs</button>
     <select id="pdfscope"><option value="ta_included">for records included at title/abstract stage</option><option value="not_excluded">for all records not excluded</option></select>
     <label class="small"><input type="checkbox" id="pdfretry"> retry failed</label></div>
    <p class="small mut">Tries open-access copies, publisher links and the DOI landing page. Use your university network or VPN
    for subscription content, or enable the browser below. You can also drop a PDF onto any record on the Screen page.</p>
   </div>
   <div class="panel"><h3>Settings</h3>
    <div class="row"><label class="small" style="width:150px">E-mail (for APIs)</label><input type="email" id="email" value="${esc(st.email)}" style="flex:1" placeholder="you@university.edu"></div>
    <div class="row" style="margin-top:6px"><label class="small" style="width:150px">Use browser for PDFs</label>
     <input type="checkbox" id="browser" ${st.browser ? "checked" : ""}>
     <select id="channel">${["chrome", "msedge", "chromium"].map(x => `<option ${st.browser_channel === x ? "selected" : ""}>${x}</option>`).join("")}</select>
     <span class="small mut">needs <code>pip install playwright</code>; opens a window where you can sign in (e.g. IEEE institutional login)</span></div>
    <div class="grid2" style="gap:10px;margin-top:10px"><div><b class="small">Exclusion reasons — title/abstract</b><textarea id="rta" style="min-height:90px">${esc(st.reasons_ta.join("\n"))}</textarea></div>
     <div><b class="small">Exclusion reasons — full text</b><textarea id="rft" style="min-height:90px">${esc(st.reasons_ft.join("\n"))}</textarea>
     <span class="small mut">"${esc(p.not_retrieved_reason)}" is always available and is reported separately in PRISMA.</span></div></div>
    <button id="savesettings" style="margin-top:8px">Save settings</button>
   </div>
  </div>`;

  const doImport = async files => {
    for (const f of files) {
      const content = await f.text();
      try {
        const r = await api(`project/${S.slug}/import`, {body: {filename: f.name, content, label: $("#srclabel").value.trim()}});
        toast(`${f.name}: ${r.n} records (${r.duplicates} duplicates)`);
      } catch (e) { toast(`${f.name}: ${e.message}`); }
    }
    await load(); render();
  };
  $("#file").onchange = e => doImport(e.target.files);
  $("#decfile").onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    $("#decinfo").textContent = "Importing…";
    const r = await api(`project/${S.slug}/import-decisions`, {body: {content: await f.text()}});
    toast(`${r.imported} decisions imported, ${r.unmatched} not matched`); await load(); render();
  };
  const d = $("#drop");
  d.ondragover = e => { e.preventDefault(); d.classList.add("over"); };
  d.ondragleave = () => d.classList.remove("over");
  d.ondrop = e => { e.preventDefault(); d.classList.remove("over"); doImport(e.dataTransfer.files); };

  const saveTerms = async () => {
    await api(`project/${S.slug}/terms`, {body: {include: $("#tinc").value.split("\n"), exclude: $("#texc").value.split("\n")}});
    await load();
  };
  $("#saveterms").onclick = async () => { await saveTerms(); toast("Terms saved"); render(); };
  $("#previewexc").onclick = async () => {
    const protect = $("#protect").checked, info = $("#excinfo");
    info.textContent = "Counting…";
    await saveTerms();
    const r = await api(`project/${S.slug}/apply-exclusion-terms`, {body: {dry_run: true, protect_included_terms: protect}});
    info.innerHTML = `${r.n} undecided records would be auto-excluded: ` + Object.entries(r.by_term).map(([t, n]) => `<code>${esc(t)}</code> ${n}`).join(", ");
  };
  $("#applyexc").onclick = async () => {
    const protect = $("#protect").checked;
    $("#excinfo").textContent = "Applying…";
    await saveTerms();
    const r = await api(`project/${S.slug}/apply-exclusion-terms`, {body: {protect_included_terms: protect}});
    toast(`${r.n} records auto-excluded`); await load(); render();
  };
  $("#undoauto").onclick = async () => { const r = await api(`project/${S.slug}/undo-automation`, {body: {}}); toast(`${r.undone} auto-exclusions undone`); await load(); render(); };
  $("#savesettings").onclick = async () => {
    await api(`project/${S.slug}/settings`, {body: {email: $("#email").value.trim(), browser: $("#browser").checked, browser_channel: $("#channel").value,
      reasons_ta: $("#rta").value.split("\n").map(x => x.trim()).filter(Boolean), reasons_ft: $("#rft").value.split("\n").map(x => x.trim()).filter(Boolean)}});
    await load(); toast("Settings saved");
  };
  $("#meta").onclick = () => startJob("metadata", {all: $("#metaall").checked});
  $("#pdf").onclick = () => startJob("pdf", {scope: $("#pdfscope").value, retry: $("#pdfretry").checked});
}

/* ------------------------------------------------------------ jobs */
async function startJob(kind, body) {
  try { await api(`project/${S.slug}/job/${kind}`, {body}); } catch (e) { return toast(e.message); }
  pollJob();
}
async function pollJob() {
  clearTimeout(S.poll);
  if (!S.slug) return;
  const j = await api(`project/${S.slug}/job`);
  const box = $("#job");
  if (!j.kind) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const pct = j.n ? Math.round(100 * j.i / j.n) : 0;
  box.innerHTML = `<div class="hd"><b>${j.kind === "pdf" ? "PDF download" : "Metadata update"}</b>
    <span class="small mut">${j.running ? `${j.i}/${j.n} · ${esc(j.current)}` : (j.error ? "failed" : "finished")}</span>
    <span style="margin-left:auto"></span>${j.running ? `<button id="jstop">Stop</button>` : `<button id="jclose">Close</button>`}</div>
    <div class="bar" style="margin:0 14px"><i style="width:${pct}%"></i></div><pre>${esc(j.lines.slice(-40).join("\n"))}</pre>`;
  const pre = $("pre", box); pre.scrollTop = pre.scrollHeight;
  if (j.running) { $("#jstop").onclick = () => api(`project/${S.slug}/job/stop`, {body: {}}); S.poll = setTimeout(pollJob, 1500); }
  else {
    $("#jclose").onclick = () => box.classList.add("hidden");
    if (!box._done) { box._done = true; await load(); render(); }
  }
  if (j.running) box._done = false;
}

/* ------------------------------------------------------------ term highlighting */
function termRx(t) {
  t = t.trim();
  if (t.length > 2 && t.startsWith("/") && t.endsWith("/")) { try { return new RegExp(t.slice(1, -1), "gi"); } catch { } }
  const parts = t.split(/\s+/).map(x => x.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, "\\w*"));
  return new RegExp("(?<![\\w])" + parts.join("[\\s\\-]+") + "(?![\\w])", "gi");
}
function highlight(text) {
  let h = esc(text);
  const mark = (terms, cls) => terms.forEach(t => { if (!t.trim()) return; try { h = h.replace(termRx(t), m => `<mark${cls}>${m}</mark>`); } catch { } });
  mark(P().terms.include, ""); mark(P().terms.exclude, ' class="x"');
  return h;
}

/* ------------------------------------------------------------ screening */
const TABS = [
  ["ta", "To screen", r => !r.dup_of && !["include", "exclude", "maybe"].includes(dec(r.id).ta)],
  ["maybe", "Maybe", r => !r.dup_of && dec(r.id).ta === "maybe"],
  ["ft", "Full text", r => !r.dup_of && dec(r.id).ta === "include" && !["include", "exclude"].includes(dec(r.id).ft)],
  ["inc", "Included", r => !r.dup_of && dec(r.id).ta === "include" && dec(r.id).ft === "include"],
  ["exc", "Excluded", r => !r.dup_of && (dec(r.id).ta === "exclude" || dec(r.id).ft === "exclude")],
  ["all", "All", r => !r.dup_of],
  ["dup", "Duplicates", r => !!r.dup_of],
];
function filtered() {
  const tab = TABS.find(t => t[0] === S.tab) || TABS[0];
  const q = S.q.toLowerCase();
  let rs = P().records.filter(tab[2]);
  if (q) rs = rs.filter(r => (r.title + " " + r.abstract + " " + r.id + " " + (r.authors || []).join(" ") + " " + (r.keywords || []).join(" ") + " " + r.doi).toLowerCase().includes(q));
  if (S.pdf) rs = rs.filter(r => (S.pdf === "yes") === !!r.has_pdf);
  if (S.hit === "inc") rs = rs.filter(r => r.hits_inc.length || (r.hits_inc_ft || []).length);
  if (S.hit === "noinc") rs = rs.filter(r => !r.hits_inc.length && !(r.hits_inc_ft || []).length);
  if (S.hit === "exc") rs = rs.filter(r => r.hits_exc.length || (r.hits_exc_ft || []).length);
  if (S.hit === "noabs") rs = rs.filter(r => (r.abstract || "").length < 100);
  const score = r => r.hits_inc.length * 2 + (r.hits_inc_ft || []).length - r.hits_exc.length * 3;
  if (S.sort === "score") rs = [...rs].sort((a, b) => score(b) - score(a));
  if (S.sort === "year") rs = [...rs].sort((a, b) => (b.year || "").localeCompare(a.year || ""));
  if (S.sort === "title") rs = [...rs].sort((a, b) => a.title.localeCompare(b.title));
  return rs;
}
function stageOf(r) { return (dec(r.id).ta === "include" && S.tab !== "ta" && S.tab !== "maybe") ? "ft" : "ta"; }

function screen() {
  const counts = Object.fromEntries(TABS.map(t => [t[0], P().records.filter(t[2]).length]));
  $("#app").innerHTML = `
  <div class="tabs">${TABS.map(([k, l]) => `<span class="tab ${S.tab === k ? "on" : ""}" data-t="${k}">${l}<b>${counts[k]}</b></span>`).join("")}</div>
  <div class="filters"><div class="row">
    <input type="search" id="q" placeholder="Search title, abstract, authors, DOI…" value="${esc(S.q)}" style="flex:1;min-width:220px">
    <select id="hit"><option value="">All records</option><option value="inc">Matches an inclusion term</option><option value="noinc">No inclusion term</option>
      <option value="exc">Matches an exclusion term</option><option value="noabs">No abstract</option></select>
    <select id="pdfsel"><option value="">PDF: any</option><option value="yes">Has PDF</option><option value="no">No PDF</option></select>
    <select id="sort"><option value="default">Import order</option><option value="score">Term score</option><option value="year">Newest first</option><option value="title">Title A–Z</option></select>
    <span id="nshown" class="small mut"></span>
    <span style="margin-left:auto"></span>
    <select id="bulkreason"></select><button class="exc" id="bulk">Exclude all shown</button>
  </div><div class="small mut" style="margin-top:4px">Keys: <kbd>j</kbd>/<kbd>k</kbd> next/previous · <kbd>i</kbd> include · <kbd>e</kbd> exclude (reason from the card) · <kbd>m</kbd> maybe · <kbd>u</kbd> undo · <kbd>a</kbd> abstract · <kbd>o</kbd> open PDF/DOI · drop a PDF on a card to attach it</div></div>
  <div id="list"></div><div id="more"></div>`;
  $("#hit").value = S.hit; $("#pdfsel").value = S.pdf; $("#sort").value = S.sort;
  document.querySelectorAll(".tab").forEach(t => t.onclick = () => { S.tab = t.dataset.t; S.shown = 40; S.sel = 0; screen(); });
  let qt; $("#q").oninput = e => { clearTimeout(qt); qt = setTimeout(() => { S.q = e.target.value; S.shown = 40; S.sel = 0; drawList(); }, 200); };
  $("#hit").onchange = e => { S.hit = e.target.value; S.shown = 40; S.sel = 0; drawList(); };
  $("#pdfsel").onchange = e => { S.pdf = e.target.value; S.shown = 40; S.sel = 0; drawList(); };
  $("#sort").onchange = e => { S.sort = e.target.value; drawList(); };
  const ftTab = S.tab === "ft" || S.tab === "inc";
  const reasons = ftTab ? [...P().settings.reasons_ft, P().not_retrieved_reason] : P().settings.reasons_ta;
  $("#bulkreason").innerHTML = reasons.map(x => `<option>${esc(x)}</option>`).join("");
  $("#bulk").onclick = async () => {
    const rs = filtered();
    if (!rs.length || !confirm(`Exclude ${rs.length} records (${ftTab ? "full text" : "title/abstract"}) with reason "${$("#bulkreason").value}"?`)) return;
    await decide(rs.map(r => r.id), ftTab ? "ft" : "ta", "exclude", $("#bulkreason").value);
    screen();
  };
  drawList();
}

function card(r, i) {
  const d = dec(r.id), stage = stageOf(r);
  const reasons = stage === "ft" ? [...P().settings.reasons_ft, P().not_retrieved_reason] : P().settings.reasons_ta;
  const cur = d[stage], curReason = d[stage + "_reason"];
  const chips = [...r.hits_inc.map(t => `<span class="chip">${esc(t)}</span>`), ...(r.hits_inc_ft || []).map(t => `<span class="chip ft" title="only in full text">${esc(t)} (full text)</span>`),
    ...r.hits_exc.map(t => `<span class="chip x">${esc(t)}</span>`), ...(r.hits_exc_ft || []).map(t => `<span class="chip x ft">${esc(t)} (full text)</span>`)].join("");
  const status = [d.ta && `<span class="chip dec-${d.ta}">T/A: ${d.ta}${d.ta_reason ? " — " + esc(d.ta_reason) : ""}${d.ta_auto ? " (auto)" : ""}</span>`,
    d.ft && `<span class="chip dec-${d.ft}">Full text: ${d.ft}${d.ft_reason ? " — " + esc(d.ft_reason) : ""}</span>`].filter(Boolean).join("");
  const open = S.open.has(r.id);
  const au = (r.authors || []).slice(0, 3).join("; ") + ((r.authors || []).length > 3 ? " et al." : "");
  return `<article class="card d-${cur || ""} ${i === S.sel ? "sel" : ""}" data-id="${esc(r.id)}" data-i="${i}">
   <div class="meta"><code>${esc(r.id)}</code> · ${esc(r.year || "?")} · ${esc(r.venue || "")} · <span title="source">${esc(r.source || "")}</span>${r.dup_of ? ` · duplicate of <code>${esc(r.dup_of)}</code>` : ""}</div>
   <h3>${highlight(r.title)}</h3>
   <div class="meta">${esc(au)}</div>
   ${r.abstract ? `<div class="abs ${open ? "" : "clip"}" data-abs>${highlight(r.abstract)}</div>` : `<div class="abs mut small">No abstract — use "Update metadata" on the Import page, or open the article.</div>`}
   <div>${chips}${status}</div>
   <div class="links">${r.doi ? `<a href="https://doi.org/${esc(r.doi)}" target="_blank" rel="noopener">DOI</a>` : ""}
    <a href="https://scholar.google.com/scholar?q=${encodeURIComponent(r.title)}" target="_blank" rel="noopener">Scholar</a>
    ${r.has_pdf ? `<a href="/api/project/${S.slug}/pdf/${encodeURIComponent(r.id)}" target="_blank"><b>PDF</b></a>` : `<span class="small mut">no PDF${r.pdf_failed ? " (download failed)" : ""} — drop one here</span>`}</div>
   ${r.dup_of ? "" : `<div class="actions"><span class="lbl">${stage === "ft" ? "Full text:" : "Title/abstract:"}</span>
    <button class="inc ${cur === "include" ? "on" : ""}" data-a="include">Include</button>
    ${stage === "ta" ? `<button class="may ${cur === "maybe" ? "on" : ""}" data-a="maybe">Maybe</button>` : ""}
    <button class="exc ${cur === "exclude" ? "on" : ""}" data-a="exclude">Exclude</button>
    <select data-reason>${reasons.map(x => `<option ${x === curReason ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
    ${cur ? `<button data-a="reset" title="undo">Undo</button>` : ""}
    ${stage === "ft" ? `<button data-a="back" title="move back to title/abstract stage">Back to T/A</button>` : ""}</div>`}
  </article>`;
}

function drawList() {
  const rs = filtered();
  S.sel = Math.min(S.sel, Math.max(0, rs.length - 1));
  if (S.sel >= S.shown) S.shown = S.sel + 10;
  $("#nshown").textContent = `${rs.length} shown`;
  $("#list").innerHTML = rs.slice(0, S.shown).map(card).join("") || `<p class="mut">Nothing here.</p>`;
  $("#more").innerHTML = rs.length > S.shown ? `<button id="morebtn">Show more (${rs.length - S.shown} left)</button>` : "";
  if ($("#morebtn")) $("#morebtn").onclick = () => { S.shown += 60; drawList(); };
  document.querySelectorAll(".card").forEach(el => {
    const id = el.dataset.id;
    el.onclick = e => {
      S.sel = +el.dataset.i;
      document.querySelectorAll(".card.sel").forEach(x => x.classList.remove("sel")); el.classList.add("sel");
      const a = e.target.dataset && e.target.dataset.a;
      if (a) act(id, a, $("[data-reason]", el)?.value);
      else if (e.target.hasAttribute && e.target.hasAttribute("data-abs")) { S.open.has(id) ? S.open.delete(id) : S.open.add(id); e.target.classList.toggle("clip"); }
    };
    el.ondragover = e => { e.preventDefault(); el.classList.add("dragover"); };
    el.ondragleave = () => el.classList.remove("dragover");
    el.ondrop = async e => {
      e.preventDefault(); el.classList.remove("dragover");
      const f = e.dataTransfer.files[0]; if (!f) return;
      try { await api(`project/${S.slug}/upload-pdf/${encodeURIComponent(id)}`, {body: await f.arrayBuffer(), raw: true}); toast("PDF attached"); await load(); drawList(); }
      catch (err) { toast(err.message); }
    };
  });
}

async function decide(ids, stage, value, reason) {
  const r = await api(`project/${S.slug}/decide`, {body: {ids, stage, value, reason}});
  ids.forEach(id => {
    const d = P().decisions[id] = P().decisions[id] || {};
    if (value === null) { delete d[stage]; delete d[stage + "_reason"]; delete d[stage + "_auto"]; }
    else { d[stage] = value; d[stage + "_reason"] = value === "exclude" ? reason : ""; delete d[stage + "_auto"]; }
  });
  P().counts = r.counts; nav();
}
async function act(id, a, reason) {
  const r = P().records.find(x => x.id === id), stage = stageOf(r);
  if (a === "back") { await decide([id], "ft", null); await decide([id], "ta", null); }
  else if (a === "reset") await decide([id], stage, null);
  else await decide([id], stage, a, reason);
  const tabs = $(".tabs");
  if (tabs) tabs.innerHTML = TABS.map(([k, l]) => `<span class="tab ${S.tab === k ? "on" : ""}" data-t="${k}">${l}<b>${P().records.filter(TABS.find(t => t[0] === k)[2]).length}</b></span>`).join("");
  document.querySelectorAll(".tab").forEach(t => t.onclick = () => { S.tab = t.dataset.t; S.shown = 40; S.sel = 0; screen(); });
  drawList();
}

document.addEventListener("keydown", e => {
  if (S.view !== "screen" || !S.P || ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
  const cards = [...document.querySelectorAll(".card")];
  const el = cards[S.sel]; if (!el) return;
  const id = el.dataset.id, k = e.key.toLowerCase();
  const sel = i => { S.sel = Math.max(0, Math.min(cards.length - 1, i)); cards.forEach(c => c.classList.remove("sel")); cards[S.sel].classList.add("sel"); cards[S.sel].scrollIntoView({block: "nearest", behavior: "smooth"}); };
  if (k === "j") sel(S.sel + 1);
  else if (k === "k") sel(S.sel - 1);
  else if (k === "i") act(id, "include");
  else if (k === "e") act(id, "exclude", $("[data-reason]", el)?.value);
  else if (k === "m" && stageOf(P().records.find(x => x.id === id)) === "ta") act(id, "maybe");
  else if (k === "u") act(id, "reset");
  else if (k === "a") { const ab = $("[data-abs]", el); if (ab) { ab.classList.toggle("clip"); S.open.has(id) ? S.open.delete(id) : S.open.add(id); } }
  else if (k === "o") { const a = $(".links a[href*='/pdf/']", el) || $(".links a", el); if (a) window.open(a.href, "_blank"); }
  else return;
  e.preventDefault();
});

/* ------------------------------------------------------------ PRISMA */
async function prismaView() {
  const c = await api(`project/${S.slug}/counts`); P().counts = c; nav();
  const methods = await api(`project/${S.slug}/export/methods.txt`);
  if (S.view !== "prisma") return;
  const rows = o => Object.entries(o).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="n">${v}</td></tr>`).join("") || `<tr><td class="mut">None</td><td></td></tr>`;
  const ex = n => `/api/project/${S.slug}/export/${n}`;
  $("#app").innerHTML = `
  <h1>PRISMA 2020 summary</h1>
  <div class="kpis">
   <div class="kpi"><b>${c.identified}</b><span>records identified</span></div>
   <div class="kpi"><b>${c.duplicates}</b><span>duplicates removed</span></div>
   <div class="kpi"><b>${c.screened}</b><span>records screened</span></div>
   <div class="kpi"><b>${c.sought}</b><span>reports sought</span></div>
   <div class="kpi"><b>${c.assessed}</b><span>reports assessed</span></div>
   <div class="kpi"><b>${c.included}</b><span>studies included</span></div>
  </div>
  <div class="grid2">
   <div class="panel"><h3>Progress</h3>
    <div class="small">Title/abstract screening: ${c.screened - c.ta_pending} of ${c.screened} decided (${c.progress_ta}%)${c.ta_maybe ? ` · ${c.ta_maybe} marked maybe` : ""}</div><div class="bar"><i style="width:${c.progress_ta}%"></i></div>
    <div class="small" style="margin-top:8px">Full-text assessment: ${c.sought - c.ft_pending} of ${c.sought} decided (${c.progress_ft}%) · ${c.sought_with_pdf} of ${c.sought} have a PDF</div><div class="bar"><i style="width:${c.progress_ft}%"></i></div>
   </div>
   <div class="panel"><h3>Export</h3>
    <div class="row"><a class="btn" href="${ex("prisma.svg")}" download="prisma.svg">Flow diagram (SVG)</a>
     <a class="btn" href="${ex("prisma.tex")}">Flow diagram (LaTeX/TikZ)</a>
     <a class="btn" href="${ex("screening.csv")}">Screening record (CSV)</a>
     <a class="btn" href="${ex("included.bib")}">Included studies (BibTeX)</a>
     <a class="btn" href="${ex("project.json")}">Full project (JSON)</a></div>
    <p class="small mut">The CSV lists every record with source, duplicate status, both decisions and reasons — suitable as supplementary material.</p>
   </div>
  </div>
  <h2>Flow diagram</h2>
  <div class="svgwrap"><img src="${ex("prisma.svg")}?t=${Date.now()}" alt="PRISMA flow diagram"></div>
  <div class="grid2" style="margin-top:16px">
   <div class="panel"><h3>Records excluded at title/abstract (${c.ta_excluded})</h3><table>${rows(c.ta_excluded_reasons)}</table>
    <p class="small mut">Plus ${c.automation} excluded by automation (exclusion terms).</p></div>
   <div class="panel"><h3>Reports excluded at full text (${c.ft_excluded})</h3><table>${rows(c.ft_excluded_reasons)}</table>
    <p class="small mut">Not retrieved: ${c.not_retrieved}</p></div>
  </div>
  <h2>Methods text (draft)</h2>
  <div class="panel"><textarea id="methods" style="min-height:170px;font-family:inherit;font-size:14px">${esc(methods)}</textarea>
   <button id="copym" style="margin-top:6px">Copy</button></div>`;
  $("#copym").onclick = () => { navigator.clipboard.writeText($("#methods").value); toast("Copied"); };
}

window.addEventListener("unhandledrejection", e => toast("Error: " + (e.reason && e.reason.message || e.reason)));
route().then(pollJob);
