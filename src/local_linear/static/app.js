"use strict";

// ---- tiny helpers ----------------------------------------------------------
const $ = (sel, el = document) => el.querySelector(sel);

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "value") el.value = v;
    else if (k === "style") el.style.cssText = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}

function svg(markup) {
  const s = h("span", { class: "icon" });
  s.innerHTML = markup; // only called with static, trusted strings
  return s;
}

// Server-rendered Markdown: the API escapes raw HTML and rejects unsafe links before this is
// assigned to innerHTML (see local_linear/markdown.py).
function mdView(html, cls = "") {
  const el = h("div", { class: ("md " + cls).trim() });
  el.innerHTML = html;
  return el;
}

// Rendered Markdown that turns into a textarea on click and saves when focus leaves it.
function mdBlock({ source, html, placeholder, onSave, tall = false }) {
  const view = h("div", { class: "md-view" + (html ? "" : " md-empty") });
  if (html) view.innerHTML = html;
  else view.textContent = placeholder;
  const area = h("textarea", { class: "desc-input" + (tall ? " tall" : ""), placeholder, style: "display:none",
    onblur: () => { if (area.value !== source) onSave(area.value); else show(false); },
    onkeydown: (e) => { if (e.key === "Escape") area.value = source; } });
  area.value = source;
  const hint = h("div", { class: "hint", style: "display:none" }, "Markdown supported · click outside to save · Esc to cancel");
  function show(editing) {
    view.style.display = editing ? "none" : "";
    area.style.display = hint.style.display = editing ? "" : "none";
    if (editing) area.focus();
  }
  view.onclick = (e) => { if (!e.target.closest("a")) show(true); }; // let links be followed
  return h("div", { class: "md-block" }, view, area, hint);
}

function toast(msg, error = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (error ? " error" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.className = ""), 2600);
}

async function api(path, opts = {}) {
  const res = await fetch("/api" + path, {
    method: opts.method || "GET",
    headers: opts.body ? { "Content-Type": "application/json" } : undefined,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {}
    toast(detail, true);
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem("ll." + k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("ll." + k, JSON.stringify(v)); } catch {} },
};

const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "");
const initials = (name) => (name || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
const avatar = (u) => (u ? h("span", { class: "avatar", title: u.name }, initials(u.name)) : null);

// ---- icons -----------------------------------------------------------------
function statusIcon(type, color) {
  const c = color || "#95a2b3";
  const base = (inner) => svg(`<svg width="14" height="14" viewBox="0 0 14 14" fill="none">${inner}</svg>`);
  switch (type) {
    case "completed":
      return base(`<circle cx="7" cy="7" r="6" fill="${c}"/><path d="M4 7.2l2 2L10 5" stroke="#fff" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`);
    case "canceled":
      return base(`<circle cx="7" cy="7" r="6" stroke="${c}" stroke-width="1.5"/><path d="M5 5l4 4M9 5l-4 4" stroke="${c}" stroke-width="1.5" stroke-linecap="round"/>`);
    case "started":
      return base(`<circle cx="7" cy="7" r="6" stroke="${c}" stroke-width="1.5"/><path d="M7 3a4 4 0 010 8z" fill="${c}"/>`);
    case "backlog":
      return base(`<circle cx="7" cy="7" r="6" stroke="${c}" stroke-width="1.5" stroke-dasharray="2 2"/>`);
    default:
      return base(`<circle cx="7" cy="7" r="6" stroke="${c}" stroke-width="1.5"/>`);
  }
}

function priorityIcon(p) {
  if (p === 1) return svg(`<svg width="14" height="14" viewBox="0 0 14 14"><rect x="1" y="1" width="12" height="12" rx="3" fill="#eb5757"/><path d="M7 4v4.2M7 10v.2" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/></svg>`);
  const lit = p === 0 ? 0 : 5 - p; // 2->3 bars, 3->2, 4->1
  const bar = (i, x, y, ht) =>
    `<rect x="${x}" y="${y}" width="3" height="${ht}" rx="1" fill="currentColor" opacity="${p === 0 || i > lit ? 0.25 : 1}"/>`;
  return svg(`<svg width="14" height="14" viewBox="0 0 14 14">${bar(1, 1, 8, 5)}${bar(2, 5.5, 5, 8)}${bar(3, 10, 2, 11)}</svg>`);
}

// ---- app state -------------------------------------------------------------
const state = {
  meta: { teams: [], users: [], labels: [], priorities: [], project_statuses: [] },
  team: store.get("team", ""),
  view: store.get("view", "list"),
  tab: "all",
  filters: { q: "", priority: "", assignee: "", label: "" },
};

const teamKey = () => state.team || (state.meta.teams[0] && state.meta.teams[0].key) || "";
const teamById = (id) => state.meta.teams.find((t) => t.id === id);
const currentUser = () => {
  const users = state.meta.users;
  return users.find((u) => u.id === store.get("me", null)) || users.find((u) => u.name === "Me") || users[0] || null;
};

async function loadMeta() {
  state.meta = await api("/meta");
  if (state.team && !state.meta.teams.some((t) => t.key === state.team)) state.team = "";
}

function parseRoute() {
  const [path, query] = location.hash.replace(/^#/, "").split("?");
  return { parts: path.split("/").filter(Boolean), query: new URLSearchParams(query || "") };
}

const go = (hash) => { location.hash = hash; };

// ---- sidebar ---------------------------------------------------------------
function renderSidebar(route) {
  const side = $("#sidebar");
  const [page] = route.parts;
  const nav = (label, hash, active, extra) =>
    h("button", { class: "nav-item" + (active ? " active" : ""), onclick: () => go(hash) }, label, extra);

  side.replaceChildren(
    h("div", { class: "brand" }, h("span", { class: "logo" }), "Local Linear"),
    h("button", { class: "btn-new", onclick: () => openIssueModal() }, "New issue", h("kbd", {}, "C")),
    nav("All issues", "#/issues", (!page || page === "issues" || page === "issue") && !state.team),
    nav("Projects", "#/projects", page === "projects" || page === "project"),
    h("div", { class: "nav-label" }, "Teams"),
    ...state.meta.teams.map((t) =>
      nav(t.name, "#/issues?team=" + t.key, (page === "issues" || !page) && state.team === t.key, h("span", { class: "key" }, t.key))
    ),
    h("button", { class: "nav-item", onclick: openTeamModal }, "+ New team"),
    h("div", { class: "spacer" }),
    state.meta.users.length > 0 && h("div", { class: "prop", style: "padding:0 8px 6px" },
      h("label", {}, "Signed in as"),
      select(state.meta.users.map((u) => [u.id, u.name]), currentUser().id, (v) => store.set("me", +v), "field")),
    h("button", { class: "nav-item", onclick: toggleTheme }, "Toggle theme")
  );
}

function toggleTheme() {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  store.set("theme", root.dataset.theme);
}

// ---- issues list / board ---------------------------------------------------
function select(options, value, onchange, cls = "field") {
  const el = h("select", { class: cls, onchange: (e) => onchange(e.target.value) },
    options.map(([v, label]) => h("option", { value: v, selected: String(v) === String(value) }, label)));
  return el;
}

async function renderIssues(route) {
  state.team = route.query.get("team") || "";
  store.set("team", state.team);
  renderSidebar(route);

  const main = $("#main");
  const params = new URLSearchParams();
  if (state.team) params.set("team", state.team);
  const f = state.filters;
  if (f.q) params.set("q", f.q);
  if (f.priority) params.set("priority", f.priority);
  if (f.assignee === "none") params.set("unassigned", "true");
  else if (f.assignee) params.set("assignee_id", f.assignee);
  if (f.label) params.set("label_id", f.label);
  params.set("order_by", "priority");

  let issues = await api("/issues?" + params);
  if (state.tab === "active") issues = issues.filter((i) => ["unstarted", "started"].includes(i.status.type));
  if (state.tab === "backlog") issues = issues.filter((i) => i.status.type === "backlog");

  const teamTitle = state.team ? (state.meta.teams.find((t) => t.key === state.team) || {}).name : "All issues";
  const rerender = () => renderIssues(parseRoute());

  const header = h("div", { class: "page-header" },
    h("h1", {}, teamTitle),
    h("div", { class: "tabs" },
      [["all", "All"], ["active", "Active"], ["backlog", "Backlog"]].map(([k, label]) =>
        h("button", { class: "tab" + (state.tab === k ? " active" : ""), onclick: () => { state.tab = k; rerender(); } }, label))),
    h("div", { class: "seg" },
      [["list", "List"], ["board", "Board"]].map(([k, label]) =>
        h("button", { class: state.view === k ? "active" : "", onclick: () => { state.view = k; store.set("view", k); rerender(); } }, label))));

  const search = h("input", { type: "search", id: "search", placeholder: "Search issues (/)", value: f.q,
    onkeydown: (e) => { if (e.key === "Enter") { f.q = e.target.value.trim(); rerender(); } } });
  const filters = h("div", { class: "filters" },
    search,
    select([["", "Any priority"], ...state.meta.priorities.map((p) => [p.value, p.name])], f.priority, (v) => { f.priority = v; rerender(); }),
    select([["", "Any assignee"], ["none", "Unassigned"], ...state.meta.users.map((u) => [u.id, u.name])], f.assignee, (v) => { f.assignee = v; rerender(); }),
    select([["", "Any label"], ...state.meta.labels.map((l) => [l.id, l.name])], f.label, (v) => { f.label = v; rerender(); }));

  const body = issues.length === 0
    ? h("div", { class: "empty" }, "No issues. Press C to create one.")
    : state.view === "board" ? boardView(issues, rerender) : listView(issues);
  main.replaceChildren(header, filters, body);
}

function statusesFor(issues) {
  // Columns/groups: the statuses of the selected team, or the union (by name/type) across teams.
  const teams = state.team ? state.meta.teams.filter((t) => t.key === state.team) : state.meta.teams;
  const seen = new Map();
  for (const t of teams) for (const s of t.statuses) if (!seen.has(s.name)) seen.set(s.name, s);
  return [...seen.values()].sort((a, b) => a.position - b.position);
}

function labelChips(issue) {
  return issue.labels.map((l) => h("span", { class: "chip" }, h("span", { class: "dot", style: `background:${l.color}` }), l.name));
}

function issueRow(i) {
  return h("div", { class: "row", onclick: () => go("#/issue/" + i.identifier) },
    priorityIcon(i.priority),
    h("span", { class: "ident" }, i.identifier),
    statusIcon(i.status.type, i.status.color),
    h("span", { class: "title" }, i.title),
    h("span", { class: "meta" },
      labelChips(i),
      i.project_name && h("span", { class: "chip" }, i.project_name),
      i.sub_issue_count > 0 && h("span", {}, "↳ " + i.sub_issue_count),
      i.comment_count > 0 && h("span", {}, "💬 " + i.comment_count),
      h("span", {}, fmtDate(i.created_at)),
      avatar(i.assignee)));
}

function listView(issues, opts = {}) {
  const wrap = h("div");
  for (const st of statusesFor(issues)) {
    const group = issues.filter((i) => i.status.name === st.name);
    if (!group.length) continue;
    wrap.append(
      h("div", { class: "group-head" }, statusIcon(st.type, st.color), st.name, h("span", { class: "count" }, group.length),
        h("button", { class: "add", title: "New issue", onclick: () => openIssueModal({ status: st.name, ...(opts.defaults || {}) }) }, "+")),
      ...group.map(issueRow));
  }
  return wrap;
}

function boardView(issues, rerender, opts = {}) {
  const board = h("div", { class: "board" });
  for (const st of statusesFor(issues)) {
    const group = issues.filter((i) => i.status.name === st.name);
    const col = h("div", { class: "column",
      ondragover: (e) => { e.preventDefault(); col.classList.add("over"); },
      ondragleave: () => col.classList.remove("over"),
      ondrop: async (e) => {
        e.preventDefault();
        col.classList.remove("over");
        const ref = e.dataTransfer.getData("text/plain");
        const issue = issues.find((x) => x.identifier === ref);
        if (!issue || issue.status.name === st.name) return;
        const target = teamById(issue.team_id).statuses.find((s) => s.name === st.name);
        if (!target) return toast("That team has no status named " + st.name, true);
        await api("/issues/" + ref, { method: "PATCH", body: { status_id: target.id } });
        rerender();
      } },
      h("div", { class: "group-head" }, statusIcon(st.type, st.color), st.name, h("span", { class: "count" }, group.length),
        h("button", { class: "add", title: "New issue", onclick: () => openIssueModal({ status: st.name, ...(opts.defaults || {}) }) }, "+")));
    for (const i of group) {
      col.append(h("div", { class: "card", draggable: "true",
        ondragstart: (e) => { e.dataTransfer.setData("text/plain", i.identifier); e.currentTarget.classList.add("dragging"); },
        ondragend: (e) => e.currentTarget.classList.remove("dragging"),
        onclick: () => go("#/issue/" + i.identifier) },
        h("div", { class: "top" }, priorityIcon(i.priority), i.identifier, h("span", { style: "margin-left:auto" }, avatar(i.assignee))),
        h("div", {}, i.title),
        i.labels.length > 0 && h("div", { class: "labels" }, labelChips(i))));
    }
    board.append(col);
  }
  return board;
}

// ---- issue detail ----------------------------------------------------------
async function renderIssue(route) {
  const ref = route.parts[1];
  renderSidebar(route);
  const issue = await api("/issues/" + ref);
  const team = teamById(issue.team_id);
  const projects = await api("/projects?team=" + team.key);
  const refresh = () => renderIssue(parseRoute());
  const patch = async (body) => { await api("/issues/" + ref, { method: "PATCH", body }); refresh(); };

  const title = h("input", { class: "title-input", value: issue.title,
    onblur: (e) => { const v = e.target.value.trim(); if (v && v !== issue.title) patch({ title: v }); } });
  const desc = mdBlock({ source: issue.description, html: issue.description_html, placeholder: "Add description…",
    onSave: (v) => patch({ description: v }) });

  const subInput = h("input", { class: "field", style: "width:100%", placeholder: "Add sub-issue… (Enter)",
    onkeydown: async (e) => {
      if (e.key !== "Enter" || !e.target.value.trim()) return;
      await api("/issues", { method: "POST", body: { team: team.key, title: e.target.value.trim(), parent_id: issue.id, project_id: issue.project_id } });
      refresh();
    } });

  const postComment = async () => {
    if (!commentBox.value.trim()) return;
    const me = currentUser();
    await api(`/issues/${ref}/comments`, { method: "POST", body: { body: commentBox.value, author_id: me ? me.id : null } });
    refresh();
  };
  const commentBox = h("textarea", { class: "field", placeholder: "Leave a comment… (Markdown supported)",
    onkeydown: (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) postComment(); } });
  const previewBox = h("div", { class: "comment md-view", style: "display:none;width:100%" });
  const previewBtn = h("button", { class: "btn", type: "button", onclick: async () => {
    if (previewBox.style.display !== "none") {
      previewBox.style.display = "none"; commentBox.style.display = ""; previewBtn.textContent = "Preview";
      return;
    }
    const { html } = await api("/markdown", { method: "POST", body: { text: commentBox.value } });
    if (html) previewBox.innerHTML = html; else previewBox.textContent = "Nothing to preview";
    previewBox.style.display = ""; commentBox.style.display = "none"; previewBtn.textContent = "Edit";
  } }, "Preview");
  const send = h("button", { class: "btn primary", onclick: postComment }, "Comment");

  const prop = (label, node) => h("div", { class: "prop" }, h("label", {}, label), node);
  const labelToggles = h("div", { style: "display:flex;flex-wrap:wrap;gap:4px" },
    state.meta.labels.map((l) => {
      const on = issue.labels.some((x) => x.id === l.id);
      return h("button", { class: "chip toggle" + (on ? " on" : ""),
        onclick: () => patch({ label_ids: on ? issue.labels.filter((x) => x.id !== l.id).map((x) => x.id) : [...issue.labels.map((x) => x.id), l.id] }) },
        h("span", { class: "dot", style: `background:${l.color}` }), l.name);
    }));

  $("#main").replaceChildren(
    h("div", { class: "breadcrumb" },
      h("button", { class: "back", onclick: () => history.length > 1 ? history.back() : go("#/issues") }, "← Back"),
      team.name, "›", issue.identifier,
      h("span", { class: "spacer", style: "flex:1" }),
      h("button", { class: "btn danger", onclick: async () => {
        if (!confirm(`Delete ${issue.identifier}?`)) return;
        await api("/issues/" + ref, { method: "DELETE" });
        go("#/issues");
      } }, "Delete")),
    h("div", { class: "detail" },
      h("div", { class: "content" },
        issue.parent_identifier && h("div", { class: "breadcrumb", style: "padding:0 0 8px;border:0" },
          "Sub-issue of ", h("a", { href: "#/issue/" + issue.parent_identifier, style: "text-decoration:underline" }, issue.parent_identifier)),
        title, desc,
        h("div", { class: "section-title" }, "Sub-issues", h("span", {}, issue.sub_issues.length)),
        issue.sub_issues.map((s) => issueRow(s)),
        subInput,
        h("div", { class: "section-title" }, "Activity"),
        issue.comments.map((c) => h("div", { class: "comment" },
          h("div", { class: "who" }, avatar(c.author), c.author ? c.author.name : "Unknown",
            h("span", {}, new Date(c.created_at).toLocaleString()),
            h("button", { class: "del", title: "Delete comment", onclick: async () => { await api("/comments/" + c.id, { method: "DELETE" }); refresh(); } }, "✕")),
          mdView(c.body_html, "body"))),
        h("div", { class: "composer" }, commentBox, previewBox, h("div", { style: "display:flex;gap:8px" }, previewBtn, send))),
      h("div", { class: "props" },
        prop("Status", select(team.statuses.map((s) => [s.id, s.name]), issue.status.id, (v) => patch({ status_id: +v }))),
        prop("Priority", select(state.meta.priorities.map((p) => [p.value, p.name]), issue.priority, (v) => patch({ priority: +v }))),
        prop("Assignee", select([["", "Unassigned"], ...state.meta.users.map((u) => [u.id, u.name])], issue.assignee ? issue.assignee.id : "", (v) => patch({ assignee_id: v ? +v : null }))),
        prop("Project", select([["", "No project"], ...projects.map((p) => [p.id, p.name])], issue.project_id || "", (v) => patch({ project_id: v ? +v : null, milestone_id: null }))),
        prop("Estimate", h("input", { class: "field", type: "number", min: "0", value: issue.estimate ?? "",
          onchange: (e) => patch({ estimate: e.target.value === "" ? null : +e.target.value }) })),
        prop("Due date", h("input", { class: "field", type: "date", value: issue.due_date || "",
          onchange: (e) => patch({ due_date: e.target.value || null }) })),
        prop("Labels", labelToggles))));
}

// ---- projects --------------------------------------------------------------
async function renderProjects(route) {
  renderSidebar(route);
  const projects = await api("/projects" + (state.team ? "?team=" + state.team : ""));
  $("#main").replaceChildren(
    h("div", { class: "page-header" }, h("h1", {}, "Projects"),
      h("button", { class: "btn primary", style: "margin-left:auto", onclick: () => openProjectModal() }, "New project")),
    projects.length === 0
      ? h("div", { class: "empty" }, "No projects yet.")
      : h("div", { class: "project-grid" }, projects.map((p) =>
          h("div", { class: "project-card", onclick: () => go("#/project/" + p.id) },
            h("div", { style: "display:flex;gap:8px;align-items:center" },
              h("span", { class: "chip" }, h("span", { class: "dot", style: `background:${p.color}` }), p.status),
              h("strong", {}, p.name), h("span", { style: "margin-left:auto" }, avatar(p.lead))),
            h("div", { class: "sum" }, p.summary),
            h("div", { class: "bar" }, h("span", { style: `width:${p.progress.percent}%` })),
            h("div", { style: "display:flex;justify-content:space-between;color:var(--muted);margin-top:6px" },
              h("span", {}, `${p.progress.completed}/${p.progress.total} done`),
              h("span", {}, p.target_date ? "Target " + fmtDate(p.target_date) : ""))))));
}

async function renderProject(route) {
  const id = route.parts[1];
  renderSidebar(route);
  const p = await api("/projects/" + id);
  const issues = await api("/issues?project_id=" + id + "&order_by=priority");
  const team = teamById(p.team_id);
  const refresh = () => renderProject(parseRoute());
  const patch = async (body) => { await api("/projects/" + id, { method: "PATCH", body }); refresh(); };

  const field = (label, node) => h("div", { class: "prop" }, h("label", {}, label), node);
  const desc = mdBlock({ source: p.description, html: p.description_html, placeholder: "Write a project description…",
    onSave: (v) => patch({ description: v }) });

  const msName = h("input", { class: "field", placeholder: "New milestone name" });
  const msDate = h("input", { class: "field", type: "date" });
  const docTitle = h("input", { class: "field", placeholder: "New document title" });

  $("#main").replaceChildren(
    h("div", { class: "breadcrumb" }, h("button", { class: "back", onclick: () => go("#/projects") }, "← Projects"), p.name,
      h("span", { style: "flex:1" }),
      h("button", { class: "btn danger", onclick: async () => {
        if (!confirm(`Delete project "${p.name}"? Its issues are kept.`)) return;
        await api("/projects/" + id, { method: "DELETE" });
        go("#/projects");
      } }, "Delete")),
    h("div", { class: "project-page" },
      h("input", { class: "title-input", value: p.name, onblur: (e) => { const v = e.target.value.trim(); if (v && v !== p.name) patch({ name: v }); } }),
      h("input", { class: "title-input", style: "font-size:14px;font-weight:400;color:var(--muted)", placeholder: "Short summary", value: p.summary,
        onblur: (e) => { if (e.target.value !== p.summary) patch({ summary: e.target.value }); } }),
      h("div", { class: "project-props" },
        field("Status", select(state.meta.project_statuses.map((s) => [s, s]), p.status, (v) => patch({ status: v }))),
        field("Priority", select(state.meta.priorities.map((x) => [x.value, x.name]), p.priority, (v) => patch({ priority: +v }))),
        field("Lead", select([["", "No lead"], ...state.meta.users.map((u) => [u.id, u.name])], p.lead ? p.lead.id : "", (v) => patch({ lead_id: v ? +v : null }))),
        field("Start", h("input", { class: "field", type: "date", value: p.start_date || "", onchange: (e) => patch({ start_date: e.target.value || null }) })),
        field("Target", h("input", { class: "field", type: "date", value: p.target_date || "", onchange: (e) => patch({ target_date: e.target.value || null }) }))),
      h("div", { class: "bar" }, h("span", { style: `width:${p.progress.percent}%` })),
      h("div", { style: "color:var(--muted);margin:6px 0" }, `${p.progress.percent}% complete · ${p.progress.completed}/${p.progress.total} issues · ${p.progress.started} in progress`),
      desc,

      h("div", { class: "section-title" }, "Milestones"),
      p.milestones.map((ms) => h("div", { class: "ms-row" },
        h("strong", {}, ms.name), h("span", { style: "color:var(--muted)" }, ms.target_date ? fmtDate(ms.target_date) : "No date"),
        h("span", { style: "margin-left:auto;color:var(--muted)" }, `${ms.done_count}/${ms.issue_count}`),
        h("button", { class: "back", onclick: async () => { await api("/milestones/" + ms.id, { method: "DELETE" }); refresh(); } }, "✕"))),
      h("div", { class: "ms-row" }, msName, msDate, h("button", { class: "btn", onclick: async () => {
        if (!msName.value.trim()) return;
        await api(`/projects/${id}/milestones`, { method: "POST", body: { name: msName.value.trim(), target_date: msDate.value || null } });
        refresh();
      } }, "Add")),

      h("div", { class: "section-title" }, "Documents"),
      p.documents.map((d) => documentEditor(d, refresh)),
      h("div", { class: "ms-row" }, docTitle, h("button", { class: "btn", onclick: async () => {
        if (!docTitle.value.trim()) return;
        await api("/documents", { method: "POST", body: { title: docTitle.value.trim(), project_id: +id } });
        refresh();
      } }, "Add")),

      h("div", { class: "section-title" }, "Issues", h("span", {}, issues.length),
        h("button", { class: "btn", onclick: () => openIssueModal({ project: p.id, team: team.key }) }, "New issue")),
      issues.length ? listView(issues, { defaults: { project: p.id, team: team.key } }) : h("div", { class: "empty" }, "No issues in this project.")));
}

function documentEditor(d, refresh) {
  return h("div", { class: "doc" },
    h("div", { class: "doc-row" }, h("strong", {}, d.title),
      h("button", { class: "back", style: "margin-left:auto", onclick: async () => { await api("/documents/" + d.id, { method: "DELETE" }); refresh(); } }, "✕")),
    mdBlock({ source: d.content, html: d.content_html, placeholder: "Empty document — click to edit", tall: true,
      onSave: async (v) => { await api("/documents/" + d.id, { method: "PATCH", body: { content: v } }); refresh(); } }));
}

// ---- modals ----------------------------------------------------------------
function closeModal() { $("#modal-root").replaceChildren(); }

function modal(title, bodyNodes, actions) {
  const overlay = h("div", { class: "overlay", onmousedown: (e) => { if (e.target === overlay) closeModal(); } },
    h("div", { class: "modal", role: "dialog", "aria-label": title }, h("h2", {}, title), ...bodyNodes, h("div", { class: "actions" }, actions)));
  $("#modal-root").replaceChildren(overlay);
  return overlay;
}

function openIssueModal(defaults = {}) {
  if (!state.meta.teams.length) return openTeamModal();
  const key = defaults.team || teamKey();
  let team = state.meta.teams.find((t) => t.key === key) || state.meta.teams[0];
  const chosenLabels = new Set();

  const title = h("input", { class: "title-input", placeholder: "Issue title", autofocus: true });
  const desc = h("textarea", { class: "field", placeholder: "Add description…" });
  const teamSel = select(state.meta.teams.map((t) => [t.key, t.name]), team.key, () => {}, "field");
  const statusSel = h("select", { class: "field" });
  const prioSel = select(state.meta.priorities.map((p) => [p.value, p.name]), 0, () => {});
  const assigneeSel = select([["", "Unassigned"], ...state.meta.users.map((u) => [u.id, u.name])], "", () => {});
  const projectSel = h("select", { class: "field" });
  const labelWrap = h("div", { class: "row2" }, state.meta.labels.map((l) =>
    h("button", { class: "chip toggle", type: "button", onclick: (e) => {
      chosenLabels.has(l.id) ? chosenLabels.delete(l.id) : chosenLabels.add(l.id);
      e.currentTarget.classList.toggle("on");
    } }, h("span", { class: "dot", style: `background:${l.color}` }), l.name)));

  async function fillTeamDependent() {
    team = state.meta.teams.find((t) => t.key === teamSel.value);
    const wanted = defaults.status || "Backlog";
    statusSel.replaceChildren(...team.statuses.map((s) => h("option", { value: s.id, selected: s.name === wanted }, s.name)));
    const projects = await api("/projects?team=" + team.key);
    projectSel.replaceChildren(h("option", { value: "" }, "No project"),
      ...projects.map((p) => h("option", { value: p.id, selected: p.id === defaults.project }, p.name)));
  }
  teamSel.onchange = fillTeamDependent;
  fillTeamDependent();

  const submit = async () => {
    if (!title.value.trim()) return title.focus();
    const created = await api("/issues", { method: "POST", body: {
      team: teamSel.value, title: title.value.trim(), description: desc.value,
      status_id: +statusSel.value, priority: +prioSel.value,
      assignee_id: assigneeSel.value ? +assigneeSel.value : null,
      project_id: projectSel.value ? +projectSel.value : null,
      label_ids: [...chosenLabels],
    } });
    closeModal();
    toast(`Created ${created.identifier}`);
    route();
  };

  const overlay = modal("New issue", [title, desc, h("div", { class: "row2" }, teamSel, statusSel, prioSel, assigneeSel, projectSel), labelWrap], [
    h("button", { class: "btn", onclick: closeModal }, "Cancel"),
    h("button", { class: "btn primary", onclick: submit }, "Create issue"),
  ]);
  overlay.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submit(); });
  title.focus();
}

function openTeamModal() {
  const name = h("input", { class: "field", placeholder: "Team name" });
  const key = h("input", { class: "field", placeholder: "Key (e.g. ENG)", maxlength: "10" });
  const submit = async () => {
    if (!name.value.trim() || !key.value.trim()) return;
    await api("/teams", { method: "POST", body: { name: name.value.trim(), key: key.value.trim() } });
    await loadMeta();
    closeModal();
    go("#/issues?team=" + key.value.trim().toUpperCase());
    route();
  };
  modal("New team", [name, key], [
    h("button", { class: "btn", onclick: closeModal }, "Cancel"),
    h("button", { class: "btn primary", onclick: submit }, "Create team"),
  ]);
  name.focus();
}

function openProjectModal() {
  const name = h("input", { class: "title-input", placeholder: "Project name" });
  const summary = h("input", { class: "field", placeholder: "Short summary" });
  const teamSel = select(state.meta.teams.map((t) => [t.key, t.name]), teamKey(), () => {});
  const statusSel = select(state.meta.project_statuses.map((s) => [s, s]), "planned", () => {});
  const lead = select([["", "No lead"], ...state.meta.users.map((u) => [u.id, u.name])], "", () => {});
  const start = h("input", { class: "field", type: "date" });
  const target = h("input", { class: "field", type: "date" });
  const submit = async () => {
    if (!name.value.trim()) return name.focus();
    const p = await api("/projects", { method: "POST", body: {
      team: teamSel.value, name: name.value.trim(), summary: summary.value, status: statusSel.value,
      lead_id: lead.value ? +lead.value : null, start_date: start.value || null, target_date: target.value || null,
    } });
    closeModal();
    go("#/project/" + p.id);
  };
  modal("New project", [name, summary, h("div", { class: "row2" }, teamSel, statusSel, lead), h("div", { class: "row2" }, start, target)], [
    h("button", { class: "btn", onclick: closeModal }, "Cancel"),
    h("button", { class: "btn primary", onclick: submit }, "Create project"),
  ]);
  name.focus();
}

// ---- router & shortcuts ----------------------------------------------------
async function route() {
  const r = parseRoute();
  const [page] = r.parts;
  try {
    if (page === "issue") await renderIssue(r);
    else if (page === "projects") await renderProjects(r);
    else if (page === "project") await renderProject(r);
    else await renderIssues(r);
  } catch (e) {
    if (!$("#toast.error")) toast(String(e.message || e), true);
  }
}

document.addEventListener("keydown", (e) => {
  const tag = (e.target.tagName || "").toLowerCase();
  const typing = ["input", "textarea", "select"].includes(tag) || e.target.isContentEditable;
  if (e.key === "Escape") { closeModal(); if (typing) e.target.blur(); return; }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "c") { e.preventDefault(); openIssueModal(); }
  else if (e.key === "/") { const s = $("#search"); if (s) { e.preventDefault(); s.focus(); } }
});

window.addEventListener("hashchange", route);

(async function init() {
  const theme = store.get("theme", "");
  if (theme) document.documentElement.dataset.theme = theme;
  await loadMeta();
  route();
})();
