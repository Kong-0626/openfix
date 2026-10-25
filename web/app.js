"use strict";

const state = {
  overview: null,
  diagnosis: null,
  orders: [],
  decision: null,
};

const elements = {
  healthDot: document.querySelector("#health-dot"),
  healthLabel: document.querySelector("#health-label"),
  statsStrip: document.querySelector("#stats-strip"),
  form: document.querySelector("#diagnosis-form"),
  assetSelect: document.querySelector("#asset-select"),
  symptomInput: document.querySelector("#symptom-input"),
  charCount: document.querySelector("#char-count"),
  inputError: document.querySelector("#input-error"),
  analyzeButton: document.querySelector("#analyze-button"),
  sampleList: document.querySelector("#sample-list"),
  result: document.querySelector("#diagnosis-result"),
  resultContent: document.querySelector("#result-content"),
  workOrderList: document.querySelector("#work-order-list"),
  auditList: document.querySelector("#audit-list"),
  workOrderDialog: document.querySelector("#work-order-dialog"),
  workOrderForm: document.querySelector("#work-order-form"),
  workPriority: document.querySelector("#work-priority"),
  workActor: document.querySelector("#work-actor"),
  workConfirm: document.querySelector("#work-confirm"),
  workOrderError: document.querySelector("#work-order-error"),
  decisionDialog: document.querySelector("#decision-dialog"),
  decisionForm: document.querySelector("#decision-form"),
  decisionTitle: document.querySelector("#decision-title"),
  decisionIntro: document.querySelector("#decision-intro"),
  decisionApprover: document.querySelector("#decision-approver"),
  decisionReason: document.querySelector("#decision-reason"),
  decisionReasonLabel: document.querySelector("#decision-reason-label"),
  decisionConfirmRow: document.querySelector("#decision-confirm-row"),
  decisionConfirm: document.querySelector("#decision-confirm"),
  decisionError: document.querySelector("#decision-error"),
  decisionSubmit: document.querySelector("#decision-submit"),
  evaluationStatus: document.querySelector("#evaluation-status"),
  evaluationNote: document.querySelector("#evaluation-note"),
  metricGrid: document.querySelector("#metric-grid"),
  toastRegion: document.querySelector("#toast-region"),
};

const escapeHtml = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

const formatDate = (value) => {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return escapeHtml(value);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
};

async function api(path, options = {}) {
  const request = {
    method: options.method || "GET",
    headers: { Accept: "application/json" },
  };
  if (options.body !== undefined) {
    request.headers["Content-Type"] = "application/json";
    request.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, request);
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`服务返回了无法解析的响应（HTTP ${response.status}）`);
  }
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || `请求失败（HTTP ${response.status}）`);
  }
  return payload.data;
}

function toast(message, isError = false) {
  const item = document.createElement("div");
  item.className = `toast${isError ? " is-error" : ""}`;
  item.textContent = message;
  elements.toastRegion.append(item);
  window.setTimeout(() => item.remove(), 3600);
}

function setHealth(online, label) {
  elements.healthDot.classList.toggle("is-online", online);
  elements.healthDot.classList.toggle("is-offline", !online);
  elements.healthLabel.textContent = label;
}

function renderOverview(data) {
  state.overview = data;
  const stats = data.stats;
  const values = [
    [stats.assets, "接入设备"],
    [stats.knowledge_records, "知识规程"],
    [stats.historical_cases, "历史案例"],
    [12, "评测任务"],
  ];
  elements.statsStrip.innerHTML = values
    .map(
      ([value, label]) =>
        `<div class="stat"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`,
    )
    .join("");

  elements.assetSelect.innerHTML = [
    '<option value="">系统根据描述自动识别</option>',
    ...data.assets.map(
      (asset) =>
        `<option value="${escapeHtml(asset.id)}">${escapeHtml(asset.id)} · ${escapeHtml(asset.name)}</option>`,
    ),
  ].join("");

  elements.sampleList.innerHTML = data.sample_queries
    .map((query, index) => {
      const danger = index === data.sample_queries.length - 1;
      const label = ["空压机高温", "冷却泵汽蚀", "伺服过载", "高危请求"][index] || `示例 ${index + 1}`;
      return `<button type="button" class="sample-chip${danger ? " sample-chip--danger" : ""}" data-sample="${index}">${escapeHtml(label)}</button>`;
    })
    .join("");
}

async function loadOverview() {
  try {
    const [health, overview] = await Promise.all([api("/api/health"), api("/api/overview")]);
    if (health.status !== "ok") throw new Error("服务未就绪");
    setHealth(true, "本地服务在线");
    renderOverview(overview);
  } catch (error) {
    setHealth(false, "服务不可用");
    toast(error.message, true);
  }
}

function renderResult(result) {
  state.diagnosis = result;
  elements.result.hidden = false;

  const safety = result.safety || {};
  const safetyRequired = Boolean(safety.required);
  const safetyTitle = safetyRequired
    ? `${safety.level === "critical" ? "严重" : "高"}风险 · 暂停执行危险操作`
    : "未命中高危规则 · 仍需现场安全确认";
  const confidence = Math.max(0, Math.min(100, Number(result.confidence) || 0));
  const candidates = result.candidates || [];
  const actions = result.actions || [];
  const evidence = result.evidence || [];
  const missing = result.missing_information || [];
  const graphNodes = result.graph?.nodes || [];
  const assetLabel = result.asset
    ? `${escapeHtml(result.asset.id)} · ${escapeHtml(result.asset.name)}`
    : "未指定设备";
  const statusLabel = result.status === "input_required" ? "信息不足" : "等待人工复核";

  const candidateHtml = candidates.length
    ? `<ol class="candidate-list">${candidates
        .map(
          (item) => `
          <li>
            <span class="likelihood">${escapeHtml(item.likelihood)}</span>
            <p>${escapeHtml(item.cause)}</p>
            <div class="candidate-meta">${escapeHtml(item.basis)} · 证据 ${escapeHtml(item.evidence_ids.join(" / "))}</div>
          </li>`,
        )
        .join("")}</ol>`
    : '<p class="candidate-meta">系统没有生成故障根因假设。</p>';

  const actionHtml = actions.length
    ? `<ol class="action-list">${actions
        .map(
          (item) => `
          <li>
            <span class="action-phase">${escapeHtml(item.phase)}</span>
            ${escapeHtml(item.action)}
          </li>`,
        )
        .join("")}</ol>`
    : '<p class="candidate-meta">请先补充信息，系统不会在没有证据时生成检修步骤。</p>';

  const evidenceHtml = evidence.length
    ? `<ul class="evidence-list">${evidence
        .map(
          (item) => `
          <li>
            <div class="evidence-head">
              <strong>${escapeHtml(item.title)}</strong>
              <span class="source-badge">${escapeHtml(item.type)}</span>
            </div>
            <p>${escapeHtml(item.excerpt)}</p>
            <div class="evidence-reasons">${(item.reasons || [])
              .map((reason) => `<span>${escapeHtml(reason)}</span>`)
              .join("")}</div>
          </li>`,
        )
        .join("")}</ul>`
    : '<p class="candidate-meta">当前没有足够证据。</p>';

  const missingHtml = missing.length
    ? `<ul class="missing-list">${missing.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
    : '<p class="candidate-meta">关键信息基本完整，仍需复核测量值与现场状态。</p>';

  const graphHtml = graphNodes.length
    ? graphNodes
        .map((node, index) => {
          const arrow = index ? '<span class="chain-arrow" aria-hidden="true"></span>' : "";
          return `${arrow}<div class="chain-node${node.kind === "safety" ? " is-safety" : ""}"><strong>${escapeHtml(node.label)}</strong><span>${escapeHtml(node.kind)}</span></div>`;
        })
        .join("")
    : '<span class="candidate-meta">无证据链</span>';

  const canCreateOrder = result.status !== "input_required" && actions.length > 0;

  elements.resultContent.innerHTML = `
    <article class="card result-shell">
      <header class="result-top">
        <div>
          <div class="result-id">${escapeHtml(assetLabel)} · ${escapeHtml(result.request_id)} · ${escapeHtml(statusLabel)}</div>
          <h2>诊断结果与证据包</h2>
          <p>${escapeHtml(result.summary)}</p>
        </div>
        <div class="confidence" aria-label="诊断置信度 ${confidence}%">
          <svg viewBox="0 0 100 100" aria-hidden="true">
            <circle class="confidence-track" cx="50" cy="50" r="43"></circle>
            <circle class="confidence-ring" cx="50" cy="50" r="43"></circle>
          </svg>
          <div><strong>${confidence}%</strong><small>${escapeHtml(result.confidence_label)}</small></div>
        </div>
      </header>
      <div class="safety-banner${safetyRequired ? "" : " is-normal"}">
        <span class="safety-symbol" aria-hidden="true">${safetyRequired ? "!" : "✓"}</span>
        <div>
          <strong>${escapeHtml(safetyTitle)}</strong>
          <span>${escapeHtml(safety.summary || "")}</span>
        </div>
      </div>
      <div class="result-body">
        <div>
          <section class="result-block">
            <span class="micro-label">HYPOTHESES</span>
            <h3>可能的根因</h3>
            ${candidateHtml}
          </section>
          <section class="result-block">
            <span class="micro-label">${safetyRequired ? "IMMEDIATE ACTIONS" : "NEXT ACTIONS"}</span>
            <h3>${safetyRequired ? "先执行安全处置" : "建议排查步骤"}</h3>
            ${actionHtml}
          </section>
        </div>
        <div class="result-side">
          <section class="result-block">
            <span class="micro-label">EVIDENCE</span>
            <h3>证据来源</h3>
            ${evidenceHtml}
          </section>
          <section class="result-block">
            <span class="micro-label">GAPS</span>
            <h3>仍需补充</h3>
            ${missingHtml}
          </section>
        </div>
      </div>
      <section class="evidence-chain">
        <span class="micro-label">EVIDENCE CHAIN</span>
        <div class="chain-nodes">${graphHtml}</div>
      </section>
      <footer class="result-footer">
        <p>${escapeHtml(result.disclaimer)}</p>
        ${
          canCreateOrder
            ? '<button type="button" class="button button--primary" data-action="create-order">转为待审批工单</button>'
            : ""
        }
      </footer>
    </article>
  `;

  const ring = elements.resultContent.querySelector(".confidence-ring");
  if (ring) {
    const circumference = 2 * Math.PI * 43;
    ring.setAttribute("stroke-dasharray", String(circumference));
    ring.setAttribute("stroke-dashoffset", String(circumference * (1 - confidence / 100)));
  }

  elements.result.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function submitDiagnosis(event) {
  event.preventDefault();
  const query = elements.symptomInput.value.trim();
  const assetId = elements.assetSelect.value || null;
  elements.inputError.textContent = "";

  if (!query) {
    elements.inputError.textContent = "请先描述设备现象。";
    elements.symptomInput.focus();
    return;
  }
  if (query.length > 1000) {
    elements.inputError.textContent = "故障描述不能超过 1000 个字符。";
    return;
  }

  elements.analyzeButton.disabled = true;
  elements.analyzeButton.classList.add("is-loading");
  elements.analyzeButton.querySelector(".button-label").textContent = "正在检索证据";
  try {
    const result = await api("/api/diagnose", {
      method: "POST",
      body: { query, asset_id: assetId },
    });
    renderResult(result);
  } catch (error) {
    elements.inputError.textContent = error.message;
    toast(error.message, true);
  } finally {
    elements.analyzeButton.disabled = false;
    elements.analyzeButton.classList.remove("is-loading");
    elements.analyzeButton.querySelector(".button-label").textContent = "生成证据诊断";
  }
}

function loadSample(index) {
  if (!state.overview) return;
  const query = state.overview.sample_queries[index];
  if (!query) return;
  elements.symptomInput.value = query;
  elements.charCount.textContent = `${query.length} / 1000`;
  elements.inputError.textContent = "";
  const matchedAsset = state.overview.assets.find((asset) => query.includes(asset.id));
  elements.assetSelect.value = matchedAsset?.id || "";
  elements.symptomInput.focus();
}

function openWorkOrderDialog() {
  if (!state.diagnosis) return;
  elements.workOrderError.textContent = "";
  elements.workActor.value = "";
  elements.workConfirm.checked = false;
  elements.workPriority.value = state.diagnosis.safety?.required ? "P1" : "P2";
  showDialog(elements.workOrderDialog);
}

function showDialog(dialog) {
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
}

function closeDialog(dialog) {
  if (typeof dialog.close === "function") dialog.close();
  else dialog.removeAttribute("open");
}

async function createWorkOrder(event) {
  event.preventDefault();
  const actor = elements.workActor.value.trim();
  elements.workOrderError.textContent = "";
  if (!actor) {
    elements.workOrderError.textContent = "请填写创建人。";
    return;
  }
  if (!elements.workConfirm.checked) {
    elements.workOrderError.textContent = "请确认已核对诊断内容与安全边界。";
    return;
  }
  const result = state.diagnosis;
  const submit = elements.workOrderForm.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    const order = await api("/api/work-orders", {
      method: "POST",
      body: {
        diagnosis_id: result.request_id,
        asset_id: result.asset?.id || null,
        priority: elements.workPriority.value,
        title: result.asset ? `${result.asset.id} 检修诊断工单` : "设备检修诊断工单",
        summary: result.summary,
        actions: result.actions,
        evidence_ids: result.evidence.map((item) => item.id),
        actor,
      },
    });
    closeDialog(elements.workOrderDialog);
    toast(`工单 ${order.id} 已创建，等待人工审批。`);
    await Promise.all([refreshOrders(), refreshAudit()]);
    document.querySelector("#orders").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    elements.workOrderError.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
}

function statusBadge(status) {
  const map = {
    pending_approval: ["is-pending", "待审批"],
    approved: ["is-approved", "已批准"],
    rejected: ["is-rejected", "已驳回"],
  };
  const [className, label] = map[status] || ["is-pending", escapeHtml(status)];
  return `<span class="status-badge ${className}">${label}</span>`;
}

function renderOrders(orders) {
  state.orders = orders;
  if (!orders.length) {
    elements.workOrderList.innerHTML =
      '<div class="empty-state"><strong>暂无工单</strong><span>完成一次诊断后，可将结果转为待审批工单。</span></div>';
    return;
  }
  elements.workOrderList.innerHTML = orders
    .map(
      (order) => `
      <article class="work-order">
        <div class="work-order-head">
          <div>
            <span class="work-order-id">${escapeHtml(order.id)} · ${escapeHtml(order.priority)}</span>
            <h4>${escapeHtml(order.title)}</h4>
          </div>
          ${statusBadge(order.status)}
        </div>
        <p>${escapeHtml(order.summary)}</p>
        <p>创建：${formatDate(order.created_at)} · 步骤 ${order.actions.length} 条 · 证据 ${order.evidence_ids.length} 条</p>
        ${
          order.status === "pending_approval"
            ? `<div class="order-actions">
                <button type="button" class="mini-button" data-order-id="${escapeHtml(order.id)}" data-decision="approve">批准</button>
                <button type="button" class="mini-button mini-button--danger" data-order-id="${escapeHtml(order.id)}" data-decision="reject">驳回</button>
              </div>`
            : order.approver
              ? `<p>处理人：${escapeHtml(order.approver)}${order.rejection_reason ? ` · 原因：${escapeHtml(order.rejection_reason)}` : ""}</p>`
              : ""
        }
      </article>`,
    )
    .join("");
}

function renderAudit(events) {
  if (!events.length) {
    elements.auditList.innerHTML =
      '<div class="empty-state"><strong>尚无审计事件</strong><span>工单创建或审批后会在这里留痕。</span></div>';
    return;
  }
  const labels = {
    "work_order.created": "创建工单",
    "work_order.approved": "批准工单",
    "work_order.rejected": "驳回工单",
  };
  elements.auditList.innerHTML = events
    .map(
      (event) => `
      <div class="audit-item">
        <span class="audit-dot" aria-hidden="true"></span>
        <div>
          <strong>${escapeHtml(labels[event.action] || event.action)} · ${escapeHtml(event.object_id)}</strong>
          <small>${escapeHtml(event.actor)} · ${formatDate(event.created_at)}</small>
        </div>
      </div>`,
    )
    .join("");
}

async function refreshOrders() {
  try {
    renderOrders(await api("/api/work-orders?limit=20"));
  } catch (error) {
    toast(error.message, true);
  }
}

async function refreshAudit() {
  try {
    renderAudit(await api("/api/audit?limit=30"));
  } catch (error) {
    toast(error.message, true);
  }
}

function openDecisionDialog(orderId, decision) {
  const order = state.orders.find((item) => item.id === orderId);
  if (!order) return;
  state.decision = { orderId, decision };
  const isApprove = decision === "approve";
  elements.decisionTitle.textContent = isApprove ? "批准检修工单" : "驳回检修工单";
  elements.decisionIntro.textContent = `${order.id} · ${order.title}。审批动作会进入审计轨迹。`;
  elements.decisionSubmit.textContent = isApprove ? "确认批准" : "确认驳回";
  elements.decisionReason.hidden = isApprove;
  elements.decisionReasonLabel.hidden = isApprove;
  elements.decisionConfirmRow.hidden = !isApprove;
  elements.decisionReason.value = "";
  elements.decisionApprover.value = "";
  elements.decisionConfirm.checked = false;
  elements.decisionError.textContent = "";
  showDialog(elements.decisionDialog);
}

async function submitDecision(event) {
  event.preventDefault();
  if (!state.decision) return;
  const approver = elements.decisionApprover.value.trim();
  elements.decisionError.textContent = "";
  if (approver.length < 2) {
    elements.decisionError.textContent = "审批人姓名至少 2 个字符。";
    return;
  }
  const isApprove = state.decision.decision === "approve";
  if (isApprove && !elements.decisionConfirm.checked) {
    elements.decisionError.textContent = "请完成现场安全条件确认。";
    return;
  }
  const reason = elements.decisionReason.value.trim();
  if (!isApprove && !reason) {
    elements.decisionError.textContent = "驳回时必须填写原因。";
    return;
  }
  elements.decisionSubmit.disabled = true;
  try {
    const payload = isApprove
      ? { approver, confirmation: "确认安全条件并批准工单" }
      : { approver, reason };
    await api(`/api/work-orders/${encodeURIComponent(state.decision.orderId)}/${state.decision.decision}`, {
      method: "POST",
      body: payload,
    });
    closeDialog(elements.decisionDialog);
    toast(isApprove ? "工单已批准并记录审计事件。" : "工单已驳回并记录审计事件。");
    await Promise.all([refreshOrders(), refreshAudit()]);
  } catch (error) {
    elements.decisionError.textContent = error.message;
  } finally {
    elements.decisionSubmit.disabled = false;
  }
}

async function loadEvaluation() {
  try {
    const report = await api("/api/evaluation");
    const metrics = [
      ["知识召回", report.knowledge_evidence_recall, "Expected evidence in top 5"],
      ["案例召回", report.case_evidence_recall, "Historical case retrieval"],
      ["拒答准确率", report.abstention_accuracy, "Abstain when evidence is weak"],
      ["安全门命中率", report.safety_gate_accuracy, "Deterministic safety rules"],
    ];
    elements.evaluationStatus.innerHTML = `
      <span class="evaluation-mark">${report.passed ? "✓" : "!"}</span>
      <div>
        <strong>${report.passed ? "全部评测通过" : "存在未通过用例"}</strong>
        <small>${report.total_cases} 条本地测试任务 · 自动复现</small>
      </div>`;
    elements.evaluationNote.textContent = report.note;
    elements.metricGrid.innerHTML = metrics
      .map(
        ([label, value, note]) => `
        <div class="metric">
          <span>${escapeHtml(label)}</span>
          <strong>${(Number(value) * 100).toFixed(0)}%</strong>
          <small>${escapeHtml(note)}</small>
        </div>`,
      )
      .join("");
  } catch (error) {
    elements.evaluationStatus.innerHTML =
      '<span class="evaluation-mark">!</span><div><strong>评测暂不可用</strong><small>请检查本地服务</small></div>';
    elements.evaluationNote.textContent = error.message;
  }
}

elements.form.addEventListener("submit", submitDiagnosis);
elements.symptomInput.addEventListener("input", () => {
  elements.charCount.textContent = `${elements.symptomInput.value.length} / 1000`;
  elements.inputError.textContent = "";
});
elements.symptomInput.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    elements.form.requestSubmit();
  }
});
elements.sampleList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-sample]");
  if (button) loadSample(Number(button.dataset.sample));
});
elements.resultContent.addEventListener("click", (event) => {
  if (event.target.closest('[data-action="create-order"]')) openWorkOrderDialog();
});
elements.workOrderForm.addEventListener("submit", createWorkOrder);
elements.workOrderList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-decision]");
  if (button) openDecisionDialog(button.dataset.orderId, button.dataset.decision);
});
elements.decisionForm.addEventListener("submit", submitDecision);
document.querySelectorAll("[data-close-dialog]").forEach((button) => {
  button.addEventListener("click", () => {
    const dialog = document.getElementById(button.dataset.closeDialog);
    if (dialog) closeDialog(dialog);
  });
});
document.querySelector("#refresh-orders").addEventListener("click", refreshOrders);
document.querySelector("#refresh-audit").addEventListener("click", refreshAudit);

Promise.allSettled([loadOverview(), refreshOrders(), refreshAudit(), loadEvaluation()]);
