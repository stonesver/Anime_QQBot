const bridge = window.AstrBotPluginPage;
const state = { view: "overview", groups: [], writesEnabled: true, overviewLoading: false };
const $ = (selector) => document.querySelector(selector);
const OVERVIEW_REFRESH_MS = 30_000;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "—" : date.toLocaleString();
}

function status(value) {
  const good = ["sent", "completed", "confirmed", "pending"].includes(value);
  const bad = ["failed", "unknown", "rejected", "retry"].includes(value);
  return `<span class="status ${good ? "good" : bad ? "bad" : ""}">${escapeHtml(value || "—")}</span>`;
}

function loading(target) { $(target).innerHTML = '<div class="loading">正在读取…</div>'; }
function empty(message) { return `<div class="empty">${escapeHtml(message)}</div>`; }
function error(target, reason) { $(target).innerHTML = `<div class="error">${escapeHtml(reason.message || reason)}</div>`; }
function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  window.setTimeout(() => node.classList.remove("show"), 2600);
}

async function confirmAction(title, message) {
  const dialog = $("#confirm-dialog");
  $("#confirm-title").textContent = title;
  $("#confirm-message").textContent = message;
  dialog.showModal();
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true });
  });
}

const napcatStates = {
  unknown: ["尚未检测 QQ 会话", "等待 AstrBot 完成首次 NapCat 状态探测。"],
  online: ["QQ 会话在线", "NapCat 可达，QQ 当前可以接收和发送群消息。"],
  qq_offline: ["QQ 会话已离线", "NapCat 进程仍在，但 QQ 登录已经失效。"],
  unreachable: ["NapCat 状态接口不可达", "已连续三次无法取得 QQ 会话状态。"],
};

function napcatLabel(value) {
  return napcatStates[value]?.[0] || napcatStates.unknown[0];
}

function renderNapcatStatus(payload = {}) {
  const value = napcatStates[payload.status] ? payload.status : "unknown";
  const banner = $("#napcat-banner");
  banner.className = `session-banner ${value}`;
  $("#napcat-status-label").textContent = napcatStates[value][0];
  $("#napcat-status-detail").textContent = napcatStates[value][1];
  $("#napcat-observed-at").textContent = formatTime(payload.observed_at);
  $("#napcat-changed-at").textContent = formatTime(payload.status_changed_at);
  $("#napcat-offline-since").textContent = formatTime(payload.offline_since);
  $("#napcat-recovery").hidden = value !== "qq_offline";

  const events = Array.isArray(payload.recent_events) ? payload.recent_events : [];
  $("#napcat-history").innerHTML = events.length ? events.map((event) => `
    <div class="history-row">
      <span class="history-time">${formatTime(event.occurred_at)}</span>
      <span>${event.previous_status ? `${escapeHtml(napcatLabel(event.previous_status))} → ` : ""}<strong>${escapeHtml(napcatLabel(event.status))}</strong></span>
    </div>
  `).join("") : empty("还没有状态变化记录。");
}

async function loadOverview(showLoading = true) {
  if (state.overviewLoading) return;
  state.overviewLoading = true;
  if (showLoading) loading("#overview-grid");
  try {
    const data = await bridge.apiGet("overview");
    renderNapcatStatus(data.napcat_status);
    const metrics = [
      ["已同步番剧", data.catalog_animes], ["AniList 映射", `${data.anilist_mapped}/${data.catalog_animes}`],
      ["未来有计划", data.future_airing_animes], ["精确时刻", `${data.future_exact_animes}/${data.future_airing_animes}`],
      ["待 AniList 映射", data.future_unmapped_anilist_animes], ["已映射·源未给时刻", data.future_mapped_without_exact_animes],
      ["已登记群", data.groups], ["有效订阅", data.subscriptions],
      ["等待通知", data.pending_notifications], ["异常通知", data.failed_notifications],
      ["人工待确认映射", data.pending_mappings],
    ];
    $("#overview-grid").innerHTML = metrics.map(([label, value]) =>
      `<article class="metric"><span>${label}</span><strong>${value}</strong></article>`
    ).join("");
  } catch (reason) {
    if (showLoading) error("#overview-grid", reason);
  } finally {
    state.overviewLoading = false;
  }
}

function catalogAiring(item) {
  if (!item.next_air_date) return "暂无后续计划";
  if (!item.next_air_at) return `${escapeHtml(item.next_air_date)} · 待定`;
  return formatTime(item.next_air_at);
}

async function loadCatalog() {
  loading("#catalog-content");
  try {
    const data = await bridge.apiGet("catalog", { query: $("#catalog-query").value, page: 1, page_size: 50 });
    if (!data.items.length) return $("#catalog-content").innerHTML = empty("没有匹配的已同步番剧。");
    $("#catalog-content").innerHTML = `<table><thead><tr><th>番剧</th><th>来源</th><th>下一次放送</th><th>精度</th><th>最近同步</th></tr></thead><tbody>${
      data.items.map((item) => `<tr>
        <td><strong class="catalog-title">${escapeHtml(item.title)}</strong><code class="catalog-id">${escapeHtml(item.id)}</code></td>
        <td><div class="source-tags">${item.sources.map((source) => `<span>${escapeHtml(source)}</span>`).join("") || "—"}</div></td>
        <td>${catalogAiring(item)}${item.next_episode ? `<small class="episode-label">第 ${escapeHtml(item.next_episode)} 集</small>` : ""}</td>
        <td>${item.precision === "exact" ? '<span class="status good">精确时刻</span>' : item.precision === "date_only" ? '<span class="status warn">仅日期</span>' : "—"}</td>
        <td>${formatTime(item.last_synced_at)}</td>
      </tr>`).join("")
    }</tbody></table>`;
  } catch (reason) { error("#catalog-content", reason); }
}

async function loadGroups() {
  loading("#groups-content");
  try {
    const data = await bridge.apiGet("groups", { query: $("#group-query").value, page: 1, page_size: 50 });
    state.groups = data.items;
    if (!data.items.length) return $("#groups-content").innerHTML = empty("没有匹配的群。");
    $("#groups-content").innerHTML = `<table><thead><tr><th>群</th><th>@入口</th><th>短命令</th><th>主动提醒</th><th>状态</th><th>操作</th></tr></thead><tbody>${
      data.items.map((item) => `<tr>
        <td>${escapeHtml(item.group_id)}</td>
        <td>${item.mention_enabled ? "开" : "关"}</td>
        <td>${item.direct_shortcuts_enabled ? "开" : "关"}</td>
        <td>${item.active_notifications_enabled ? "开" : "关"}</td>
        <td>${item.paused ? status("paused") : status("active")}</td>
        <td><div class="action-row">
          <button class="button small ghost" data-group="${escapeHtml(item.group_id)}" data-toggle="direct_shortcuts_enabled">切换短命令</button>
          <button class="button small ghost" data-group="${escapeHtml(item.group_id)}" data-toggle="active_notifications_enabled">切换提醒</button>
        </div></td>
      </tr>`).join("")
    }</tbody></table>`;
  } catch (reason) { error("#groups-content", reason); }
}

async function loadSubscriptions() {
  loading("#subscriptions-content");
  try {
    const data = await bridge.apiGet("subscriptions", { query: $("#subscription-query").value, page: 1, page_size: 50 });
    if (!data.items.length) return $("#subscriptions-content").innerHTML = empty("没有匹配的订阅。");
    $("#subscriptions-content").innerHTML = `<table><thead><tr><th>群</th><th>用户</th><th>番剧</th><th>提醒</th><th>操作</th></tr></thead><tbody>${
      data.items.map((item) => `<tr><td>${escapeHtml(item.group_id)}</td><td>${escapeHtml(item.user_id)}</td>
      <td>${escapeHtml(item.anime_title)}</td><td>${item.notify_airing ? "开播 " : ""}${item.notify_resource ? "Mikan" : ""}</td>
      <td><button class="button small danger" data-cancel-sub="${item.id}">取消订阅</button></td></tr>`).join("")
    }</tbody></table>`;
  } catch (reason) { error("#subscriptions-content", reason); }
}

async function loadMappings() {
  loading("#mappings-content");
  try {
    const data = await bridge.apiGet("mappings", { page: 1, page_size: 50 });
    if (!data.items.length) return $("#mappings-content").innerHTML = empty("还没有需要展示的映射状态。");
    $("#mappings-content").innerHTML = `<table><thead><tr><th>番剧</th><th>来源</th><th>状态</th><th>证据 / 原因</th><th>操作</th></tr></thead><tbody>${
      data.items.map((item) => `<tr><td>${escapeHtml(item.anime_title)}</td><td>${escapeHtml(item.provider)}${item.external_id !== "—" ? ` · ${escapeHtml(item.external_id)}` : ""}</td>
      <td>${item.kind === "assessment" ? escapeHtml(mappingOutcome(item.status, item.candidate_count)) : `${Math.round(item.confidence * 100)}%`}</td><td>${escapeHtml(mappingEvidence(item))}</td>
      <td>${item.kind === "assessment" ? "自动比对将在冷却后重试" : `<div class="action-row"><button class="button small" data-map="${item.id}" data-decision="confirmed">确认</button>
      <button class="button small danger" data-map="${item.id}" data-decision="rejected">拒绝</button></div>`}</td></tr>`).join("")
    }</tbody></table>`;
  } catch (reason) { error("#mappings-content", reason); }
}

function mappingOutcome(statusName, candidateCount) {
  const labels = { no_candidate: "未找到候选", ambiguous: "候选不唯一", missing_source_metadata: "源数据不完整", sync_failed: "候选同步失败" };
  const label = labels[statusName] || statusName;
  return Number.isInteger(candidateCount) ? `${label}（${candidateCount}）` : label;
}

function mappingEvidence(item) {
  if (item.kind !== "assessment") return `${item.evidence_type} / ${item.method}`;
  const labels = { no_search_candidate: "AniList 搜索未返回可用候选", first_air_date_mismatch: "标题能对应，但首播日不一致", title_not_matched: "首播日可对应，但标题未精确匹配", multiple_exact_candidates: "多个候选同时满足严格条件", missing_bangumi_title_or_air_date: "Bangumi 缺少日文标题或首播日", candidate_sync_failed: "AniList 候选详情未能同步" };
  return `${labels[item.evidence_type] || item.evidence_type}；最近尝试 ${formatTime(item.attempted_at)}`;
}

async function loadNotifications() {
  loading("#notifications-content");
  try {
    const data = await bridge.apiGet("notifications", { status: $("#notification-status").value, page: 1, page_size: 50 });
    if (!data.items.length) return $("#notifications-content").innerHTML = empty("当前筛选下没有通知。");
    $("#notifications-content").innerHTML = `<table><thead><tr><th>群</th><th>类型</th><th>状态</th><th>可发送时间</th><th>次数</th><th>操作</th></tr></thead><tbody>${
      data.items.map((item) => `<tr><td>${escapeHtml(item.group_id)}</td><td>${escapeHtml(item.job_type)}</td><td>${status(item.status)}</td>
      <td>${formatTime(item.available_at)}</td><td>${item.attempt_count}</td><td><div class="action-row">
      ${["failed", "retry", "unknown"].includes(item.status) ? `<button class="button small" data-notification="${item.id}" data-notification-action="retry" data-unknown="${item.status === "unknown"}">重试</button>` : ""}
      ${["pending", "failed", "retry", "unknown"].includes(item.status) ? `<button class="button small danger" data-notification="${item.id}" data-notification-action="cancel">取消</button>` : ""}
      </div></td></tr>`).join("")
    }</tbody></table>`;
  } catch (reason) { error("#notifications-content", reason); }
}

async function loadSources() {
  loading("#sources-content"); loading("#mapping-policy-content"); loading("#jobs-content");
  try {
    const [sources, policy, jobs] = await Promise.all([bridge.apiGet("sources"), bridge.apiGet("mapping-policy"), bridge.apiGet("jobs")]);
    $("#sources-content").innerHTML = sources.length ? sources.map((item) => `<article class="source-card">
      <p class="section-kicker">${escapeHtml(item.provider)}</p><h3>${item.last_error ? "需要关注" : "运行正常"}</h3>
      <dl><dt>最近成功</dt><dd>${formatTime(item.last_success_at)}</dd><dt>最近失败</dt><dd>${formatTime(item.last_failure_at)}</dd>
      <dt>错误摘要</dt><dd>${escapeHtml(item.last_error || "—")}</dd></dl></article>`).join("") : empty("还没有来源同步记录。");
    $("#jobs-content").innerHTML = jobs.length ? `<table><thead><tr><th>任务</th><th>状态</th><th>创建</th><th>错误</th></tr></thead><tbody>${
      jobs.map((item) => `<tr><td>${escapeHtml(item.job_type)}</td><td>${status(item.status)}</td><td>${formatTime(item.created_at)}</td><td>${escapeHtml(item.error_summary || "—")}</td></tr>`).join("")
    }</tbody></table>` : empty("还没有管理任务。");
    renderMappingPolicy(policy);
  } catch (reason) { error("#sources-content", reason); error("#mapping-policy-content", reason); error("#jobs-content", reason); }
}

function renderMappingPolicy(policy) {
  const outcomes = Object.entries(policy.assessment_counts || {}).map(([reason, count]) =>
    `${escapeHtml(mappingReason(reason))} ${escapeHtml(count)}`).join(" · ") || "尚无严格映射失败记录";
  $("#mapping-policy-content").innerHTML = `<div class="policy-fields">
    <label>单轮搜索预算<input id="mapping-query-budget" type="number" min="1" max="30" value="${escapeHtml(policy.query_budget)}" /><small>实际 AniList 搜索请求数，上限 30。</small></label>
    <label>近期优先窗口<input id="mapping-priority-window" type="number" min="1" max="14" value="${escapeHtml(policy.priority_window_days)}" /><small>未来 1–14 天内的番剧优先尝试。</small></label>
    <label>失败重试冷却<input id="mapping-retry-cooldown" type="number" min="1" max="168" value="${escapeHtml(policy.retry_cooldown_hours)}" /><small>严格不匹配后等待的小时数。</small></label>
  </div>
  <p class="policy-note">严格规则：标题 + 首播日 + 唯一候选。最近一次 AniList 成功：${formatTime(policy.last_success_at)}；${policy.last_error ? `错误：${escapeHtml(policy.last_error)}` : "当前无错误摘要"}。</p>
  <p class="policy-note">失败归因：${outcomes}</p>
  <div class="action-row"><button class="button small ghost" data-action="save-mapping-policy">保存</button><button class="button small" data-action="save-and-sync-mapping-policy">保存并立即同步</button></div>`;
}

function mappingReason(reason) {
  const labels = { no_search_candidate: "无搜索候选", first_air_date_mismatch: "首播日不一致", title_not_matched: "标题未精确匹配", multiple_exact_candidates: "候选不唯一", missing_bangumi_title_or_air_date: "Bangumi 数据不完整", candidate_sync_failed: "候选同步失败" };
  return labels[reason] || reason;
}

const loaders = { overview: loadOverview, catalog: loadCatalog, groups: loadGroups, subscriptions: loadSubscriptions, mappings: loadMappings, notifications: loadNotifications, sources: loadSources };
async function switchView(view) {
  state.view = view;
  document.querySelectorAll(".tab").forEach((node) => node.classList.toggle("active", node.dataset.view === view));
  document.querySelectorAll(".view").forEach((node) => node.classList.toggle("active", node.id === `view-${view}`));
  await loaders[view]();
}

document.addEventListener("click", async (event) => {
  const target = event.target.closest("button");
  if (!target) return;
  try {
    if (target.dataset.view) return switchView(target.dataset.view);
    if (target.dataset.action === "refresh") return loaders[state.view]();
    if (target.dataset.action === "pause-delivery" || target.dataset.action === "resume-delivery") {
      const paused = target.dataset.action === "pause-delivery";
      if (!await confirmAction(paused ? "暂停主动发送" : "恢复主动发送", paused ? "开播和 Mikan 通知会留在队列中。" : "确认解除人工暂停与熔断。")) return;
      await bridge.apiPost("delivery/global", { paused, reason: paused ? "manual dashboard pause" : "" });
      toast(paused ? "主动发送已暂停" : "主动发送已恢复"); return loadOverview();
    }
    if (target.dataset.toggle) {
      const item = state.groups.find((row) => row.group_id === target.dataset.group);
      const field = target.dataset.toggle;
      await bridge.apiPost(`groups/${item.group_id}/update`, { expected_version: item.version, [field]: !item[field] });
      toast("群设置已保存"); return loadGroups();
    }
    if (target.dataset.cancelSub) {
      if (!await confirmAction("取消这条订阅", "只取消当前用户、当前群的这一条番剧订阅。")) return;
      await bridge.apiPost(`subscriptions/${target.dataset.cancelSub}/cancel`, {});
      toast("订阅已取消"); return loadSubscriptions();
    }
    if (target.dataset.map) {
      if (!await confirmAction("确认映射结论", `将该映射标记为“${target.dataset.decision === "confirmed" ? "确认" : "拒绝"}”。`)) return;
      await bridge.apiPost(`mappings/${target.dataset.map}/review`, { decision: target.dataset.decision });
      toast("映射已更新"); return loadMappings();
    }
    if (target.dataset.notification) {
      const action = target.dataset.notificationAction;
      if (!await confirmAction(action === "retry" ? "重试单条通知" : "取消单条通知", target.dataset.unknown === "true" ? "状态未知，重试可能造成重复提醒。" : "操作只影响当前这一条。")) return;
      await bridge.apiPost(`notifications/${target.dataset.notification}/action`, { action, confirm_unknown: target.dataset.unknown === "true" });
      toast(action === "retry" ? "已放回队列" : "通知已取消"); return loadNotifications();
    }
    if (target.dataset.action === "sync-catalog") {
      const key = `catalog-${Date.now()}`;
      await bridge.apiPost("jobs/enqueue", { job_type: "sync_catalog", idempotency_key: key, parameters: { provider: "bangumi" } });
      toast("目录同步任务已创建"); return loadSources();
    }
    if (target.dataset.action === "save-mapping-policy" || target.dataset.action === "save-and-sync-mapping-policy") {
      const payload = {
        query_budget: Number($("#mapping-query-budget").value),
        priority_window_days: Number($("#mapping-priority-window").value),
        retry_cooldown_hours: Number($("#mapping-retry-cooldown").value),
      };
      await bridge.apiPost("mapping-policy", payload);
      if (target.dataset.action === "save-and-sync-mapping-policy") {
        await bridge.apiPost("jobs/enqueue", { job_type: "sync_anilist_mapping", idempotency_key: `anilist-mapping-${Date.now()}`, parameters: {} });
        toast("策略已保存，AniList 映射同步已创建");
      } else {
        toast("映射策略已保存，将在下一轮同步生效");
      }
      return loadSources();
    }
  } catch (reason) { toast(reason.message || "操作失败"); }
});

$("#group-query").addEventListener("change", loadGroups);
$("#catalog-query").addEventListener("change", loadCatalog);
$("#subscription-query").addEventListener("change", loadSubscriptions);
$("#notification-status").addEventListener("change", loadNotifications);

try {
  if (!bridge) throw new Error("请从 AstrBot 插件详情打开此页面。");
  await bridge.ready();
  $(".live-dot").classList.add("ready");
  $("#connection-label").textContent = "已连接 AstrBot";
  await loadOverview();
  window.setInterval(() => {
    if (state.view === "overview" && !document.hidden) loadOverview(false);
  }, OVERVIEW_REFRESH_MS);
} catch (reason) {
  $("#connection-label").textContent = "连接失败";
  error("#overview-grid", reason);
}
