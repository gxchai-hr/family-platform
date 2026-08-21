/* 家庭日常管理平台 前端 */
const BASE = "";
let token = localStorage.getItem("fp_token") || null;
let me = null;
let view = "dashboard";
let calY = new Date().getFullYear(), calM = new Date().getMonth() + 1;   // 共享日历当前月
let dashY = new Date().getFullYear(), dashM = new Date().getMonth() + 1; // 仪表盘月历当前月
let editingRecipeId = null; // 当前正在编辑的食谱 id（null 表示新建）
let editingDiaryId = null;  // 当前正在编辑的日记 id（null 表示新建）
let _evById = {};            // 日程/纪念日按 id 缓存（供详情弹窗读取）

function authHeader() {
  return token ? { Authorization: "Bearer " + token } : {};
}
async function api(method, path, body, form) {
  const opts = { method, headers: authHeader() };
  if (form) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(BASE + path, opts);
  if (res.status === 401) {
    logout();
    throw new Error("登录失效，请重新登录");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "请求失败");
  return data;
}
function esc(s) {
  return (s == null ? "" : String(s)).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
  );
}
function todayStr() {
  const d = new Date();
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
}
function fmtDate(d) {
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
}
function isOwner(ownerId) {
  return me.role === "admin" || me.id === ownerId;
}

/* 同一天内排序：无时间的放最前，其余按时间升序 */
function sortByTime(arr) {
  arr.sort((a, b) => {
    const ta = a.time || "", tb = b.time || "";
    if (!ta && !tb) return 0;
    if (!ta) return -1;
    if (!tb) return 1;
    return ta.localeCompare(tb);
  });
}

/* 月历单元格里的活动标签：时间 参与人 主题（如 08:00 张三 参加英语培训） */
function eventLabel(e) {
  const parts = [];
  if (e.time) parts.push(e.time);
  if (e.participants) parts.push(e.participants);
  parts.push(e.title || "");
  return parts.join(" ");
}

/* ---------- 弹窗（详情 / 改密码 / 重置密码） ---------- */
function openModal(title, bodyHtml, wide) {
  closeModal();
  const m = document.createElement("div");
  m.id = "modal";
  // 注意：modal-box 必须嵌套在 modal-mask 内，flex 居中才会作用于它
  m.innerHTML = `<div class="modal-mask" onclick="if(event.target===this)closeModal()">
    <div class="modal-box ${wide ? "wide" : ""}"><div class="modal-title">${title}</div><div class="modal-body">${bodyHtml}</div></div>
  </div>`;
  document.body.appendChild(m);
}
function closeModal() {
  const m = document.getElementById("modal");
  if (m) m.remove();
}

/* ---------- 极简 Markdown 渲染 ---------- */
function md2html(md) {
  if (!md) return "";
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const safeUrl = (u) => u.replace(/"/g, "%22").replace(/[<>]/g, "");
  const inline = (s) => {
    let t = esc(s);
    t = t.replace(/`([^`]+)`/g, (m, c) => `<code>${esc(c)}</code>`);
    t = t.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (m, a, u) => `<img src="${safeUrl(u)}" alt="${esc(a)}" style="max-width:100%;border-radius:8px;margin:6px 0;">`);
    t = t.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (m, tx, u) => `<a href="${safeUrl(u)}" target="_blank" rel="noopener">${esc(tx)}</a>`);
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    t = t.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    return t;
  };
  const lines = md.split(/\r?\n/);
  let html = "", i = 0, ulOpen = false, olOpen = false;
  const closeLists = () => { if (ulOpen) { html += "</ul>"; ulOpen = false; } if (olOpen) { html += "</ol>"; olOpen = false; } };
  while (i < lines.length) {
    let line = lines[i];
    if (/^```/.test(line)) {
      let code = ""; i++;
      while (i < lines.length && !/^```/.test(lines[i])) { code += lines[i] + "\n"; i++; }
      i++; closeLists(); html += `<pre><code>${esc(code)}</code></pre>`; continue;
    }
    if (/^\s*$/.test(line)) { closeLists(); i++; continue; }
    let h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { closeLists(); const lv = h[1].length; html += `<h${lv}>${inline(h[2])}</h${lv}>`; i++; continue; }
    let ul = line.match(/^\s*[-*]\s+(.*)$/);
    if (ul) { if (olOpen) { html += "</ol>"; olOpen = false; } if (!ulOpen) { html += "<ul>"; ulOpen = true; } html += `<li>${inline(ul[1])}</li>`; i++; continue; }
    let ol = line.match(/^\s*\d+\.\s+(.*)$/);
    if (ol) { if (ulOpen) { html += "</ul>"; ulOpen = false; } if (!olOpen) { html += "<ol>"; olOpen = true; } html += `<li>${inline(ol[1])}</li>`; i++; continue; }
    let para = line; i++;
    while (i < lines.length && !/^\s*$/.test(lines[i]) && !/^(#{1,4})\s/.test(lines[i]) && !/^\s*[-*]\s/.test(lines[i]) && !/^\s*\d+\.\s/.test(lines[i]) && !/^```/.test(lines[i])) { para += "<br>" + lines[i]; i++; }
    closeLists(); html += `<p>${inline(para)}</p>`;
  }
  closeLists();
  return html;
}

/* 把类别选项填充到 select */
async function fillCat(selectEl, kind) {
  if (!selectEl) return;
  try {
    const cats = await api("GET", "/api/categories?kind=" + kind);
    selectEl.innerHTML = cats.map((c) => `<option>${esc(c.name)}</option>`).join("") ||
      `<option>其他</option>`;
  } catch (e) {
    selectEl.innerHTML = `<option>其他</option>`;
  }
}

/* ---------- 登录 ---------- */
async function init() {
  if (token) {
    try {
      me = await api("GET", "/api/me");
      renderShell();
      return;
    } catch (e) {
      token = null;
      localStorage.removeItem("fp_token");
    }
  }
  showLogin();
}
function showLogin() {
  document.getElementById("root").innerHTML = `
    <div class="login-wrap"><div class="card login-box">
      <h1>家庭日常管理平台</h1>
      <div class="sub">请登录以继续</div>
      <div class="form-inline" style="grid-template-columns:1fr;">
        <input id="u" placeholder="用户名">
        <input id="p" type="password" placeholder="密码">
        <button class="btn primary" onclick="doLogin()">登录</button>
      </div>
      <div id="lerr" class="muted"></div>
    </div></div>`;
}
async function doLogin() {
  const username = document.getElementById("u").value.trim();
  const password = document.getElementById("p").value;
  try {
    const r = await api("POST", "/api/login?username=" + encodeURIComponent(username) + "&password=" + encodeURIComponent(password));
    token = r.token;
    me = r.user;
    localStorage.setItem("fp_token", token);
    renderShell();
  } catch (e) {
    document.getElementById("lerr").textContent = e.message;
  }
}
function logout() {
  token = null;
  me = null;
  localStorage.removeItem("fp_token");
  showLogin();
}

/* ---------- 框架 ---------- */
const NAV = [
  { id: "dashboard", name: "仪表盘" },
  { id: "notices", name: "公告板" },
  { id: "wishes", name: "心愿单" },
  { id: "calendar", name: "共享日历" },
  { id: "anniversary", name: "纪念日" },
  { id: "shopping", name: "购物清单" },
  { id: "recipes", name: "食谱文档" },
  { id: "photos", name: "家庭相册" },
  { id: "diary", name: "日记本" },
  { id: "luckymoney", name: "压岁钱/红包" },
];
function renderShell() {
  const adminItems = me.role === "admin" ? [
    { id: "categories", name: "类别管理" },
    { id: "users", name: "用户管理" },
  ] : [];
  const nav = [].concat(NAV, adminItems)
    .map((n) => `<a class="nav-item ${n.id === view ? "active" : ""}" onclick="setView('${n.id}')">${n.name}</a>`)
    .join("");
  document.getElementById("root").innerHTML = `
    <div class="layout">
      <aside class="sidebar">
        <div class="brand">家庭中心</div>
        <div class="sub">${esc(me.display_name)} 的家</div>
        ${nav}
        <div class="nav-sep"></div>
        <a class="nav-item" onclick="openChangePw()">修改密码</a>
        <a class="nav-item" onclick="logout()">退出登录</a>
      </aside>
      <main class="content">
        <div class="topbar"><h2 id="page-title"></h2>
          <div class="userbox"><b>${esc(me.display_name)}</b> · ${roleText(me.role)}</div>
        </div>
        <div id="view"></div>
      </main>
    </div>`;
  setView(view);
}
function roleText(r) {
  return { admin: "管理员", member: "家庭成员", guest: "访客" }[r] || r;
}
function setView(v) {
  view = v;
  document.querySelectorAll(".nav-item").forEach((e) => e.classList.remove("active"));
  renderView(v);
}
async function renderView(v) {
  document.getElementById("page-title").textContent = pageName(v);
  const el = document.getElementById("view");
  try {
    if (v === "dashboard") return renderDashboard(el);
    if (v === "notices") return renderNotices(el);
    if (v === "wishes") return renderWishes(el);
    if (v === "calendar") return renderCalendar(el);
    if (v === "anniversary") return renderAnniversary(el);
    if (v === "shopping") return renderShopping(el);
    if (v === "recipes") return renderRecipes(el);
    if (v === "photos") return renderPhotos(el);
    if (v === "diary") return renderDiary(el);
    if (v === "luckymoney") return renderLucky(el);
    if (v === "categories") return renderCategories(el);
    if (v === "users") return renderUsers(el);
  } catch (e) {
    el.innerHTML = `<div class="muted">加载失败：${esc(e.message)}</div>`;
  }
}
function pageName(v) {
  const m = { dashboard: "仪表盘", notices:  "公告板", wishes: "心愿单", calendar: "共享日历",
    anniversary: "纪念日", shopping: "购物清单", recipes: "食谱文档", photos: "家庭相册",
    diary: "日记本", luckymoney: "压岁钱 / 红包", categories: "类别管理", users: "用户管理" };
  return m[v] || "";
}

/* ---------- 月历网格（日历页 / 仪表盘共用） ---------- */
function renderMonthGrid(box, y, m, eventsByDate, clickable) {
  const monthNames = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"];
  const first = new Date(y, m - 1, 1);
  const startDow = first.getDay();
  const days = new Date(y, m, 0).getDate();
  let html = `<div class="cal-title">${y} 年 ${monthNames[m - 1]}</div><div class="cal-head">`;
  ["日", "一", "二", "三", "四", "五", "六"].forEach((d) => (html += `<div>${d}</div>`));
  html += `</div><div class="cal-grid">`;
  for (let i = 0; i < startDow; i++) html += `<div class="cal-cell empty"></div>`;
  const tdy = todayStr();
  for (let d = 1; d <= days; d++) {
    const ds = `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    const evs = eventsByDate[ds] || [];
    const evHtml = evs.map((e) => {
      const cls = "cal-ev " + (e.type || "event") + (clickable ? " clickable" : "");
      const onClick = clickable ? `onclick="openEvent(${e.id},'${ds}')"` : "";
      const tip = `${e.title}｜参与人:${e.participants || "—"}｜时间:${e.time || "—"}`;
      return `<div class="${cls}" ${onClick} title="${esc(tip)}">
        <div class="cal-ev-title">${esc(eventLabel(e))}</div></div>`;
    }).join("");
    const cls = ds === tdy ? "cal-cell today" : "cal-cell";
    html += `<div class="${cls}"><div class="cal-day">${d}</div>${evHtml}</div>`;
  }
  html += `</div>`;
  box.innerHTML = html;
}

/* ---------- 日程/纪念日详情弹窗（含删除选项） ---------- */
function openEvent(id, date) {
  const e = _evById[id];
  if (!e) return;
  const repText = { none: "不重复", daily: "每天", weekly: "每周", monthly: "每月", yearly: "每年" }[e.repeat_type || "none"] || "不重复";
  const canDel = isOwner(e.user_id);
  const body = `
    <div class="event-detail">
      <div><b>主题：</b>${esc(e.title)}</div>
      ${e.date ? `<div><b>日期：</b>${esc(e.date)}${date && date !== e.date ? `（本条：${esc(date)}）` : ""}</div>` : ""}
      ${e.time ? `<div><b>时间：</b>${esc(e.time)}</div>` : ""}
      <div><b>参与人：</b>${esc(e.participants || "—")}</div>
      <div><b>类型：</b>${e.type === "anniversary" ? "纪念日" : "日程"}　<b>重复：</b>${repText}</div>
      ${e.note ? `<div><b>备注：</b>${esc(e.note)}</div>` : ""}
    </div>
    <div class="row" style="margin-top:16px;justify-content:flex-end;">
      <button class="btn" onclick="closeModal()">关闭</button>
      ${canDel ? `<button class="btn danger" onclick="excludeEvent(${id},'${date}')">只删本条（${esc(date)}）</button>
      <button class="btn danger" onclick="deleteEventAll(${id})">删除全部</button>` : ""}
    </div>`;
  openModal(e.type === "anniversary" ? "纪念日详情" : "日程详情", body);
}
async function excludeEvent(id, date) {
  closeModal();
  if (!confirm("仅删除 " + date + " 这一条，其余重复保留？")) return;
  await api("POST", "/api/events/" + id + "/exclude", { date });
  if (view === "calendar") return refreshCalendar();
  if (view === "dashboard") return renderDashMonth(document.getElementById("dash-cal"));
}
async function deleteEventAll(id) {
  closeModal();
  if (!confirm("确认删除整条（含所有重复）？")) return;
  await api("DELETE", "/api/events/" + id);
  if (view === "calendar") return refreshCalendar();
  if (view === "dashboard") return renderDashMonth(document.getElementById("dash-cal"));
  if (view === "anniversary") return renderAnniversary(document.getElementById("view"));
}

/* ---------- 仪表盘 ---------- */
async function renderDashboard(el) {
  const [notices, wishes, shop] = await Promise.all([
    api("GET", "/api/notices"),
    api("GET", "/api/wishes"),
    api("GET", "/api/shopping"),
  ]);
  const openWishes = wishes.filter((w) => w.status === "想要");
  el.innerHTML = `
    <div class="two-col">
      <div class="card">
        <div class="title-row"><b>最新公告</b><button class="btn" onclick="setView('notices')">查看全部</button></div>
        ${notices.slice(0, 5).map((n) => `<div class="list-item"><div>${esc(n.title)} ${n.pinned ? '<span class="badge amber">置顶</span>' : ""}</div><div class="meta">${esc(n.author)} · ${esc(n.created_at)}</div></div>`).join("") || '<div class="muted">暂无</div>'}
      </div>
      <div class="card">
        <div class="title-row"><b>购物清单（待购）</b><button class="btn" onclick="setView('shopping')">去添加</button></div>
        ${shop.filter((s) => !s.done).slice(0, 6).map((s) => `<div class="list-item"><div>${esc(s.name)} ${s.quantity ? "(" + esc(s.quantity) + ")" : ""}</div><div class="meta">${esc(s.added_by_name)}</div></div>`).join("") || '<div class="muted">暂无</div>'}
      </div>
    </div>
    <div class="card" style="margin-top:16px;">
      <div class="title-row"><b>未实现心愿（详细）</b><button class="btn" onclick="setView('wishes')">全部心愿</button></div>
      ${openWishes.map((w) => `
        <div class="list-item">
          <div><b>${esc(w.content)}</b>
            <span class="badge ${w.priority === "高" ? "pink" : "gray"}">${esc(w.priority)}</span>
            <span class="badge blue">未实现</span></div>
          <div class="meta">${esc(w.proposer)}${w.link ? ' · <a href="' + esc(w.link) + '" target="_blank">链接</a>' : ""}</div>
        </div>`).join("") || '<div class="muted">太棒了，所有心愿都已实现 🎉</div>'}
    </div>
    <div class="card" style="margin-top:16px;">
      <div class="title-row">
        <b>本月日历（日程 · 纪念日）</b>
        <span>
          <button class="btn" onclick="dashShift(-1)">‹ 上月</button>
          <button class="btn" onclick="dashShift(1)">下月 ›</button>
        </span>
      </div>
      <div id="dash-cal"></div>
    </div>`;
  renderDashMonth(document.getElementById("dash-cal"));
}
async function dashShift(delta) {
  dashM += delta;
  if (dashM < 1) { dashM = 12; dashY--; }
  if (dashM > 12) { dashM = 1; dashY++; }
  renderDashMonth(document.getElementById("dash-cal"));
}
async function renderDashMonth(box) {
  box.innerHTML = '<div class="muted">加载中…</div>';
  const [events, anns] = await Promise.all([
    api("GET", "/api/events?type=event"),
    api("GET", "/api/events?type=anniversary"),
  ]);
  const map = {};
  // 日程：通过 expandEvent 展开（自动尊重 exceptions 单条排除）
  events.forEach((e) => {
    _evById[e.id] = e;
    expandEvent(e, dashY, dashM).forEach((ds) => {
      (map[ds] = map[ds] || []).push(e);
    });
  });
  // 纪念日：按 month-day 投影到本年/次年，并尊重 exceptions
  const yNow = new Date().getFullYear();
  anns.forEach((a) => {
    _evById[a.id] = a;
    const exSet = new Set((a.exceptions || "").split(",").map((s) => s.trim()).filter(Boolean));
    const mmdd = a.date.slice(5);
    let yr = yNow;
    const thisYearStr = `${yNow}-${mmdd}`;
    if (new Date(thisYearStr + "T00:00:00") < new Date(todayStr() + "T00:00:00")) yr = yNow + 1;
    const key = `${yr}-${mmdd}`;
    if (!exSet.has(key)) (map[key] = map[key] || []).push(a);
  });
  // 同一天内按时间排序（无时间置前）
  for (const k in map) sortByTime(map[k]);
  renderMonthGrid(box, dashY, dashM, map, true);
}

/* ---------- 公告板（到期 + 归档 + 权限） ---------- */
async function renderNotices(el) {
  const list = await api("GET", "/api/notices");
  const archived = await api("GET", "/api/notices/archived");
  el.innerHTML = `
    <div class="card">
      <div class="title-row"><b>发布新公告</b></div>
      <div class="form-inline">
        <input id="n_title" placeholder="标题">
        <select id="n_cat"><option>家庭事务</option><option>缴费</option><option>提醒</option><option>其他</option></select>
        <label style="display:flex;align-items:center;gap:6px;flex:none;"><input type="checkbox" id="n_pin"> 置顶</label>
        <input id="n_exp" type="date" title="到期日期（可选，到期当天24时后自动归档）">
        <button class="btn primary" onclick="addNotice()" style="flex:none;">发布</button>
      </div>
      <textarea id="n_body" placeholder="正文（可选）" style="width:100%;min-height:60px;margin-bottom:14px;"></textarea>
    </div>
    <div id="nlist"></div>
    <div class="card" style="margin-top:16px;">
      <div class="title-row"><b>已归档公告（${archived.length}）</b></div>
      <div id="narch"></div>
    </div>`;
  renderNoticeList(document.getElementById("nlist"), list);
  document.getElementById("narch").innerHTML = archived.map((n) => `
    <div class="list-item">
      <div><b>${esc(n.title)}</b> <span class="badge gray">已归档</span> ${n.category ? `<span class="badge gray">${esc(n.category)}</span>` : ""}</div>
      <div class="meta">${esc(n.author)} · ${esc(n.created_at)}${n.expired_at ? " · 到期 " + esc(n.expired_at) : ""}</div>
      ${isOwner(n.author_id) ? `<div style="margin-top:8px;"><button class="btn" onclick="unarchiveNotice(${n.id})">恢复</button><button class="btn danger" onclick="delNotice(${n.id})">删除</button></div>` : ""}
    </div>`).join("") || '<div class="muted">暂无归档</div>';
}
function renderNoticeList(box, list) {
  box.innerHTML = list.map((n) => `
    <div class="list-item">
      <div><b>${esc(n.title)}</b> ${n.pinned ? '<span class="badge amber">置顶</span>' : ""}
        <span class="badge gray">${esc(n.category)}</span></div>
      <div class="meta">${esc(n.author)} · ${esc(n.created_at)}${n.expired_at ? " · 到期 " + esc(n.expired_at) : ""}</div>
      ${n.body ? `<div style="margin-top:6px;">${esc(n.body)}</div>` : ""}
      ${isOwner(n.author_id) ? `<div style="margin-top:8px;"><button class="btn" onclick="archiveNotice(${n.id})">归档</button><button class="btn danger" onclick="delNotice(${n.id})">删除</button></div>` : ""}
    </div>`).join("") || '<div class="muted">暂无公告</div>';
}
async function addNotice() {
  const title = document.getElementById("n_title").value.trim();
  if (!title) return alert("请填写标题");
  await api("POST", "/api/notices", {
    title, body: document.getElementById("n_body").value,
    category: document.getElementById("n_cat").value,
    pinned: document.getElementById("n_pin").checked ? 1 : 0,
    expired_at: document.getElementById("n_exp").value || null,
  });
  renderNotices(document.getElementById("view"));
}
async function archiveNotice(id) {
  if (!confirm("确认归档该公告？")) return;
  await api("POST", "/api/notices/" + id + "/archive");
  renderNotices(document.getElementById("view"));
}
async function unarchiveNotice(id) {
  await api("POST", "/api/notices/" + id + "/unarchive");
  renderNotices(document.getElementById("view"));
}
async function delNotice(id) {
  if (!confirm("确认删除？")) return;
  await api("DELETE", "/api/notices/" + id);
  renderNotices(document.getElementById("view"));
}

/* ---------- 心愿单（去价格 + 标记为已实现 + 权限） ---------- */
async function renderWishes(el) {
  const list = await api("GET", "/api/wishes");
  el.innerHTML = `
    <div class="card">
      <div class="title-row"><b>添加心愿</b></div>
      <div class="form-inline">
        <input id="w_c" placeholder="想要什么">
        <select id="w_p"><option>高</option><option selected>中</option><option>低</option></select>
        <input id="w_link" placeholder="链接(可选)">
        <button class="btn primary" onclick="addWish()" style="flex:none;">添加</button>
      </div>
    </div>
    <div id="wlist"></div>`;
  renderWishList(document.getElementById("wlist"), list);
}
function renderWishList(box, list) {
  box.innerHTML = list.map((w) => `
    <div class="list-item">
      <div><b>${esc(w.content)}</b>
        <span class="badge ${w.priority === "高" ? "pink" : "gray"}">${esc(w.priority)}</span>
        <span class="badge ${w.status === "想要" ? "blue" : w.status === "已实现" ? "green" : "gray"}">${esc(w.status)}</span>
      </div>
      <div class="meta">${esc(w.proposer)}${w.link ? ' · <a href="' + esc(w.link) + '" target="_blank">链接</a>' : ""}</div>
      ${isOwner(w.user_id) ? `<div style="margin-top:8px;">
        ${w.status !== "已实现" ? `<button class="btn" onclick="setWish(${w.id},'已实现')">标记为已实现</button>` : ""}
        ${w.status !== "已放弃" ? `<button class="btn" onclick="setWish(${w.id},'已放弃')">放弃</button>` : ""}
        <button class="btn danger" onclick="delWish(${w.id})">删除</button>
      </div>` : ""}
    </div>`).join("") || '<div class="muted">暂无心愿</div>';
}
async function addWish() {
  const content = document.getElementById("w_c").value.trim();
  if (!content) return alert("请填写内容");
  await api("POST", "/api/wishes", {
    content, priority: document.getElementById("w_p").value,
    link: document.getElementById("w_link").value || null,
  });
  const list = await api("GET", "/api/wishes");
  renderWishList(document.getElementById("wlist"), list);
}
async function setWish(id, status) {
  await api("PUT", "/api/wishes/" + id, { status });
  const list = await api("GET", "/api/wishes");
  renderWishList(document.getElementById("wlist"), list);
}
async function delWish(id) {
  if (!confirm("确认删除？")) return;
  await api("DELETE", "/api/wishes/" + id);
  const list = await api("GET", "/api/wishes");
  renderWishList(document.getElementById("wlist"), list);
}

/* ---------- 共享日历（月视图 + 重复，仅日程） ---------- */
async function renderCalendar(el) {
  el.innerHTML = `
    <div class="card">
      <div class="title-row"><b>添加日程</b></div>
      <div class="form-inline">
        <div class="field"><label>主题</label><input id="e_title" placeholder="主题"></div>
        <div class="field"><label>活动时间</label><input id="e_date" type="date"></div>
        <div class="field"><label>时间（可选）</label><input id="e_time" placeholder="时间(可选)"></div>
        <div class="field"><label>参与人（可选）</label><input id="e_part" placeholder="参与人(可选)"></div>
      </div>
      <div class="form-inline">
        <div class="field"><label>重复</label><select id="e_rep"><option value="none">不重复</option><option value="daily">每天</option><option value="weekly">每周</option><option value="monthly">每月</option><option value="yearly">每年</option></select></div>
        <div class="field"><label>重复截止时间</label><input id="e_until" type="date"></div>
        <div class="field"><label>重复次数（可选）</label><input id="e_count" type="number" placeholder="重复次数(可选)"></div>
        <div class="field"><label>&nbsp;</label><button class="btn primary" onclick="addEvent()">添加</button></div>
      </div>
    </div>
    <div class="card">
      <div class="title-row">
        <b>月历</b>
        <span>
          <button class="btn" onclick="calShift(-1)">‹ 上月</button>
          <button class="btn" onclick="calShift(1)">下月 ›</button>
        </span>
      </div>
      <div style="color:var(--muted);font-size:12px;margin-bottom:8px;">点击日程可查看详情；纪念日请在「纪念日」页管理。</div>
      <div id="cal-box"></div>
    </div>`;
  await refreshCalendar();
}
async function calShift(delta) {
  calM += delta;
  if (calM < 1) { calM = 12; calY--; }
  if (calM > 12) { calM = 1; calY++; }
  await refreshCalendar();
}
async function refreshCalendar() {
  const events = await api("GET", "/api/events?type=event");
  _evById = {};
  const map = {};
  events.forEach((e) => {
    _evById[e.id] = e;
    expandEvent(e, calY, calM).forEach((ds) => {
      (map[ds] = map[ds] || []).push(e);
    });
  });
  for (const k in map) sortByTime(map[k]);
  renderMonthGrid(document.getElementById("cal-box"), calY, calM, map, true);
}
function expandEvent(e, y, m) {
  const res = [];
  const exSet = new Set((e.exceptions || "").split(",").map((s) => s.trim()).filter(Boolean));
  const start = new Date(e.date + "T00:00:00");
  if (start.getFullYear() === y && start.getMonth() === m - 1 && !exSet.has(fmtDate(start))) res.push(fmtDate(start));
  if (!e.repeat_type || e.repeat_type === "none") return res;
  let cur = new Date(start);
  let count = 1;
  const limit = e.repeat_until ? new Date(e.repeat_until + "T00:00:00") : null;
  const maxCount = e.repeat_count || 9999;
  while (true) {
    if (e.repeat_type === "daily") cur.setDate(cur.getDate() + 1);
    else if (e.repeat_type === "weekly") cur.setDate(cur.getDate() + 7);
    else if (e.repeat_type === "monthly") cur.setMonth(cur.getMonth() + 1);
    else if (e.repeat_type === "yearly") cur.setFullYear(cur.getFullYear() + 1);
    count++;
    if (limit && cur > limit) break;
    if (count > maxCount) break;
    const ds = fmtDate(cur);
    if (cur.getFullYear() === y && cur.getMonth() === m - 1 && !exSet.has(ds)) res.push(ds);
    if (cur.getFullYear() > y + 1) break;
  }
  return res;
}
async function addEvent() {
  const title = document.getElementById("e_title").value.trim();
  const date = document.getElementById("e_date").value;
  if (!title || !date) return alert("请填写主题与日期");
  await api("POST", "/api/events", {
    title, date, time: document.getElementById("e_time").value || null,
    participants: document.getElementById("e_part").value || null,
    type: "event",
    repeat_type: document.getElementById("e_rep").value,
    repeat_until: document.getElementById("e_until").value || null,
    repeat_count: document.getElementById("e_count").value ? parseInt(document.getElementById("e_count").value) : null,
  });
  await refreshCalendar();
}

/* ---------- 纪念日（周期 + 私有 + 权限） ---------- */
async function renderAnniversary(el) {
  const list = await api("GET", "/api/events?type=anniversary&upcoming_days=400");
  el.innerHTML = `
    <div class="card">
      <div class="title-row"><b>添加纪念日</b></div>
      <div class="form-inline">
        <input id="a_title" placeholder="名称(如 爸爸生日)">
        <input id="a_date" type="date">
        <select id="a_sub"></select>
        <select id="a_rep"><option value="yearly">每年</option><option value="none">不重复</option></select>
        <label style="display:flex;align-items:center;gap:6px;flex:none;"><input type="checkbox" id="a_priv"> 私有</label>
        <button class="btn primary" onclick="addAnn()" style="flex:none;">添加</button>
      </div>
      <div class="muted">“私有”仅自己与管理员可见；“每年”表示每年重复提醒。</div>
    </div>
    <div id="alist"></div>`;
  await fillCat(document.getElementById("a_sub"), "anniversary");
  document.getElementById("alist").innerHTML = list.map((a) => `
    <div class="list-item"><div><b>${esc(a.title)}</b> <span class="badge pink">${esc(a.subtype || "")}</span>
      ${a.private ? '<span class="badge gray">私有</span>' : '<span class="badge blue">共享</span>'}
      <span class="badge gray">${a.repeat_type === "none" ? "一次性" : "每年"}</span></div>
      <div class="meta">${esc(a.date)} · 还有 <b>${a.days_left}</b> 天</div>
      ${isOwner(a.user_id) ? `<div style="margin-top:8px;"><button class="btn danger" onclick="delAnn(${a.id})">删除</button></div>` : ""}
    </div>`).join("") || '<div class="muted">暂无纪念日</div>';
}
async function addAnn() {
  const title = document.getElementById("a_title").value.trim();
  const date = document.getElementById("a_date").value;
  if (!title || !date) return alert("请填写名称与日期");
  await api("POST", "/api/events", {
    title, date, type: "anniversary", subtype: document.getElementById("a_sub").value,
    repeat_type: document.getElementById("a_rep").value,
    private: document.getElementById("a_priv").checked ? 1 : 0,
  });
  renderAnniversary(document.getElementById("view"));
}
async function delAnn(id) {
  if (!confirm("确认删除？")) return;
  await api("DELETE", "/api/events/" + id);
  renderAnniversary(document.getElementById("view"));
}

/* ---------- 购物清单（类别 + 私有 + 权限） ---------- */
async function renderShopping(el) {
  const list = await api("GET", "/api/shopping");
  el.innerHTML = `
    <div class="card">
      <div class="title-row"><b>添加物品</b></div>
      <div class="form-inline">
        <input id="s_name" placeholder="物品名">
        <input id="s_qty" placeholder="数量(可选)">
        <select id="s_cat"></select>
        <label style="display:flex;align-items:center;gap:6px;flex:none;"><input type="checkbox" id="s_priv"> 私有</label>
        <button class="btn primary" onclick="addShop()" style="flex:none;">添加</button>
      </div>
      <div class="muted">“私有”仅自己与管理员可见、可操作。</div>
    </div>
    <div id="slist"></div>`;
  await fillCat(document.getElementById("s_cat"), "shopping");
  renderShopList(document.getElementById("slist"), list);
}
function renderShopList(box, list) {
  box.innerHTML = list.map((s) => `
    <div class="list-item ${s.done ? "done" : ""}">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span><b>${esc(s.name)}</b> ${s.quantity ? "(" + esc(s.quantity) + ")" : ""} <span class="badge gray">${esc(s.category)}</span>
          ${s.private ? '<span class="badge gray">私有</span>' : '<span class="badge blue">共享</span>'}</span>
        <span>
          ${isOwner(s.added_by) ? `<button class="btn" onclick="toggleShop(${s.id})">${s.done ? "恢复" : "完成"}</button>` : ""}
          ${isOwner(s.added_by) ? `<button class="btn danger" onclick="delShop(${s.id})">删除</button>` : ""}
        </span>
      </div>
      <div class="meta">添加人：${esc(s.added_by_name)}</div>
    </div>`).join("") || '<div class="muted">清单为空</div>';
}
async function addShop() {
  const name = document.getElementById("s_name").value.trim();
  if (!name) return alert("请填写物品名");
  await api("POST", "/api/shopping", {
    name, quantity: document.getElementById("s_qty").value || null,
    category: document.getElementById("s_cat").value,
    private: document.getElementById("s_priv").checked ? 1 : 0,
  });
  const list = await api("GET", "/api/shopping");
  renderShopList(document.getElementById("slist"), list);
}
async function toggleShop(id) {
  await api("PATCH", "/api/shopping/" + id);
  const list = await api("GET", "/api/shopping");
  renderShopList(document.getElementById("slist"), list);
}
async function delShop(id) {
  if (!confirm("确认删除？")) return;
  await api("DELETE", "/api/shopping/" + id);
  const list = await api("GET", "/api/shopping");
  renderShopList(document.getElementById("slist"), list);
}

/* ---------- 食谱文档（Markdown + 粘贴图片） ---------- */
let allRecipes = [];
async function renderRecipes(el) {
  allRecipes = await api("GET", "/api/recipes");
  el.innerHTML = `
    <div class="card">
      <div class="title-row"><b>添加 / 编辑食谱</b></div>
      <div class="form-inline">
        <input id="r_name" placeholder="菜名">
        <select id="r_cat"></select>
      </div>
      <textarea id="r_content" placeholder="在此粘贴或编写 Markdown 文档（支持标题、列表、加粗；直接 Ctrl+V 粘贴图片会自动上传插入）" style="width:100%;min-height:160px;margin-top:10px;font-family:monospace;"></textarea>
      <div class="row" style="margin-top:10px;">
        <button class="btn primary" onclick="addRecipe()">保存食谱</button>
        <button class="btn" onclick="clearRecipeForm()">清空</button>
      </div>
      <div class="muted" style="margin-top:6px;">提示：从别处复制的 Markdown 文本、或直接复制带图网页内容，都会自动转成 Markdown 并把图片上传到本站（确保能正常显示）。</div>
    </div>
    <div class="card">
      <div class="title-row"><b>食谱列表</b></div>
      <input id="r_search" placeholder="搜索菜名 / 类别 / 内容关键字" oninput="filterRecipes()" style="width:100%;padding:8px 10px;margin-bottom:12px;border:1px solid var(--line);border-radius:8px;font-size:14px;">
      <div id="rlist"></div>
    </div>`;
  await fillCat(document.getElementById("r_cat"), "recipe");
  document.getElementById("r_content").addEventListener("paste", handlePaste);
  filterRecipes();
}
function filterRecipes() {
  const kw = (document.getElementById("r_search").value || "").toLowerCase();
  const list = allRecipes.filter((r) =>
    (r.name || "").toLowerCase().includes(kw) ||
    (r.category || "").toLowerCase().includes(kw) ||
    (r.content || "").toLowerCase().includes(kw));
  renderRecipeList(document.getElementById("rlist"), list);
}
function renderRecipeList(box, list) {
  box.innerHTML = list.map((r) => `
    <div class="list-item recipe-card" onclick="viewRecipe(${r.id})">
      <div><b>${esc(r.name)}</b> <span class="badge amber">${esc(r.category)}</span> <span class="muted">by ${esc(r.author)}</span></div>
      <div class="md-body" style="margin-top:8px;max-height:150px;overflow:hidden;">${md2html(r.content || "")}</div>
      <div class="muted" style="margin-top:6px;font-size:12px;">点击查看完整食谱 →</div>
    </div>`).join("") || '<div class="muted">暂无食谱</div>';
}
function viewRecipe(id) {
  const r = allRecipes.find((x) => x.id === id);
  if (!r) return;
  const own = isOwner(r.author_id); // 作者本人或管理员可改删
  const body = `
    <div class="md-body" style="max-height:72vh;overflow:auto;">${md2html(r.content || "")}</div>
    ${own ? `<div class="row" style="margin-top:14px;justify-content:flex-end;">
        <button class="btn" onclick="closeModal();editRecipe(${r.id})">编辑</button>
        <button class="btn danger" onclick="closeModal();delRecipe(${r.id})">删除</button>
      </div>` : ""}`;
  openModal(esc(r.name) + "（" + esc(r.category) + "）", body, true);
}
async function addRecipe() {
  const name = document.getElementById("r_name").value.trim();
  if (!name) return alert("请填写菜名");
  const payload = {
    name, category: document.getElementById("r_cat").value,
    content: document.getElementById("r_content").value || null,
  };
  if (editingRecipeId) {
    await api("PUT", "/api/recipes/" + editingRecipeId, payload);
  } else {
    await api("POST", "/api/recipes", payload);
  }
  editingRecipeId = null;
  allRecipes = await api("GET", "/api/recipes");
  filterRecipes();
  clearRecipeForm();
}
function clearRecipeForm() {
  document.getElementById("r_name").value = "";
  document.getElementById("r_content").value = "";
  editingRecipeId = null;
}
async function editRecipe(id) {
  const list = await api("GET", "/api/recipes");
  const r = list.find((x) => x.id === id);
  if (!r) return;
  document.getElementById("r_name").value = r.name;
  document.getElementById("r_content").value = r.content || "";
  document.getElementById("r_cat").value = r.category;
  editingRecipeId = id;
  document.getElementById("r_name").focus();
}
async function delRecipe(id) {
  if (!confirm("确认删除？")) return;
  await api("DELETE", "/api/recipes/" + id);
  allRecipes = await api("GET", "/api/recipes");
  filterRecipes();
}
async function handlePaste(e) {
  const cd = e.clipboardData || window.clipboardData;
  if (!cd) return;
  // 1. 直接复制的图片文件（如截图）
  for (const it of cd.items) {
    if (it.type && it.type.indexOf("image") === 0) {
      const file = it.getAsFile();
      if (file) {
        e.preventDefault();
        const fd = new FormData();
        fd.append("file", file);
        try {
          const r = await api("POST", "/api/upload_image", fd, true);
          insertAtCursor(e.target, "\n![图片](" + r.url + ")\n");
        } catch (err) {
          alert("图片上传失败：" + err.message);
        }
        return;
      }
    }
  }
  // 2. 富文本 HTML（从网页复制的内容）：保留格式并自动上传其中图片(data:) 后转成 Markdown
  const html = cd.getData("text/html");
  if (html) {
    e.preventDefault();
    const md = await htmlToMarkdown(html);
    if (md) {
      const ta = e.target;
      const prefix = (ta.value && !ta.value.endsWith("\n")) ? "\n" : "";
      insertAtCursor(ta, prefix + md + "\n");
    }
  }
}

/* 把剪贴板里的 HTML 转成 Markdown：标题/加粗/列表/链接保留，图片自动上传 */
async function htmlToMarkdown(html) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  let out = await walkHtml(doc.body);
  return out.replace(/\n{3,}/g, "\n\n").trim();
}
async function walkHtml(node) {
  let out = "";
  for (const child of node.childNodes) {
    if (child.nodeType === 3) { out += child.textContent; continue; }
    if (child.nodeType !== 1) continue;
    const tag = child.tagName.toLowerCase();
    if (tag === "br") { out += "\n"; continue; }
    if (tag === "img") {
      const src = child.getAttribute("src") || "";
      const alt = child.getAttribute("alt") || "";
      if (src.startsWith("data:")) {
        try {
          const r = await uploadDataUrl(src);
          out += `![${alt}](${r.url})`;
        } catch (err) {
          out += `![${alt}](${src})`;
        }
      } else if (/^https?:\/\//i.test(src)) {
        // 外链图片（如复制网页食谱里的图）通过后端代理下载到本站，确保能正常显示
        try {
          const r = await api("POST", "/api/upload_image_url", { url: src });
          out += `![${alt}](${r.url})`;
        } catch (err) {
          out += `![${alt}](${src})`;
        }
      } else {
        out += `![${alt}](${src})`;
      }
      continue;
    }
    const inner = await walkHtml(child);
    switch (tag) {
      case "h1": out += "\n# " + inner + "\n"; break;
      case "h2": out += "\n## " + inner + "\n"; break;
      case "h3": out += "\n### " + inner + "\n"; break;
      case "h4": out += "\n#### " + inner + "\n"; break;
      case "strong": case "b": out += "**" + inner + "**"; break;
      case "em": case "i": out += "*" + inner + "*"; break;
      case "a": out += "[" + inner + "](" + (child.getAttribute("href") || "") + ")"; break;
      case "code": out += "`" + inner + "`"; break;
      case "pre": out += "\n```\n" + inner + "\n```\n"; break;
      case "ul": case "ol": out += "\n" + inner; break;
      case "li": out += "- " + inner + "\n"; break;
      case "p": case "div": case "blockquote": out += "\n" + inner + "\n"; break;
      default: out += inner;
    }
  }
  return out;
}
async function uploadDataUrl(dataUrl) {
  const m = /^data:([^;]+);base64,(.*)$/.exec(dataUrl);
  if (!m) throw new Error("无效的图片数据");
  const mime = m[1], b64 = m[2];
  const ext = ({ "image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
    "image/gif": "gif", "image/webp": "webp" }[mime] || "png");
  const bin = atob(b64);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  const file = new File([arr], "pasted_" + Date.now() + "." + ext, { type: mime });
  const fd = new FormData();
  fd.append("file", file);
  return await api("POST", "/api/upload_image", fd, true);
}
function insertAtCursor(ta, text) {
  const s = ta.selectionStart, en = ta.selectionEnd;
  ta.value = ta.value.slice(0, s) + text + ta.value.slice(en);
  ta.selectionStart = ta.selectionEnd = s + text.length;
  ta.focus();
}

/* ---------- 日记本（Markdown 书写 / 查看） ---------- */
async function renderDiary(el) {
  const list = await api("GET", "/api/diaries");
  const td = todayStr();
  el.innerHTML = `
    <div class="card">
      <div class="title-row"><b>写日记</b></div>
      <div class="form-inline">
        <div class="field"><label>标题</label><input id="d_title" placeholder="今天发生了什么"></div>
        <div class="field"><label>日期</label><input id="d_date" type="date" value="${td}"></div>
      </div>
      <textarea id="d_content" placeholder="用 Markdown 写日记；可直接粘贴网页内容，格式与图片会自动转成 Markdown" style="width:100%;min-height:200px;margin-top:10px;font-family:monospace;"></textarea>
      <div class="row" style="margin-top:10px;align-items:center;">
        <label class="chk"><input id="d_priv" type="checkbox"> 设为私密（仅自己可见，管理员也看不到）</label>
        <span style="flex:1;"></span>
        <button class="btn primary" onclick="addDiary()">保存日记</button>
        <button class="btn" onclick="clearDiaryForm()">清空</button>
      </div>
      <div class="muted" style="margin-top:6px;">提示：从网页复制的内容（标题、加粗、列表、链接、图片）粘贴后会自动转成 Markdown。</div>
    </div>
    <div id="dlist"></div>`;
  const ta = document.getElementById("d_content");
  ta.addEventListener("paste", handlePaste);
  renderDiaryList(document.getElementById("dlist"), list);
}
function renderDiaryList(box, list) {
  box.innerHTML = list.map((d) => `
    <div class="list-item">
      <div><b>${esc(d.title)}</b> <span class="badge gray">${esc(d.date)}</span> ${d.private ? '<span class="badge red">私密</span>' : '<span class="badge blue">公开</span>'} <span class="muted">by ${esc(d.author)}</span></div>
      <div class="md-body" style="margin-top: 8px;">${md2html(d.content || "")}</div>
      ${me.id === d.author_id ? `<div style="margin-top:8px;"><button class="btn" onclick="editDiary(${d.id})">编辑</button><button class="btn danger" onclick="delDiary(${d.id})">删除</button></div>` : ""}
    </div>`).join("") || '<div class="muted">还没有日记，写下第一篇吧 ✍️</div>';
}
async function addDiary() {
  const title = document.getElementById("d_title").value.trim();
  if (!title) return alert("请填写标题");
  const payload = {
    title,
    date: document.getElementById("d_date").value || todayStr(),
    content: document.getElementById("d_content").value || null,
    private: document.getElementById("d_priv").checked ? 1 : 0,
  };
  if (editingDiaryId) {
    await api("PUT", "/api/diaries/" + editingDiaryId, payload);
  } else {
    await api("POST", "/api/diaries", payload);
  }
  editingDiaryId = null;
  const list = await api("GET", "/api/diaries");
  renderDiaryList(document.getElementById("dlist"), list);
  clearDiaryForm();
}
function clearDiaryForm() {
  document.getElementById("d_title").value = "";
  document.getElementById("d_content").value = "";
  document.getElementById("d_priv").checked = false;
  editingDiaryId = null;
}
async function editDiary(id) {
  const list = await api("GET", "/api/diaries");
  const d = list.find((x) => x.id === id);
  if (!d) return;
  document.getElementById("d_title").value = d.title;
  document.getElementById("d_content").value = d.content || "";
  document.getElementById("d_date").value = d.date;
  document.getElementById("d_priv").checked = !!d.private;
  editingDiaryId = id;
  document.getElementById("d_title").focus();
}
async function delDiary(id) {
  if (!confirm("确认删除？")) return;
  await api("DELETE", "/api/diaries/" + id);
  const list = await api("GET", "/api/diaries");
  renderDiaryList(document.getElementById("dlist"), list);
}

/* ---------- 家庭相册 ---------- */
async function renderPhotos(el) {
  const list = await api("GET", "/api/photos");
  const td = todayStr();
  el.innerHTML = `
    <div class="card">
      <div class="title-row"><b>上传照片</b></div>
      <div class="form-inline">
        <input id="ph_event" placeholder="事件/主题 *必填">
        <input id="ph_date" type="date" value="${td}">
        <input id="ph_desc" placeholder="描述(可选)">
        <input id="ph_file" type="file" accept="image/*">
        <button class="btn primary" onclick="uploadPhoto()" style="flex:none;">上传</button>
      </div>
      <div class="muted">主题与日期为必填项；日期默认为当天。</div>
    </div>
    <div class="photo-grid" id="pgrid"></div>`;
  document.getElementById("pgrid").innerHTML = list.map((p) => `
    <div class="photo-item">
      <img src="/api/uploads/${esc(p.path)}" alt="${esc(p.description || "")}" onclick="viewPhoto('${esc(p.path)}','${esc(p.event || "")}','${esc(p.date || "")}')">
      <div class="meta">${esc(p.event || "")} ${esc(p.date || "")}</div>
      <button class="btn danger" onclick="delPhoto(${p.id})">删除</button>
    </div>`).join("") || '<div class="muted">暂无照片</div>';
}
/* 点击缩略图查看大图（居中弹窗） */
function viewPhoto(path, ev, dt) {
  const body = `<img src="/api/uploads/${esc(path)}" style="width:100%;max-height:78vh;object-fit:contain;border-radius:10px;display:block;" alt="">
    <div class="meta" style="margin-top:10px;text-align:center;">${esc(ev)} ${esc(dt)}</div>`;
  openModal("照片", body);
}
async function uploadPhoto() {
  const f = document.getElementById("ph_file").files[0];
  if (!f) return alert("请选择图片");
  const event = document.getElementById("ph_event").value.trim();
  if (!event) return alert("请填写事件/主题");
  const dateVal = document.getElementById("ph_date").value || todayStr();
  const fd = new FormData();
  fd.append("file", f);
  fd.append("event", event);
  fd.append("date", dateVal);
  fd.append("description", document.getElementById("ph_desc").value || "");
  await api("POST", "/api/photos", fd, true);
  renderPhotos(document.getElementById("view"));
}
async function delPhoto(id) {
  if (!confirm("确认删除？")) return;
  await api("DELETE", "/api/photos/" + id);
  renderPhotos(document.getElementById("view"));
}

/* ---------- 压岁钱 / 红包（收入 / 使用） ---------- */
async function renderLucky(el) {
  const list = await api("GET", "/api/luckymoney");
  const sum = await api("GET", "/api/luckymoney/summary");
  let yearSel = '<option value="">全部年份</option>' + sum.years.map((y) => `<option>${y}</option>`).join("");
  el.innerHTML = `
    <div class="cards">
      <div class="stat"><div class="label">累计收入</div><div class="num" style="color:var(--green)">¥${sum.total_income}</div></div>
      <div class="stat"><div class="label">累计使用</div><div class="num" style="color:var(--red)">¥${sum.total_expense}</div></div>
      <div class="stat"><div class="label">结余</div><div class="num">¥${sum.balance}</div></div>
      ${sum.by_person.slice(0, 3).map((p) => `<div class="stat"><div class="label">${esc(p.receiver)} 收入</div><div class="num">¥${p.total}</div></div>`).join("")}
    </div>
    <div class="card">
      <div class="title-row"><b>记录一笔</b></div>
      <div class="form-inline">
        <input id="l_year" type="number" placeholder="年份" value="${new Date().getFullYear()}">
        <input id="l_receiver" placeholder="收款人 / 用途">
        <input id="l_amount" type="number" placeholder="金额">
        <select id="l_kind"><option value="income">收入（收红包）</option><option value="expense">使用（花掉）</option></select>
        <input id="l_giver" placeholder="发放人/备注(可选)">
        <button class="btn primary" onclick="addLucky()" style="flex:none;">记录</button>
      </div>
    </div>
    <div id="llist"></div>`;
  renderLuckyList(document.getElementById("llist"), list);
}
function renderLuckyList(box, list) {
  box.innerHTML = list.map((m) => `
    <div class="list-item">
      <div><b>${esc(m.receiver)}</b>
        ${m.kind === "income"
          ? `<span class="badge green">收入 +¥${m.amount}</span>`
          : `<span class="badge red">使用 -¥${m.amount}</span>`}
        <span class="badge gray">${m.year}</span></div>
      <div class="meta">${esc(m.giver || "")}${m.note ? " · " + esc(m.note) : ""}</div>
      ${me.role === "admin" ? `<div style="margin-top:8px;"><button class="btn danger" onclick="delLucky(${m.id})">删除</button></div>` : ""}
    </div>`).join("") || '<div class="muted">暂无记录</div>';
}
async function addLucky() {
  const year = document.getElementById("l_year").value;
  const receiver = document.getElementById("l_receiver").value.trim();
  const amount = document.getElementById("l_amount").value;
  if (!receiver || !amount) return alert("请填写收款人/用途与金额");
  await api("POST", "/api/luckymoney", {
    year: parseInt(year), receiver, amount: parseFloat(amount),
    kind: document.getElementById("l_kind").value,
    giver: document.getElementById("l_giver").value || null,
  });
  const list = await api("GET", "/api/luckymoney");
  renderLuckyList(document.getElementById("llist"), list);
}
async function delLucky(id) {
  if (!confirm("确认删除？")) return;
  await api("DELETE", "/api/luckymoney/" + id);
  const list = await api("GET", "/api/luckymoney");
  renderLuckyList(document.getElementById("llist"), list);
}

/* ---------- 类别管理（仅管理员） ---------- */
async function renderCategories(el) {
  if (me.role !== "admin") { el.innerHTML = '<div class="muted">仅管理员可访问</div>'; return; }
  const kinds = [
    { k: "shopping", name: "购物清单类别" },
    { k: "anniversary", name: "纪念日类别" },
    { k: "recipe", name: "食谱菜类" },
  ];
  el.innerHTML = kinds.map((kd) => `
    <div class="card" style="margin-bottom:16px;">
      <div class="title-row"><b>${kd.name}</b></div>
      <div class="row" id="catrow-${kd.k}"><div class="muted">加载中…</div></div>
      <div class="form-inline" style="margin-top:10px;">
        <input id="newcat-${kd.k}" placeholder="新增类别名">
        <button class="btn primary" onclick="addCat('${kd.k}')" style="flex:none;">添加</button>
      </div>
    </div>`).join("");
  for (const kd of kinds) await loadCatRow(kd.k);
}
async function loadCatRow(kind) {
  const cats = await api("GET", "/api/categories?kind=" + kind);
  document.getElementById("catrow-" + kind).innerHTML = cats.map((c) =>
    `<span class="badge gray">${esc(c.name)} <a href="javascript:delCat(${c.id})" style="color:var(--red);">×</a></span>`
  ).join(" ") || '<span class="muted">暂无，请添加</span>';
}
async function addCat(kind) {
  const name = document.getElementById("newcat-" + kind).value.trim();
  if (!name) return;
  try {
    await api("POST", "/api/categories", { kind, name });
    document.getElementById("newcat-" + kind).value = "";
    await loadCatRow(kind);
  } catch (e) { alert(e.message); }
}
async function delCat(id) {
  if (!confirm("确认删除该类别？")) return;
  await api("DELETE", "/api/categories/" + id);
  for (const k of ["shopping", "anniversary", "recipe"]) await loadCatRow(k);
}

/* ---------- 用户管理（含重置密码） ---------- */
async function renderUsers(el) {
  if (me.role !== "admin") { el.innerHTML = '<div class="muted">仅管理员可访问</div>'; return; }
  const users = await api("GET", "/api/users");
  el.innerHTML = `
    <div class="card">
      <div class="title-row"><b>新建用户</b></div>
      <div class="form-inline">
        <input id="u_name" placeholder="用户名">
        <input id="u_disp" placeholder="显示名">
        <select id="u_role"><option value="member">家庭成员</option><option value="admin">管理员</option><option value="guest">访客</option></select>
        <input id="u_pw" type="password" placeholder="初始密码">
        <button class="btn primary" onclick="addUser()" style="flex:none;">创建</button>
      </div>
    </div>
    <div id="ulist"></div>`;
  document.getElementById("ulist").innerHTML = users.map((u) => `
    <div class="list-item"><div><b>${esc(u.display_name)}</b> <span class="badge blue">${roleText(u.role)}</span></div>
      <div class="meta">@${esc(u.username)} · ${esc(u.created_at)}</div>
      ${u.id !== me.id ? `<div style="margin-top:8px;"><button class="btn" onclick="openResetPw(${u.id},'${esc(u.display_name)}')">重置密码</button><button class="btn danger" onclick="delUser(${u.id})">删除</button></div>` : ""}
    </div>`).join("");
}
async function addUser() {
  const username = document.getElementById("u_name").value.trim();
  const display_name = document.getElementById("u_disp").value.trim() || username;
  const password = document.getElementById("u_pw").value;
  if (!username || !password) return alert("请填写用户名与密码");
  await api("POST", "/api/users", {
    username, display_name, role: document.getElementById("u_role").value, password,
  });
  const users = await api("GET", "/api/users");
  document.getElementById("ulist").innerHTML = users.map((u) => `
    <div class="list-item"><div><b>${esc(u.display_name)}</b> <span class="badge blue">${roleText(u.role)}</span></div>
      <div class="meta">@${esc(u.username)} · ${esc(u.created_at)}</div>
      ${u.id !== me.id ? `<div style="margin-top:8px;"><button class="btn" onclick="openResetPw(${u.id},'${esc(u.display_name)}')">重置密码</button><button class="btn danger" onclick="delUser(${u.id})">删除</button></div>` : ""}
    </div>`).join("");
}
async function delUser(id) {
  if (!confirm("确认删除该用户？")) return;
  await api("DELETE", "/api/users/" + id);
  const users = await api("GET", "/api/users");
  document.getElementById("ulist").innerHTML = users.map((u) => `
    <div class="list-item"><div><b>${esc(u.display_name)}</b> <span class="badge blue">${roleText(u.role)}</span></div>
      <div class="meta">@${esc(u.username)} · ${esc(u.created_at)}</div>
      ${u.id !== me.id ? `<div style="margin-top:8px;"><button class="btn" onclick="openResetPw(${u.id},'${esc(u.display_name)}')">重置密码</button><button class="btn danger" onclick="delUser(${u.id})">删除</button></div>` : ""}
    </div>`).join("");
}

/* ---------- 密码修改 / 重置 ---------- */
function openChangePw() {
  const body = `
    <input id="op_pw" type="password" placeholder="当前密码">
    <input id="np_pw" type="password" placeholder="新密码">
    <div class="muted">修改成功后需重新登录。</div>
    <div class="row" style="margin-top:8px;justify-content:flex-end;">
      <button class="btn" onclick="closeModal()">取消</button>
      <button class="btn primary" onclick="submitChangePw()">确定</button>
    </div>`;
  openModal("修改密码", body);
}
async function submitChangePw() {
  const oldp = document.getElementById("op_pw").value;
  const newp = document.getElementById("np_pw").value;
  if (!oldp || !newp) return alert("请填写两项密码");
  try {
    await api("POST", "/api/me/change_password", { old_password: oldp, new_password: newp });
    closeModal();
    alert("密码已修改，请重新登录");
    token = null;
    localStorage.removeItem("fp_token");
    showLogin();
  } catch (e) { alert(e.message); }
}
function openResetPw(uid, disp) {
  const body = `
    <div class="muted">为 <b>${esc(disp)}</b> 设置新密码：</div>
    <input id="rp_pw" type="password" placeholder="新密码" style="margin-top:8px;">
    <div class="row" style="margin-top:8px;justify-content:flex-end;">
      <button class="btn" onclick="closeModal()">取消</button>
      <button class="btn primary" onclick="submitResetPw(${uid})">确定</button>
    </div>`;
  openModal("重置密码", body);
}
async function submitResetPw(uid) {
  const pw = document.getElementById("rp_pw").value;
  if (!pw) return alert("请填写新密码");
  try {
    await api("POST", "/api/users/" + uid + "/reset_password", { new_password: pw });
    closeModal();
    alert("密码已重置");
  } catch (e) { alert(e.message); }
}

init();
