const bridge = window.AstrBotPluginPage;
const state = { view: "overview", groups: [], mentionPolicy: null, pollCandidates: [], writesEnabled: true, overviewLoading: false };
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
  loading("#groups-content"); loading("#mention-policy-content");
  try {
    const [data, mentionPolicy] = await Promise.all([
      bridge.apiGet("groups", { query: $("#group-query").value, page: 1, page_size: 50 }),
      bridge.apiGet("mention-policy"),
    ]);
    state.groups = data.items;
    state.mentionPolicy = mentionPolicy;
    renderMentionPolicy(mentionPolicy);
    if (!data.items.length) return $("#groups-content").innerHTML = empty("没有匹配的群。");
    $("#groups-content").innerHTML = `<table><thead><tr><th>群</th><th>LLM 模式</th><th>LLM 图片</th><th>固定 @</th><th>短命令</th><th>主动提醒</th><th>状态</th><th>操作</th></tr></thead><tbody>${
      data.items.map((item) => `<tr>
        <td>${escapeHtml(item.group_id)}</td>
        <td><select data-group-policy="${escapeHtml(item.group_id)}" data-field="llm_mode">
          <option value="disabled" ${item.llm_mode === "disabled" ? "selected" : ""}>禁用</option>
          <option value="anime_only" ${item.llm_mode === "anime_only" ? "selected" : ""}>仅番剧</option>
          <option value="general" ${item.llm_mode === "general" ? "selected" : ""}>通用聊天</option>
        </select></td>
        <td><input type="checkbox" data-group-policy="${escapeHtml(item.group_id)}" data-field="llm_image_reply_enabled" ${item.llm_image_reply_enabled ? "checked" : ""}></td>
        <td><input type="checkbox" data-group-policy="${escapeHtml(item.group_id)}" data-field="mention_enabled" ${item.mention_enabled ? "checked" : ""}></td>
        <td>${item.direct_shortcuts_enabled ? "开" : "关"}</td>
        <td>${item.active_notifications_enabled ? "开" : "关"}</td>
        <td>${item.paused ? status("paused") : status("active")}</td>
        <td><div class="action-row">
          <button class="button small" data-group-policy-save="${escapeHtml(item.group_id)}">保存 LLM / @</button>
          <button class="button small ghost" data-group="${escapeHtml(item.group_id)}" data-toggle="direct_shortcuts_enabled">切换短命令</button>
          <button class="button small ghost" data-group="${escapeHtml(item.group_id)}" data-toggle="active_notifications_enabled">切换提醒</button>
        </div></td>
      </tr>`).join("")
    }</tbody></table>`;
  } catch (reason) { error("#groups-content", reason); }
}

const mentionActionLabels = {
  today: "今天播什么", week: "本周播什么", search: "搜索番剧", detail: "番剧详情",
  next: "下次放送", resource_detail: "资源详情", my_subscriptions: "我的订阅",
  subscribe: "订阅番剧", unsubscribe: "取消订阅", help: "帮助",
};

function renderMentionPolicy(policy) {
  const aliases = policy.aliases || {};
  $("#mention-policy-content").innerHTML = `<div class="policy-fields mention-policy-fields">${Object.entries(mentionActionLabels).map(([action, label]) => `
    <label>${escapeHtml(label)}<textarea rows="3" data-mention-action="${action}">${escapeHtml((aliases[action] || []).join("\n"))}</textarea></label>
  `).join("")}</div>
  <p class="policy-note">版本 ${escapeHtml(policy.version)} · ${policy.customized ? "已自定义" : "使用默认短语"}</p>
  <div class="action-row">
    <button class="button" data-action="save-mention-policy">保存固定短语</button>
    <button class="button ghost" data-action="restore-mention-policy">恢复默认</button>
  </div>`;
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

function minuteToTime(value) {
  const minute = Number(value || 0);
  return `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
}

function timeToMinute(value) {
  const [hour, minute] = String(value).split(":").map(Number);
  return hour * 60 + minute;
}

async function loadContent() {
  loading("#content-settings"); loading("#content-polls");
  try {
    const [groups, polls] = await Promise.all([
      bridge.apiGet("groups", { page: 1, page_size: 50 }),
      bridge.apiGet("content-polls"),
    ]);
    state.groups = groups.items;
    $("#poll-group").innerHTML = groups.items.map((item) => `<option value="${escapeHtml(item.group_id)}">${escapeHtml(item.group_id)}</option>`).join("");
    $("#content-settings").innerHTML = groups.items.length ? `<table><thead><tr><th>群</th><th>每日汇总</th><th>@全体</th><th>锚点 / 静默 / 截止</th><th>周报</th><th>周报时间</th><th>操作</th></tr></thead><tbody>${groups.items.map((item) => `<tr>
      <td>${escapeHtml(item.group_id)}</td>
      <td><input type="checkbox" data-field="daily_digest_enabled" data-content-group="${escapeHtml(item.group_id)}" ${item.daily_digest_enabled ? "checked" : ""}></td>
      <td><input type="checkbox" data-field="daily_digest_at_all_enabled" data-content-group="${escapeHtml(item.group_id)}" ${item.daily_digest_at_all_enabled ? "checked" : ""}></td>
      <td><input type="time" data-field="daily_digest_anchor_minute" data-content-group="${escapeHtml(item.group_id)}" value="${minuteToTime(item.daily_digest_anchor_minute)}"> / <input type="number" min="1" max="180" title="静默分钟" data-field="daily_digest_quiet_minutes" data-content-group="${escapeHtml(item.group_id)}" value="${escapeHtml(item.daily_digest_quiet_minutes)}"> 分 / <input type="time" data-field="daily_digest_cutoff_minute" data-content-group="${escapeHtml(item.group_id)}" value="${minuteToTime(item.daily_digest_cutoff_minute)}"></td>
      <td><input type="checkbox" data-field="weekly_report_enabled" data-content-group="${escapeHtml(item.group_id)}" ${item.weekly_report_enabled ? "checked" : ""}></td>
      <td><select data-field="weekly_report_weekday" data-content-group="${escapeHtml(item.group_id)}">${["周日", "周一", "周二", "周三", "周四", "周五", "周六"].map((label, value) => `<option value="${value}" ${item.weekly_report_weekday === value ? "selected" : ""}>${label}</option>`).join("")}</select> <input type="time" data-field="weekly_report_minute" data-content-group="${escapeHtml(item.group_id)}" value="${minuteToTime(item.weekly_report_minute)}"></td>
      <td><button class="button small" data-content-save="${escapeHtml(item.group_id)}">保存</button></td>
    </tr>`).join("")}</tbody></table>` : empty("还没有可配置的群。");
    $("#content-polls").innerHTML = polls.length ? `<table><thead><tr><th>群</th><th>主题</th><th>状态</th><th>截止</th><th>候选与票数</th><th>操作</th></tr></thead><tbody>${polls.map((poll) => `<tr><td>${escapeHtml(poll.group_id)}</td><td>${escapeHtml(poll.theme_label)}</td><td>${status(poll.status)}</td><td>${formatTime(poll.closes_at)}</td><td>${poll.candidates.map((item) => `${escapeHtml(item.title)} ${item.votes}`).join(" · ")}</td><td>${poll.status === "open" ? `<button class="button small danger" data-close-poll="${poll.id}">结束</button>` : "—"}</td></tr>`).join("")}</tbody></table>` : empty("还没有投票记录。");
  } catch (reason) { error("#content-settings", reason); error("#content-polls", reason); }
}

function renderPollCandidates(items) {
  state.pollCandidates = items;
  $("#poll-candidates").innerHTML = items.length ? items.map((item) => `<label class="candidate-choice"><input type="checkbox" data-poll-anime="${item.anime_id}" checked><span>${escapeHtml(item.title)}</span></label>`).join("") : empty("当前主题没有足够候选，可先补充订阅或放送数据。");
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
    <label>AnimeSchedule 状态<span><input id="animeschedule-enabled" type="checkbox" ${policy.animeschedule_enabled ? "checked" : ""} /> 启用映射桥与原始排期</span><small>Token：${policy.animeschedule_token_configured ? "已配置" : "未配置"}；仅 Bot 持有者可修改。</small></label>
    <label>单轮搜索预算<input id="mapping-query-budget" type="number" min="1" max="30" value="${escapeHtml(policy.query_budget)}" /><small>实际 AniList 搜索请求数，上限 30。</small></label>
    <label>近期优先窗口<input id="mapping-priority-window" type="number" min="1" max="14" value="${escapeHtml(policy.priority_window_days)}" /><small>未来 1–14 天内的番剧优先尝试。</small></label>
    <label>失败重试冷却<input id="mapping-retry-cooldown" type="number" min="1" max="168" value="${escapeHtml(policy.retry_cooldown_hours)}" /><small>严格不匹配后等待的小时数。</small></label>
    <label>AnimeSchedule 共享预算<input id="animeschedule-query-budget" type="number" min="1" max="30" value="${escapeHtml(policy.animeschedule_query_budget)}" /><small>桥接搜索与 AniList 后备共享的单轮上限。</small></label>
    <label>AnimeSchedule 优先窗口<input id="animeschedule-priority-window" type="number" min="1" max="14" value="${escapeHtml(policy.animeschedule_priority_window_days)}" /><small>未来 1–14 天内的缺映射番剧优先处理。</small></label>
    <label>空结果冷却<input id="animeschedule-empty-cooldown" type="number" min="1" max="720" value="${escapeHtml(policy.animeschedule_empty_cooldown_hours)}" /><small>正常空结果的等待小时数。</small></label>
    <label>来源错误冷却<input id="animeschedule-error-cooldown" type="number" min="1" max="720" value="${escapeHtml(policy.animeschedule_error_cooldown_hours)}" /><small>5xx 或无效响应的等待小时数。</small></label>
  </div>
  <p class="policy-note">映射规则：AnimeSchedule 唯一精确标题 + 显式 AniList ID + 同年；失败时回到 AniList 标题、首播日严格匹配。</p>
  <p class="policy-note">AnimeSchedule：最近成功 ${formatTime(policy.animeschedule_last_success_at)}；确认链接 ${escapeHtml(policy.animeschedule_confirmed_links)}；跨站补回 ${escapeHtml(policy.animeschedule_cross_id_links)}；精确排期 ${escapeHtml(policy.animeschedule_exact_occurrences)}；时间冲突 ${escapeHtml(policy.schedule_conflicts)}。${policy.animeschedule_last_error ? `错误：${escapeHtml(policy.animeschedule_last_error)}` : "当前无错误摘要"}。</p>
  <p class="policy-note">AniList：最近成功 ${formatTime(policy.last_success_at)}；${policy.last_error ? `错误：${escapeHtml(policy.last_error)}` : "当前无错误摘要"}。</p>
  <p class="policy-note">失败归因：${outcomes}</p>
  <div class="action-row"><button class="button small ghost" data-action="save-mapping-policy">保存</button><button class="button small" data-action="save-and-sync-mapping-policy">保存并立即同步</button></div>`;
}

function mappingReason(reason) {
  const labels = { no_search_candidate: "无搜索候选", first_air_date_mismatch: "首播日不一致", title_not_matched: "标题未精确匹配", multiple_exact_candidates: "候选不唯一", missing_bangumi_title_or_air_date: "Bangumi 数据不完整", candidate_sync_failed: "候选同步失败", animeschedule_search_empty: "AnimeSchedule 空结果", animeschedule_search_error: "AnimeSchedule 来源错误", animeschedule_ambiguous: "AnimeSchedule 候选不唯一", animeschedule_cross_id_invalid: "跨站 ID 无效", animeschedule_year_mismatch: "首播年份冲突", animeschedule_nsfw_rejected: "成人内容已拒绝" };
  return labels[reason] || reason;
}

const loaders = { overview: loadOverview, catalog: loadCatalog, groups: loadGroups, content: loadContent, subscriptions: loadSubscriptions, mappings: loadMappings, notifications: loadNotifications, sources: loadSources };
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
    if (target.dataset.groupPolicySave) {
      const groupId = target.dataset.groupPolicySave;
      const item = state.groups.find((row) => row.group_id === groupId);
      const fields = [...document.querySelectorAll(`[data-group-policy="${CSS.escape(groupId)}"]`)];
      const payload = { expected_version: item.version };
      fields.forEach((node) => { payload[node.dataset.field] = node.type === "checkbox" ? node.checked : node.value; });
      await bridge.apiPost(`groups/${groupId}/update`, payload);
      toast("LLM 与固定 @ 设置已保存"); return loadGroups();
    }
    if (target.dataset.action === "save-mention-policy") {
      const aliases = {};
      document.querySelectorAll("[data-mention-action]").forEach((node) => {
        aliases[node.dataset.mentionAction] = node.value.split("\n").map((value) => value.trim()).filter(Boolean);
      });
      await bridge.apiPost("mention-policy/update", { expected_version: state.mentionPolicy.version, aliases });
      toast("全局固定短语已保存"); return loadGroups();
    }
    if (target.dataset.action === "restore-mention-policy") {
      if (!await confirmAction("恢复默认固定短语", "所有群会立即恢复内置固定短语。")) return;
      await bridge.apiPost("mention-policy/restore", { expected_version: state.mentionPolicy.version });
      toast("已恢复默认固定短语"); return loadGroups();
    }
    if (target.dataset.action === "refresh-content") return loadContent();
    if (target.dataset.contentSave) {
      const groupId = target.dataset.contentSave;
      const item = state.groups.find((row) => row.group_id === groupId);
      const fields = [...document.querySelectorAll(`[data-content-group="${CSS.escape(groupId)}"]`)];
      const payload = { expected_version: item.version };
      fields.forEach((node) => {
        if (node.type === "checkbox") payload[node.dataset.field] = node.checked;
        else if (node.type === "time") payload[node.dataset.field] = timeToMinute(node.value);
        else payload[node.dataset.field] = Number(node.value);
      });
      await bridge.apiPost(`groups/${groupId}/update`, payload);
      toast("内容运营设置已保存"); return loadContent();
    }
    if (target.dataset.action === "suggest-poll") {
      const items = await bridge.apiGet("content-candidates", { group_id: $("#poll-group").value, theme: $("#poll-theme").value });
      renderPollCandidates(items); return;
    }
    if (target.dataset.action === "open-poll") {
      const animeIds = [...document.querySelectorAll("[data-poll-anime]:checked")].map((node) => node.dataset.pollAnime);
      if (animeIds.length < 3 || animeIds.length > 6) throw new Error("请选择 3–6 个候选");
      await bridge.apiPost("content-polls/open", { group_id: $("#poll-group").value, theme: $("#poll-theme").value, duration_hours: Number($("#poll-duration").value), anime_ids: animeIds });
      toast("投票已进入发送队列"); renderPollCandidates([]); return loadContent();
    }
    if (target.dataset.closePoll) {
      if (!await confirmAction("结束投票", "将立即结算并向群内发送结果。")) return;
      await bridge.apiPost(`content-polls/${target.dataset.closePoll}/close`, {});
      toast("投票已结算"); return loadContent();
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
        animeschedule_enabled: $("#animeschedule-enabled").checked,
        animeschedule_query_budget: Number($("#animeschedule-query-budget").value),
        animeschedule_priority_window_days: Number($("#animeschedule-priority-window").value),
        animeschedule_empty_cooldown_hours: Number($("#animeschedule-empty-cooldown").value),
        animeschedule_error_cooldown_hours: Number($("#animeschedule-error-cooldown").value),
      };
      await bridge.apiPost("mapping-policy", payload);
      if (target.dataset.action === "save-and-sync-mapping-policy") {
        await bridge.apiPost("jobs/enqueue", { job_type: payload.animeschedule_enabled ? "sync_animeschedule" : "sync_anilist_mapping", idempotency_key: `anime-mapping-${Date.now()}`, parameters: {} });
        toast("策略已保存，映射与排期同步已创建");
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
