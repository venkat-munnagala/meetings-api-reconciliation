/* Event Sync UI: vanilla JS over the /api routes. No build step. */
(function () {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (v) => {
    if (v === null || v === undefined) return '<span class="muted">—</span>';
    if (Array.isArray(v)) return v.length ? esc(v.join(", ")) : '<span class="muted">[]</span>';
    if (typeof v === "object") return "<code>" + esc(JSON.stringify(v)) + "</code>";
    return esc(v);
  };
  const time = (iso) => (iso ? iso.slice(11, 16) : "");
  const api = async (path, opts) => {
    const r = await fetch(path, opts);
    const body = await r.json();
    if (!r.ok) throw new Error(body.error ? body.error.message : r.statusText);
    return body;
  };

  // ---- tabs --------------------------------------------------------------
  $$(".tab").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
  async function showView(name) {
    $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
    $$(".view").forEach((v) => v.classList.toggle("hidden", v.id !== "view-" + name));
    ({ meetings: loadMeetings, proposals: loadProposals, quality: loadQuality, unmatched: loadUnmatched })[name]();
  }

  // ---- stats -------------------------------------------------------------
  async function loadStats() {
    const s = await api("/api/stats");
    const k = s.meetings_by_kind, p = s.proposals_by_level;
    $("#stats").innerHTML =
      `<span><b>${s.meetings_total}</b> meetings</span>` +
      `<span><b>${k.auto || 0}</b> auto · <b>${k.proposed || 0}</b> proposed · <b>${k.singleton || 0}</b> singleton</span>` +
      `<span><b>${Object.values(p).reduce((a, b) => a + b, 0)}</b> proposals</span>` +
      `<span>window ±${s.config.tight_window_min} min · tz ${esc(s.config.local_tz)} · normaliser v${esc(s.normalizer_version)}</span>`;
  }
  $("#sync").addEventListener("click", async () => {
    $("#sync").disabled = true;
    try { await api("/api/sync", { method: "POST" }); await loadStats(); showView(currentView()); }
    catch (e) { alert("Sync failed: " + e.message); }
    finally { $("#sync").disabled = false; }
  });
  const currentView = () => $(".tab.active").dataset.view;

  // ---- meetings ----------------------------------------------------------
  const filters = $("#filters");
  filters.addEventListener("change", loadMeetings);
  filters.owner.addEventListener("input", debounce(loadMeetings, 300));
  $("#clear").addEventListener("click", () => { filters.reset(); loadMeetings(); });
  let selected = null;

  async function loadMeetings() {
    const q = new URLSearchParams();
    for (const el of filters.elements) if (el.name && el.value) q.set(el.name, el.value);
    const rows = await api("/api/meetings?" + q.toString());
    const tb = $("#meetings tbody");
    tb.innerHTML = rows.map((m) => {
      const f = m.fields, mt = m.match;
      const lvl = mt.level ? `L${mt.level}` : "";
      return `<tr data-id="${m.meeting_id}" class="${m.meeting_id === selected ? "selected" : ""}">
        <td>${esc(f.day.value)}</td><td>${esc(time(f.start.value))}</td>
        <td>${fmt(f.title.value)}</td><td>${esc((f.owner_email.value || "").split("@")[0])}</td>
        <td>${fmt(f.client_company.value)}</td><td>${fmt(f.location_kind.value)}</td><td>${fmt(f.status.value)}</td>
        <td><span class="badge ${mt.kind}">${mt.kind} ${lvl}</span></td><td>${esc(mt.confidence || "")}</td>
        <td>${m.conflict_count ? `<span class="count conflict">${m.conflict_count}</span>` : ""} ${m.flag_count ? `<span class="count flags">${m.flag_count}</span>` : ""}</td>
      </tr>`;
    }).join("") || `<tr><td colspan="10" class="muted">No meetings match these filters.</td></tr>`;
    $$("tr[data-id]", tb).forEach((tr) => tr.addEventListener("click", () => openMeeting(tr.dataset.id)));
    if (selected && !rows.some((m) => m.meeting_id === selected)) { selected = null; $("#detail").innerHTML = '<p class="muted">Select a meeting.</p>'; }
  }

  async function openMeeting(id) {
    selected = id;
    $$("#meetings tbody tr").forEach((tr) => tr.classList.toggle("selected", tr.dataset.id === id));
    const m = await api("/api/meetings/" + id);
    $("#detail").innerHTML = renderMeeting(m);
  }

  function renderMeeting(m) {
    const mt = m.match, ev = mt.evidence;
    const src = Object.entries(m.sources).filter(([, r]) => r).map(([s, r]) => `${s}: <code>${esc(r.source_id)}</code>`).join(" · ");
    const evid = ev ? `<div class="meta">evidence: dt ${ev.dt_minutes ?? "n/a"} min${ev.whole_hour_gap ? " (whole-hour gap)" : ""}, contained ${ev.participants_contained}, owner agree ${ev.owner_agree}, client agree ${ev.client_agree ?? "n/a"}, title overlap ${ev.title_overlap.toFixed(2)}</div>` : "";
    const props = m.proposals.length ? `<div class="meta">proposals: ${m.proposals.map((p) => `<a href="#" data-proposal="${p}">${p}</a>`).join(", ")}</div>` : "";
    const flags = m.flags.length ? `<details><summary>${m.flags.length} quality flag(s)</summary><ul class="flaglist">${m.flags.map((f) => `<li><b>${esc(f.source)}</b> ${esc(f.field)} · <code>${esc(f.code)}</code> ${esc(f.detail)}</li>`).join("")}</ul></details>` : "";
    const raw = Object.entries(m.sources).filter(([, r]) => r).map(([s, r]) => `<details><summary>raw ${s} record</summary><pre>${esc(JSON.stringify(r.payload, null, 2))}</pre></details>`).join("");
    return `<h2>${fmt(m.fields.title.value)}</h2>
      <div class="meta"><span class="badge ${mt.kind}">${mt.kind}${mt.level ? " · level " + mt.level : ""}${mt.confidence ? " · " + mt.confidence : ""}</span>
        ${mt.match_key ? ` <code>${esc(mt.match_key)}</code>` : ""} · ${src} · ${m.conflict_count} conflict(s)</div>
      ${evid}${props}
      ${renderFields(m.fields)}
      ${flags}${raw}`;
  }

  function renderFields(fields) {
    const rows = Object.entries(fields).map(([name, fv]) => {
      const win = (s) => (fv.winner === s ? " win" : "");
      return `<tr class="${fv.status}">
        <td class="field">${esc(name)}<span class="rule">${esc(fv.status)}${fv.rule ? " · " + esc(fv.rule) : ""}</span></td>
        <td class="value">${fmt(fv.value)}</td>
        <td class="${win("crm")}">${fv.crm ? fmt(fv.crm.normalized) + (String(fv.crm.raw) !== String(fv.crm.normalized) && fv.crm.raw !== null && typeof fv.crm.raw !== "object" ? `<span class="rule">raw: ${esc(fv.crm.raw)}</span>` : "") : '<span class="muted">—</span>'}</td>
        <td class="${win("calendar")}">${fv.calendar ? fmt(fv.calendar.normalized) + (String(fv.calendar.raw) !== String(fv.calendar.normalized) && fv.calendar.raw !== null && typeof fv.calendar.raw !== "object" ? `<span class="rule">raw: ${esc(fv.calendar.raw)}</span>` : "") : '<span class="muted">—</span>'}</td>
      </tr>`;
    }).join("");
    return `<table class="fields"><thead><tr><th>Field · status · rule</th><th>Reconciled</th><th>CRM</th><th>Calendar</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-proposal]");
    if (!a) return;
    e.preventDefault();
    showView("proposals").then(() => openProposal(a.dataset.proposal));
  });

  // ---- proposals ---------------------------------------------------------
  async function loadProposals() {
    const ps = await api("/api/proposals");
    $("#proposals tbody").innerHTML = ps.map((p) => `<tr data-id="${p.proposal_id}">
      <td>${esc(p.level)}</td><td>${esc(p.kind)}</td>
      <td><code>${esc(p.left.source_id)}</code></td><td><code>${esc(p.right.source_id)}</code></td>
      <td>${p.reasons.map(esc).join("; ")}</td></tr>`).join("") || `<tr><td colspan="5" class="muted">No proposals.</td></tr>`;
    $$("#proposals tr[data-id]").forEach((tr) => tr.addEventListener("click", () => openProposal(tr.dataset.id)));
  }

  async function openProposal(id) {
    $$("#proposals tbody tr").forEach((tr) => tr.classList.toggle("selected", tr.dataset.id === id));
    const p = await api("/api/proposals/" + id);
    let body;
    if (p.kind === "cross_source") {
      body = `<p class="muted">Preview of the merge if confirmed. Winner rules applied; nothing is merged yet.</p>` + renderFields(p.preview);
    } else {
      const rows = Object.entries(p.preview).map(([f, v]) => `<tr class="${v.same ? "agree" : "differs"}">
        <td class="field">${esc(f)}</td><td>${fmt(v.left)}</td><td>${fmt(v.right)}</td></tr>`).join("");
      body = `<p class="muted">Two records in the same source that look like one meeting. Neither is removed.</p>
        <table class="fields"><thead><tr><th>Field</th><th>${esc(p.left.source_id)}</th><th>${esc(p.right.source_id)}</th></tr></thead><tbody>${rows}</tbody></table>`;
    }
    const ev = p.evidence ? `<div class="meta">dt ${p.evidence.dt_minutes ?? "n/a"} min · contained ${p.evidence.participants_contained} · owner agree ${p.evidence.owner_agree} · title overlap ${p.evidence.title_overlap.toFixed(2)}</div>` : "";
    $("#proposal-detail").innerHTML = `<h2>Proposal <code>${esc(p.proposal_id)}</code></h2>
      <div class="meta">level ${esc(p.level)} · ${esc(p.kind)} · <a href="#" data-meeting="${p.left.meeting_id}">${esc(p.left.source_id)}</a> ↔ <a href="#" data-meeting="${p.right.meeting_id}">${esc(p.right.source_id)}</a></div>
      <ul class="reasons">${p.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>${ev}${body}`;
  }
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-meeting]");
    if (!a) return;
    e.preventDefault();
    showView("meetings").then(() => openMeeting(a.dataset.meeting));
  });

  // ---- quality -----------------------------------------------------------
  $("#quality-code").addEventListener("change", loadQuality);
  async function loadQuality() {
    const code = $("#quality-code").value;
    const fs = await api("/api/quality" + (code ? "?code=" + encodeURIComponent(code) : ""));
    if ($("#quality-code").options.length === 1) {
      const all = await api("/api/quality");
      [...new Set(all.map((f) => f.code))].sort().forEach((c) => $("#quality-code").add(new Option(c, c)));
    }
    $("#quality tbody").innerHTML = fs.map((f) => `<tr><td>${esc(f.source)}</td><td><code>${esc(f.source_id)}</code></td><td>${esc(f.field)}</td><td><code>${esc(f.code)}</code></td><td>${esc(f.detail)}</td></tr>`).join("");
  }

  // ---- unmatched ---------------------------------------------------------
  async function loadUnmatched() {
    const u = await api("/api/unmatched");
    const rows = [];
    for (const src of ["crm", "calendar"]) for (const x of u[src]) {
      const b = x.best_candidate;
      rows.push(`<tr data-meeting="${x.meeting_id}"><td>${src}</td><td><code>${esc(x.source_id)}</code></td><td><span class="badge ${x.kind}">${x.kind}</span></td>
        <td>${b ? `<code>${esc(b.other_id)}</code>${b.level_reached ? ` (reached level ${b.level_reached})` : ""}` : '<span class="muted">no same-day candidate</span>'}</td>
        <td>${b ? b.reasons.map(esc).join("; ") : ""}</td></tr>`);
    }
    $("#unmatched tbody").innerHTML = rows.join("");
    $$("#unmatched tr[data-meeting]").forEach((tr) => tr.addEventListener("click", () => showView("meetings").then(() => openMeeting(tr.dataset.meeting))));
  }

  function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

  loadStats();
  loadMeetings();
})();
