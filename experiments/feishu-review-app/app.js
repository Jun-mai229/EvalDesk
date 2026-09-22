const state = {
  bundle: null,
  results: null,
  selectedRow: null,
  filter: "all",
  saveTimer: null,
  reviewer: "",
};

const $ = (id) => document.getElementById(id);
const LAST_BUNDLE_KEY = "evaldesk-review:last-bundle";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function storageKey(bundle) {
  return `evaldesk-review:${bundle.package_id}`;
}

function validateBundle(bundle) {
  if (!bundle || bundle.bundle_version !== 1) throw new Error("任务包版本不受支持");
  if (!bundle.package_id || !bundle.source_snapshot || !bundle.schema) {
    throw new Error("任务包缺少来源信息");
  }
  if (!Array.isArray(bundle.tasks) || !bundle.tasks.length) {
    throw new Error("任务包中没有可审阅任务");
  }
  if (!Array.isArray(bundle.schema.dimensions) || !bundle.schema.dimensions.length) {
    throw new Error("任务包没有评分维度");
  }
  if (!bundle.baseline_results || bundle.baseline_results.version !== 2) {
    throw new Error("任务包缺少初始结果");
  }
  const rows = new Set(bundle.tasks.map((task) => String(task.row)));
  if (rows.size !== bundle.tasks.length) throw new Error("任务包存在重复任务行");
  if (rows.size !== Object.keys(bundle.baseline_results.rows || {}).length) {
    throw new Error("任务与初始结果数量不一致");
  }
  rows.forEach((row) => {
    if (!bundle.baseline_results.rows[row]) throw new Error(`任务 ${row} 缺少初始结果`);
  });
}

function loadSaved(bundle) {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey(bundle)) || "null");
    if (
      saved?.package_id === bundle.package_id &&
      saved?.source_revision === bundle.source_snapshot.revision &&
      saved?.results?.version === 2
    ) {
      return saved;
    }
  } catch (_error) {
    // Invalid local data is ignored; the package baseline remains authoritative.
  }
  return null;
}

function loadBundle(bundle) {
  validateBundle(bundle);
  const saved = loadSaved(bundle);
  state.bundle = bundle;
  state.results = saved?.results || clone(bundle.baseline_results);
  state.reviewer = saved?.reviewer || "";
  state.selectedRow = bundle.tasks[0].row;
  state.filter = "all";
  $("reviewerName").value = state.reviewer;
  $("sheetName").textContent = bundle.source_snapshot.sheet_name || "评测任务";
  $("importScreen").hidden = true;
  $("app").hidden = false;
  render();
  persistNow();
}

async function readBundleFile(file) {
  if (!file) return;
  $("importError").textContent = "";
  try {
    const bundle = JSON.parse(await file.text());
    loadBundle(bundle);
  } catch (error) {
    $("importError").textContent = `无法载入：${error.message}`;
  }
}

async function loadDemo() {
  $("importError").textContent = "";
  try {
    const response = await fetch("./demo-bundle.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    loadBundle(await response.json());
  } catch (error) {
    $("importError").textContent = `演示任务载入失败：${error.message}`;
  }
}

function currentTask() {
  return state.bundle.tasks.find((task) => task.row === state.selectedRow) || state.bundle.tasks[0];
}

function resultFor(task) {
  return state.results.rows[String(task.row)];
}

function isRegistered(task) {
  return Boolean(resultFor(task)?.saved_at);
}

function visibleTasks() {
  if (state.filter === "all") return state.bundle.tasks;
  return state.bundle.tasks.filter((task) => (
    state.filter === "done" ? isRegistered(task) : !isRegistered(task)
  ));
}

function markChanged(task) {
  const result = resultFor(task);
  result.updated_at = new Date().toISOString();
  result.saved_at = null;
  schedulePersist();
  renderQueue();
  renderProgress();
}

function schedulePersist() {
  clearTimeout(state.saveTimer);
  setSaveState("保存中", "saving");
  state.saveTimer = setTimeout(persistNow, 180);
}

function persistNow() {
  clearTimeout(state.saveTimer);
  if (!state.bundle || !state.results) return;
  state.results.updated_at = new Date().toISOString();
  try {
    localStorage.setItem(LAST_BUNDLE_KEY, JSON.stringify(state.bundle));
    localStorage.setItem(storageKey(state.bundle), JSON.stringify({
      package_id: state.bundle.package_id,
      source_revision: state.bundle.source_snapshot.revision,
      reviewer: state.reviewer,
      results: state.results,
    }));
    setSaveState("本地已保存");
  } catch (error) {
    setSaveState("保存失败", "error");
    showToast(`浏览器存储失败：${error.message}`);
  }
}

function setSaveState(text, mode = "") {
  $("saveState").textContent = text;
  $("saveState").className = `save-state ${mode}`;
}

function showToast(message) {
  $("toast").textContent = message;
  $("toast").classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => $("toast").classList.remove("show"), 1800);
}

function scoreArray(value, count) {
  const source = Array.isArray(value) ? value : value === "" || value == null ? [] : [value];
  return [...source.map((item) => String(item ?? "")), ...Array(count).fill("")].slice(0, count);
}

function normalizeCurrentResult(task) {
  const result = resultFor(task);
  const count = task.outputs.length;
  state.bundle.schema.dimensions.forEach((dimension) => {
    result.dimensions[dimension.key].human_score = scoreArray(
      result.dimensions[dimension.key].human_score,
      count,
    );
  });
  result.mos = scoreArray(result.mos, count);
}

function renderQueue() {
  const list = $("taskList");
  list.replaceChildren();
  const tasks = visibleTasks();
  tasks.forEach((task) => {
    const button = element("button", "task");
    button.type = "button";
    if (task.row === state.selectedRow) button.classList.add("active");
    if (isRegistered(task)) button.classList.add("registered");
    button.append(element("span", "task-number", String(state.bundle.tasks.indexOf(task) + 1).padStart(2, "0")));
    const copyNode = element("span", "task-copy");
    copyNode.append(element("strong", "", `案例 ${task.id}`));
    copyNode.append(element("span", "", task.prompt));
    button.append(copyNode, element("i", "status-dot"));
    button.addEventListener("click", () => {
      state.selectedRow = task.row;
      render();
    });
    list.append(button);
  });
  if (!tasks.length) list.append(element("p", "empty-media", "当前筛选下没有任务"));
}

function renderProgress() {
  const done = state.bundle.tasks.filter(isRegistered).length;
  const total = state.bundle.tasks.length;
  $("progressText").textContent = `${done} / ${total}`;
  $("progressBar").style.width = `${total ? done / total * 100 : 0}%`;
}

function renderMediaItem(url, kind, label, output = false) {
  const figure = element("figure");
  const media = document.createElement(kind === "video" ? "video" : "img");
  if (kind === "video") {
    media.controls = true;
    media.preload = "metadata";
    media.playsInline = true;
  } else {
    media.alt = label;
    media.loading = "lazy";
  }
  media.src = url;
  media.addEventListener("error", () => {
    media.hidden = true;
    figure.prepend(element("div", "media-error", "素材无法直接加载，可使用下方原链接查看"));
  });
  const caption = element("figcaption");
  caption.append(element("strong", "", label));
  const link = element("a", "", "原链接");
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  caption.append(link);
  figure.append(media, caption);
  if (output) figure.dataset.output = label;
  return figure;
}

function renderMedia(task) {
  const references = $("references");
  references.replaceChildren();
  $("referenceSection").hidden = !task.references.length;
  task.references.forEach((url, index) => {
    references.append(renderMediaItem(
      url,
      task.reference_kinds?.[index] || "image",
      `参考 ${index + 1}`,
    ));
  });
  const outputs = $("outputs");
  outputs.replaceChildren();
  task.outputs.forEach((url, index) => {
    outputs.append(renderMediaItem(
      url,
      task.output_kinds?.[index] || task.kind || "image",
      `输出 ${index + 1}`,
      true,
    ));
  });
}

function option(value, text = value) {
  const node = element("option", "", text);
  node.value = value;
  return node;
}

function scoreSelect(task, dimension, outputIndex) {
  const result = resultFor(task);
  const select = element("select");
  select.setAttribute("aria-label", `${dimension.name} 输出 ${outputIndex + 1}`);
  select.append(option("", "未评分"));
  (state.bundle.options[dimension.key]?.scores || []).forEach((value) => {
    select.append(option(String(value)));
  });
  select.value = result.dimensions[dimension.key].human_score[outputIndex] || "";
  select.addEventListener("change", () => {
    result.dimensions[dimension.key].human_score[outputIndex] = select.value;
    markChanged(task);
  });
  return select;
}

function renderMatrix(task) {
  normalizeCurrentResult(task);
  const head = $("scoreHead");
  const headRow = element("tr");
  headRow.append(element("th", "", "评分维度"));
  task.outputs.forEach((_url, index) => headRow.append(element("th", "", `输出 ${index + 1}`)));
  head.replaceChildren(headRow);

  const body = $("scoreBody");
  body.replaceChildren();
  state.bundle.schema.dimensions.forEach((dimension) => {
    const row = element("tr");
    row.append(element("td", "", dimension.name));
    task.outputs.forEach((_url, index) => {
      const cell = element("td");
      cell.append(scoreSelect(task, dimension, index));
      row.append(cell);
    });
    body.append(row);
  });
  const mosRow = element("tr", "mos-row");
  mosRow.append(element("td", "", "MOS"));
  task.outputs.forEach((_url, index) => {
    const cell = element("td");
    const input = element("input", "mos-input");
    input.type = "number";
    input.min = "1";
    input.max = "5";
    input.step = "0.1";
    input.value = resultFor(task).mos[index] || "";
    input.setAttribute("aria-label", `MOS 输出 ${index + 1}`);
    input.addEventListener("input", () => {
      resultFor(task).mos[index] = input.value;
      markChanged(task);
    });
    cell.append(input);
    mosRow.append(cell);
  });
  body.append(mosRow);
}

function fieldWrapper(label, control) {
  const wrapper = element("label", "field");
  wrapper.append(element("span", "", label), control);
  return wrapper;
}

function renderTags(task, dimension, values) {
  const container = element("div", "tag-options");
  const allowed = state.bundle.options[dimension.key]?.tags || [];
  if (!allowed.length) container.append(element("span", "empty-media", "无标签选项"));
  allowed.forEach((tag) => {
    const label = element("label", "tag-option");
    const checkbox = element("input");
    checkbox.type = "checkbox";
    checkbox.checked = values.includes(tag);
    checkbox.addEventListener("change", () => {
      const next = new Set(values);
      if (checkbox.checked) next.add(tag);
      else next.delete(tag);
      const result = resultFor(task).dimensions[dimension.key];
      result.tags = [...next];
      values = result.tags;
      markChanged(task);
    });
    label.append(checkbox, element("span", "", tag));
    container.append(label);
  });
  return fieldWrapper("问题标签", container);
}

function renderTextField(task, dimension, key, label) {
  const value = resultFor(task).dimensions[dimension.key];
  const textarea = element("textarea");
  textarea.value = value[key] || "";
  textarea.maxLength = 5000;
  textarea.addEventListener("input", () => {
    value[key] = textarea.value;
    markChanged(task);
  });
  return fieldWrapper(label, textarea);
}

function renderSelectField(task, dimension, key, label, values) {
  const result = resultFor(task).dimensions[dimension.key];
  const select = element("select");
  select.append(option("", "未选择"));
  values.forEach((value) => select.append(option(value)));
  select.value = result[key] || "";
  select.addEventListener("change", () => {
    result[key] = select.value;
    markChanged(task);
  });
  return fieldWrapper(label, select);
}

function renderDetails(task) {
  const list = $("detailList");
  list.replaceChildren();
  state.bundle.schema.dimensions.forEach((dimension, index) => {
    const values = resultFor(task).dimensions[dimension.key];
    const editable = new Set(dimension.editable_fields);
    const details = element("details", "dimension-detail");
    if (index === 0) details.open = true;
    details.append(element("summary", "", `${String(index + 1).padStart(2, "0")} ${dimension.name} · 标签与归因`));
    const body = element("div", "detail-body");
    if (editable.has("tags")) body.append(renderTags(task, dimension, values.tags || []));
    if (editable.has("reason")) body.append(renderTextField(task, dimension, "reason", "评分归因"));
    if (editable.has("review_label")) {
      body.append(renderSelectField(
        task,
        dimension,
        "review_label",
        "Review 标签",
        state.bundle.options[dimension.key]?.review_labels || [],
      ));
    }
    if (editable.has("review_reason")) {
      body.append(renderTextField(task, dimension, "review_reason", "Review 归因"));
    }
    details.append(body);
    list.append(details);
  });
}

function render() {
  const task = currentTask();
  state.selectedRow = task.row;
  $("taskKind").textContent = task.kind === "video" ? "视频评测" : "图片评测";
  $("taskTitle").textContent = `案例 ${task.id}`;
  $("prompt").textContent = task.prompt;
  renderQueue();
  renderProgress();
  renderMedia(task);
  renderMatrix(task);
  renderDetails(task);
  const index = state.bundle.tasks.indexOf(task);
  $("previous").disabled = index <= 0;
  $("next").disabled = index >= state.bundle.tasks.length - 1;
}

function navigate(offset) {
  const index = state.bundle.tasks.findIndex((task) => task.row === state.selectedRow);
  const next = state.bundle.tasks[index + offset];
  if (!next) return;
  state.selectedRow = next.row;
  render();
}

function registerAndNext() {
  const task = currentTask();
  if (!state.reviewer.trim()) {
    showToast("请先填写评测人");
    $("reviewerName").focus();
    return;
  }
  const result = resultFor(task);
  const missing = state.bundle.schema.dimensions.some((dimension) => (
    result.dimensions[dimension.key].human_score.some((value) => !String(value).trim())
  ));
  if (missing || result.mos.some((value) => !String(value).trim())) {
    showToast("仍有未填写的维度分或 MOS");
    return;
  }
  result.saved_at = new Date().toISOString();
  result.updated_at = result.saved_at;
  persistNow();
  renderQueue();
  renderProgress();
  const index = state.bundle.tasks.indexOf(task);
  const next = state.bundle.tasks[index + 1];
  if (next) {
    state.selectedRow = next.row;
    render();
  } else {
    showToast("当前任务包已全部登记");
  }
}

function exportResults() {
  persistNow();
  const payload = clone(state.results);
  payload.reviewer = state.reviewer.trim();
  payload.review_package = {
    package_id: state.bundle.package_id,
    sheet_id: state.bundle.source_snapshot.sheet_id,
    source_revision: state.bundle.source_snapshot.revision,
  };
  const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], {type: "application/json"});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `results-${state.bundle.package_id}.json`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
  showToast("结果文件已导出");
}

function showImport() {
  $("app").hidden = true;
  $("importScreen").hidden = false;
  $("bundleInput").value = "";
}

$("bundleInput").addEventListener("change", (event) => readBundleFile(event.target.files[0]));
$("loadDemo").addEventListener("click", loadDemo);
$("changeBundle").addEventListener("click", showImport);
$("exportResults").addEventListener("click", exportResults);
$("saveNext").addEventListener("click", registerAndNext);
$("previous").addEventListener("click", () => navigate(-1));
$("next").addEventListener("click", () => navigate(1));
$("reviewerName").addEventListener("input", (event) => {
  state.reviewer = event.target.value;
  schedulePersist();
});
document.querySelectorAll("[data-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    state.filter = button.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach((item) => item.classList.toggle("active", item === button));
    const tasks = visibleTasks();
    if (tasks.length && !tasks.some((task) => task.row === state.selectedRow)) state.selectedRow = tasks[0].row;
    renderQueue();
    if (tasks.length) render();
  });
});

const fileDrop = $("fileDrop");
["dragenter", "dragover"].forEach((name) => fileDrop.addEventListener(name, (event) => {
  event.preventDefault();
  fileDrop.classList.add("dragging");
}));
["dragleave", "drop"].forEach((name) => fileDrop.addEventListener(name, (event) => {
  event.preventDefault();
  fileDrop.classList.remove("dragging");
}));
fileDrop.addEventListener("drop", (event) => readBundleFile(event.dataTransfer.files[0]));

try {
  const previousBundle = JSON.parse(localStorage.getItem(LAST_BUNDLE_KEY) || "null");
  if (previousBundle) loadBundle(previousBundle);
} catch (_error) {
  localStorage.removeItem(LAST_BUNDLE_KEY);
}
