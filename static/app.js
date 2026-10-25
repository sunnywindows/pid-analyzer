"use strict";

const $ = (id) => document.getElementById(id);
let currentResult = null;
let currentFile = null;

// ---------- 上传 ----------
const dropzone = $("dropzone");
const fileInput = $("fileInput");

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
});
dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => {
  if (fileInput.files.length) setFile(fileInput.files[0]);
});

function setFile(file) {
  const ext = (file.name.split(".").pop() || "").toLowerCase();
  const allowed = ["png", "jpg", "jpeg", "bmp", "webp", "tif", "tiff", "pdf"];
  if (!allowed.includes(ext)) {
    toast("不支持的文件类型，仅支持图片或 PDF", true);
    return;
  }
  currentFile = file;
  $("fileName").textContent = `${file.name}（${formatSize(file.size)}）`;
  $("fileInfo").classList.remove("hidden");
  $("previewWrap").classList.remove("hidden");

  // 图片本地预览；PDF 等分析后由后端返回预览
  if (ext !== "pdf" && file.type.startsWith("image/")) {
    const reader = new FileReader();
    reader.onload = (e) => { $("preview").src = e.target.result; };
    reader.readAsDataURL(file);
  } else {
    $("preview").src = "";
  }
}

$("removeFile").addEventListener("click", () => {
  currentFile = null;
  fileInput.value = "";
  $("fileInfo").classList.add("hidden");
  $("previewWrap").classList.add("hidden");
  $("preview").src = "";
});

function formatSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}

// ---------- 服务商预设 ----------
const PROVIDERS = {
  qwen: { baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-vl-max" },
  glm: { baseUrl: "https://open.bigmodel.cn/api/paas/v4", model: "glm-4v-plus" },
  deepseek: { baseUrl: "https://api.deepseek.com", model: "deepseek-chat" },
  kimi: { baseUrl: "https://api.moonshot.cn/v1", model: "moonshot-v1-8k-vision-preview" },
  openai: { baseUrl: "https://api.openai.com/v1", model: "gpt-6-luna" },
  custom: { baseUrl: "", model: "" },
};
$("provider").addEventListener("change", () => {
  const v = $("provider").value;
  if (!v) return;
  const p = PROVIDERS[v];
  $("baseUrl").value = p.baseUrl;
  $("model").value = p.model;
  if (v === "custom") $("baseUrl").focus();
});

// ---------- 引擎切换 ----------
$("engine").addEventListener("change", () => {
  const v = $("engine").value;
  $("aiSettings").classList.toggle("hidden", v === "local");
});

// 根据运行模式初始化引擎选择
(function initMode() {
  const mode = window.PID_MODE || "both";
  if (mode === "local") {
    // 免 API 版：固定本地智能识别，隐藏引擎与 AI 配置
    $("engine").value = "local";
    $("engineField").classList.add("hidden");
    $("aiSettings").classList.add("hidden");
  } else if (mode === "ai") {
    // 需 API 版：默认 AI 视觉大模型
    $("engine").value = "ai";
    $("engineField").classList.add("hidden");
    $("aiSettings").classList.remove("hidden");
  } else {
    // 双引擎模式：默认本地智能识别（免 API 开箱即用），AI 配置默认折叠
    $("engine").value = "local";
    $("aiSettings").classList.add("hidden");
  }
})();

// ---------- 分析 ----------
$("analyzeBtn").addEventListener("click", analyze);

async function analyze() {
  if (!currentFile) { toast("请先上传图纸文件", true); return; }
  const fd = new FormData();
  fd.append("file", currentFile);
  fd.append("engine", $("engine").value);
  fd.append("api_key", $("apiKey").value.trim());
  fd.append("base_url", $("baseUrl").value.trim());
  fd.append("model", $("model").value.trim());

  showLoading(true, "正在上传图纸…");
  try {
    const resp = await fetch("/api/analyze", { method: "POST", body: fd });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "提交失败");
    const taskId = data.task_id;

    let elapsed = 0;
    for (;;) {
      await sleep(2000);
      elapsed += 2;
      showLoading(true, `正在智能识别图纸…（已等待 ${elapsed} 秒）`);
      const sresp = await fetch(`/api/status/${taskId}`);
      const s = await sresp.json();
      if (s.status === "done") {
        currentResult = s.result;
        renderResult(s.result);
        $("preview").src = "data:image/jpeg;base64," + s.result.preview;
        toast("分析完成");
        break;
      } else if (s.status === "error") {
        throw new Error(s.error || "分析失败");
      } else if (s.status === "not_found") {
        throw new Error("任务已失效，请重新分析");
      }
      if (elapsed > 300) throw new Error("分析超时，请重试");
    }
  } catch (err) {
    toast(err.message || "分析失败，请重试", true);
  } finally {
    showLoading(false);
  }
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

// ---------- 渲染 ----------
const TAB_DEFS = {
  equipment: { title: "位号", cols: ["tag", "type", "description"] },
  instruments: { title: "位号", cols: ["tag", "type", "description"] },
  pipelines: { title: "管线号", cols: ["tag", "type", "description"] },
};
const TAB_LABELS = { equipment: "设备", instruments: "仪表", pipelines: "管线" };
let activeTab = "equipment";

function renderResult(d) {
  $("placeholder").classList.add("hidden");
  $("result").classList.remove("hidden");

  const engineLabel = d.meta.engine === "ai" ? "AI 视觉大模型" : "本地智能识别";
  $("summaryCard").innerHTML =
    `<div class="s-title">📋 图纸概要</div>
     <div>${escapeHtml(d.summary || "（无概要）")}</div>
     <div class="s-flow"><b>工艺物料流向：</b>${escapeHtml(d.flow || "（未识别）")}</div>`;

  $("metaBar").innerHTML = [
    chip("文件", d.meta.filename),
    chip("引擎", engineLabel),
    chip("模型", d.meta.model || "—"),
    chip("页数", d.meta.pages),
    chip("尺寸", d.meta.dimensions),
    chip("时间", d.meta.analyzed_at),
  ].join("");

  $("cntEquipment").textContent = d.equipment.length;
  $("cntInstruments").textContent = d.instruments.length;
  $("cntPipelines").textContent = d.pipelines.length;

  renderFindings(d.findings);
  switchTab("equipment");
}

function chip(label, value) {
  return `<span class="chip">${label}：<b>${escapeHtml(String(value ?? "—"))}</b></span>`;
}

function switchTab(tab) {
  activeTab = tab;
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.tab === tab));
  const def = TAB_DEFS[tab];
  const rows = currentResult[tab] || [];
  const thead = $("dataTable").querySelector("thead");
  const tbody = $("dataTable").querySelector("tbody");

  const headers = { tag: def.title, type: "类型", description: "说明" };
  thead.innerHTML = "<tr>" + Object.values(headers).map((h) => `<th>${h}</th>`).join("") + "</tr>";

  if (!rows.length) {
    tbody.innerHTML = `<tr class="empty-row"><td colspan="3">未识别到${TAB_LABELS[tab]}</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map((r) =>
    `<tr>
       <td class="tag">${escapeHtml(r.tag)}</td>
       <td>${escapeHtml(r.type || "—")}</td>
       <td>${escapeHtml(r.description || "—")}</td>
     </tr>`).join("");
}

document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => switchTab(t.dataset.tab)));

function renderFindings(findings) {
  const box = $("findings");
  if (!findings || !findings.length) { box.innerHTML = ""; return; }
  box.innerHTML = `<h3>⚠ 发现与建议</h3><ul class="warn">` +
    findings.map((f) => `<li>${escapeHtml(f)}</li>`).join("") + "</ul>";
}

// ---------- 导出 ----------
$("exportBtn").addEventListener("click", async () => {
  if (!currentResult) return;
  showLoading(true, "正在生成 Excel…");
  try {
    const resp = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentResult),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || "导出失败");
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "P&ID分析结果.xlsx";
    a.click();
    URL.revokeObjectURL(url);
    toast("Excel 已导出");
  } catch (err) {
    toast(err.message || "导出失败", true);
  } finally {
    showLoading(false);
  }
});

// ---------- 通用 ----------
function showLoading(on, text) {
  $("loading").classList.toggle("hidden", !on);
  if (text) $("loadingText").textContent = text;
}

let toastTimer = null;
function toast(msg, isError) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.toggle("error", !!isError);
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 3200);
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
