const state = {
  manifest: null,
  tasks: [],
  results: null,
  index: 0,
  dimension: 0,
  output: 0,
  filter: "all",
  saveTimer: null,
  selectedRow: null,
  dirty: new Map(),
  generation: 0,
  saveChain: Promise.resolve(),
  navigating: false,
  revealed: new Set(),
  expandedTagSections: new Set(),
};

const $ = (id) => document.getElementById(id);
const LAYOUT_STORAGE_KEY = "feishu-eval-workbench-layout-v1";
const REVIEWER_STORAGE_KEY = "feishu-eval-workbench-reviewer-v1";
const DEFAULT_LAYOUT = { left: 232, right: 390, leftCollapsed: false, rightCollapsed: false };
const layoutState = loadLayoutState();

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function loadLayoutState() {
  try {
    return {...DEFAULT_LAYOUT, ...JSON.parse(localStorage.getItem(LAYOUT_STORAGE_KEY) || "{}")};
  } catch (_error) {
    return {...DEFAULT_LAYOUT};
  }
}

function saveLayoutState() {
  try {
    localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(layoutState));
  } catch (_error) {
    // Layout persistence is optional; scoring remains unaffected.
  }
}

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), Math.max(minimum, maximum));
}

function constrainLayout() {
  const total = $("layout").clientWidth;
  if (!total) return;
  const leftHandle = layoutState.leftCollapsed ? 0 : 7;
  const rightHandle = layoutState.rightCollapsed ? 0 : 7;
  const minimumCenter = 300;
  const minimumLeft = 160;
  const minimumRight = 280;
  if (!layoutState.rightCollapsed) {
    const occupiedLeft = layoutState.leftCollapsed ? 0 : minimumLeft + leftHandle;
    layoutState.right = clamp(layoutState.right, minimumRight, total - occupiedLeft - rightHandle - minimumCenter);
  }
  if (!layoutState.leftCollapsed) {
    const occupiedRight = layoutState.rightCollapsed ? 0 : layoutState.right + rightHandle;
    layoutState.left = clamp(layoutState.left, minimumLeft, total - occupiedRight - leftHandle - minimumCenter);
  }
}

function applyLayout(save = false) {
  constrainLayout();
  const layout = $("layout");
  const compact = window.matchMedia("(max-width: 760px)").matches;
  const leftCollapsed = !compact && layoutState.leftCollapsed;
  const rightCollapsed = !compact && layoutState.rightCollapsed;
  layout.style.setProperty("--left-width", `${Math.round(layoutState.left)}px`);
  layout.style.setProperty("--right-width", `${Math.round(layoutState.right)}px`);
  layout.style.setProperty("--left-track", leftCollapsed ? "0px" : "var(--left-width)");
  layout.style.setProperty("--left-divider-track", leftCollapsed ? "0px" : "7px");
  layout.style.setProperty("--right-divider-track", rightCollapsed ? "0px" : "7px");
  layout.style.setProperty("--right-track", rightCollapsed ? "0px" : "var(--right-width)");
  $("leftPanel").hidden = leftCollapsed;
  $("resizeLeft").hidden = leftCollapsed;
  $("restoreLeft").hidden = !leftCollapsed;
  $("rightPanel").hidden = rightCollapsed;
  $("resizeRight").hidden = rightCollapsed;
  $("restoreRight").hidden = !rightCollapsed;
  $("collapseLeft").setAttribute("aria-expanded", String(!leftCollapsed));
  $("restoreLeft").setAttribute("aria-expanded", String(!leftCollapsed));
  $("collapseRight").setAttribute("aria-expanded", String(!rightCollapsed));
  $("restoreRight").setAttribute("aria-expanded", String(!rightCollapsed));
  $("resizeLeft").setAttribute("aria-valuenow", String(Math.round(layoutState.left)));
  $("resizeRight").setAttribute("aria-valuenow", String(Math.round(layoutState.right)));
  if (save) saveLayoutState();
}

function setPanelCollapsed(side, collapsed) {
  layoutState[`${side}Collapsed`] = collapsed;
  applyLayout(true);
}

function resizePanel(side, clientX) {
  const bounds = $("layout").getBoundingClientRect();
  if (side === "left") {
    layoutState.left = clientX - bounds.left;
  } else {
    layoutState.right = bounds.right - clientX;
  }
  applyLayout();
}

function setupResizer(side) {
  const handle = $(`resize${side === "left" ? "Left" : "Right"}`);
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || window.matchMedia("(max-width: 760px)").matches) return;
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    document.body.classList.add("resizing");
  });
  handle.addEventListener("pointermove", (event) => {
    if (!handle.hasPointerCapture(event.pointerId)) return;
    resizePanel(side, event.clientX);
  });
  const finish = (event) => {
    if (!handle.hasPointerCapture(event.pointerId)) return;
    handle.releasePointerCapture(event.pointerId);
    document.body.classList.remove("resizing");
    applyLayout(true);
  };
  handle.addEventListener("pointerup", finish);
  handle.addEventListener("pointercancel", finish);
  handle.addEventListener("dblclick", () => {
    layoutState[side] = DEFAULT_LAYOUT[side];
    applyLayout(true);
  });
  handle.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const direction = event.key === "ArrowRight" ? 1 : -1;
    layoutState[side] += direction * (side === "left" ? 16 : -16);
    applyLayout(true);
  });
}

function initLayout() {
  setupResizer("left");
  setupResizer("right");
  $("collapseLeft").addEventListener("click", () => setPanelCollapsed("left", true));
  $("restoreLeft").addEventListener("click", () => setPanelCollapsed("left", false));
  $("collapseRight").addEventListener("click", () => setPanelCollapsed("right", true));
  $("restoreRight").addEventListener("click", () => setPanelCollapsed("right", false));
  window.addEventListener("resize", () => applyLayout());
  applyLayout();
}

function resultFor(task) {
  return state.results.rows[String(task.row)];
}

function scoreArray(value, count) {
  let items = [];
  if (Array.isArray(value)) {
    items = value.map((item) => item == null ? "" : String(item).trim());
  } else {
    const text = String(value ?? "").trim();
    if (text) {
      try {
        const parsed = JSON.parse(text);
        if (Array.isArray(parsed)) items = parsed.map((item) => item == null ? "" : String(item).trim());
      } catch (_error) {
        items = text.replace(/^\[/, "").replace(/\]$/, "").split(/[,，、]/).map((item) => item.trim());
      }
      if (!items.length) items = [text];
    }
  }
  return [...items, ...Array(Math.max(0, count - items.length)).fill("")];
}

function normalizeResults() {
  state.tasks.forEach((task) => {
    const result = resultFor(task);
    if (!result) return;
    const count = task.outputs.length;
    state.manifest.schema.dimensions.forEach((dimension) => {
      const value = result.dimensions[dimension.key];
      value.human_score = scoreArray(value.human_score, count);
    });
    result.mos = scoreArray(result.mos, count);
  });
  state.results.version = 2;
}

function isOutputDone(task, outputIndex) {
  const result = resultFor(task);
  if (!result) return false;
  if (!state.manifest.schema.dimensions.length) return Boolean(result.mos[outputIndex]);
  return state.manifest.schema.dimensions.every((dimension) => {
    const scores = result.dimensions[dimension.key]?.human_score || [];
    return String(scores[outputIndex] || "").trim() !== "";
  });
}

function isDone(task) {
  return task.outputs.every((_url, index) => isOutputDone(task, index));
}

function visibleTasks() {
  if (state.filter === "all") return state.tasks;
  return state.tasks.filter((task) => state.filter === "done" ? isSaved(task) : !isSaved(task));
}

function currentTask() {
  return state.tasks.find((task) => task.row === state.selectedRow) || visibleTasks()[0] || null;
}

function isSaved(task) {
  return Boolean(resultFor(task)?.saved_at) && !state.dirty.has(String(task.row));
}

function selectTask(task) {
  state.selectedRow = task?.row ?? null;
  state.dimension = 0;
  state.output = 0;
  render();
}

function currentDimension() {
  return state.manifest.schema.dimensions[state.dimension];
}

function setSaveState(text, mode = "") {
  $("saveState").textContent = text;
  $("saveState").className = `status ${mode}`;
}

function showToast(message) {
  $("toast").textContent = message;
  $("toast").classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => $("toast").classList.remove("show"), 1800);
}

function persist(registerTask = null) {
  clearTimeout(state.saveTimer);
  // Capture physical rows before navigation and serialize all writes.
  const versions = new Map(state.dirty);
  if (registerTask) versions.set(String(registerTask.row), state.dirty.get(String(registerTask.row)) || 0);
  const rows = {};
  versions.forEach((_version, row) => { rows[row] = JSON.parse(JSON.stringify(state.results.rows[row])); });
  if (registerTask) rows[String(registerTask.row)].saved_at = new Date().toISOString();
  const operation = async () => {
    if (!Object.keys(rows).length) return true;
    setSaveState("保存中", "saving");
    try {
      const response = await fetch("/api/results", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rows }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "保存失败");
      versions.forEach((version, row) => {
        if ((state.dirty.get(row) || 0) === version) {
          state.dirty.delete(row);
          if (rows[row].saved_at) state.results.rows[row].saved_at = rows[row].saved_at;
        }
      });
      setSaveState(state.dirty.size ? "待保存" : "本地已保存", state.dirty.size ? "saving" : "");
      renderQueue();
      renderProgress();
      return !registerTask || isSaved(registerTask);
    } catch (error) {
      setSaveState(`保存失败：${error.message}`, "error");
      return false;
    }
  };
  state.saveChain = state.saveChain.then(operation, operation);
  return state.saveChain;
}

function queuePersist() {
  const task = currentTask();
  if (!task) return;
  resultFor(task).saved_at = null;
  state.dirty.set(String(task.row), ++state.generation);
  clearTimeout(state.saveTimer);
  setSaveState("待保存", "saving");
  state.saveTimer = setTimeout(() => persist(), 350);
  renderQueue();
  renderProgress();
}

function renderProgress() {
  const done = state.tasks.filter(isSaved).length;
  $("progressText").textContent = `已保存 ${done} / ${state.tasks.length}`;
  $("progressBar").style.width = `${state.tasks.length ? done / state.tasks.length * 100 : 0}%`;
}

function renderQueue() {
  const list = $("taskList");
  const scrollTop = list.scrollTop;
  list.replaceChildren();
  const tasks = visibleTasks();
  const active = currentTask();
  tasks.forEach((task, index) => {
    const button = el("button", `task${active && task.row === active.row ? " active" : ""}${isSaved(task) ? " saved" : ""}`);
    button.dataset.row = task.row;
    const number = el("span", "task-number", String(index + 1));
    const copy = el("span", "task-copy");
    copy.append(el("strong", "", `#${task.id} · ${task.kind === "video" ? "视频" : "图片"}`));
    copy.append(el("span", "", task.prompt));
    const dot = el("i", `dot${isSaved(task) ? " done" : ""}`);
    dot.title = isSaved(task) ? "本地已保存" : "尚未保存登记";
    if (isSaved(task)) copy.append(el("small", "saved-label", "✓ 已保存"));
    button.append(number, copy, dot);
    button.addEventListener("click", () => {
      if (!state.navigating) selectTask(task);
    });
    list.append(button);
  });
  if (!tasks.length) list.append(el("div", "empty", "当前筛选下没有任务"));
  list.scrollTop = scrollTop;
}

function renderMedia(task) {
  const media = $("media");
  const outputTabs = $("outputTabs");
  media.replaceChildren();
  const activeOutput = task.outputs[state.output];
  const outputKind = task.output_kinds?.[state.output] || task.kind;
  const referencePanel = el("section", "reference-panel");
  referencePanel.append(
    sectionHeading("01", "参考素材", `共 ${(task.references || []).length} 项 · 用于对照`),
  );
  const referenceSurface = el("div", "reference-surface");
  const referenceGrid = el("div", "reference-grid");
  const outputPanel = el("section", "output-panel");
  outputPanel.append(
    sectionHeading("02", "待评结果", `当前 ${state.output + 1} / ${task.outputs.length} · 请对此结果评分`),
    outputTabs,
  );
  const appendMedia = (parent, item) => {
    const figure = document.createElement("figure");
    figure.className = item.reference ? "reference-media" : "output-media";
    const node = document.createElement(item.kind === "video" ? "video" : "img");
    node.src = item.url;
    if (item.kind === "video") {
      node.controls = true;
      node.preload = "metadata";
    } else {
      node.alt = item.label;
    }
    const caption = el("figcaption", "", item.label);
    const link = el("a", "media-link", "打开原素材 ↗");
    link.href = item.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    caption.append(link);
    node.addEventListener("error", () => {
      node.hidden = true;
      figure.prepend(el("div", "media-error", "素材加载失败，可打开原素材查看"));
    });
    figure.append(node, caption);
    parent.append(figure);
  };
  (task.references || []).forEach((url, index) => {
    appendMedia(referenceGrid, {
      url, reference: true,
      kind: task.reference_kinds?.[index] || (/\.(mp4|mov|webm|m4v)(?:[?#]|$)/i.test(url) ? "video" : "image"),
      label: `参考素材 ${index + 1}`,
    });
  });
  if (!(task.references || []).length) referenceGrid.append(el("div", "reference-empty", "此 Case 未提供参考素材"));
  referenceSurface.append(referenceGrid);
  referencePanel.append(referenceSurface);
  if (activeOutput) appendMedia(outputPanel, {url: activeOutput, kind: outputKind, label: `待评${outputKind === "video" ? "视频" : "结果图"} ${state.output + 1}`});
  media.append(referencePanel, outputPanel);
}

function sectionHeading(index, title, meta) {
  const heading = el("div", "section-heading");
  heading.append(el("span", "section-index", index));
  const copy = el("div", "section-title");
  copy.append(el("h2", "", title), el("span", "", meta));
  heading.append(copy);
  return heading;
}

function renderOutputTabs(task) {
  const tabs = $("outputTabs");
  if (tabs.dataset.row !== String(task.row)) {
    tabs.replaceChildren();
    tabs.dataset.row = task.row;
    task.outputs.forEach((_url, index) => {
    const button = el(
      "button",
      `${index === state.output ? "active" : ""}${isOutputDone(task, index) ? " done" : ""}`,
      `结果 ${index + 1}`,
    );
    button.addEventListener("click", () => {
      const scrollLeft = tabs.scrollLeft;
      state.output = index;
      renderOutputTabs(task);
      renderMedia(task);
      renderForm();
      renderMos(task);
      tabs.scrollLeft = scrollLeft;
      requestAnimationFrame(() => {
        tabs.scrollLeft = scrollLeft;
      });
    });
    tabs.append(button);
    });
    tabs.scrollLeft = 0;
  }
  [...tabs.children].forEach((button, index) => {
    button.classList.toggle("active", index === state.output);
    button.classList.toggle("done", isOutputDone(task, index));
    button.setAttribute("aria-pressed", String(index === state.output));
  });
  tabs.hidden = task.outputs.length <= 1;
}

function renderTabs() {
  const tabs = $("dimensionTabs");
  if (!tabs.children.length) state.manifest.schema.dimensions.forEach((dimension, index) => {
    const button = el("button", index === state.dimension ? "active" : "", dimension.name);
    button.addEventListener("click", () => {
      state.dimension = index;
      renderTabs();
      renderForm();
    });
    tabs.append(button);
  });
  [...tabs.children].forEach((button, index) => {
    button.classList.toggle("active", index === state.dimension);
    button.setAttribute("aria-pressed", String(index === state.dimension));
  });
}

function updateDimension(field, value) {
  const task = currentTask();
  const dimension = currentDimension();
  const dimensionResult = resultFor(task).dimensions[dimension.key];
  if (field === "human_score") {
    dimensionResult.human_score[state.output] = value;
  } else {
    dimensionResult[field] = value;
  }
  renderProgress();
  renderQueue();
  renderOutputTabs(task);
  queuePersist();
}

function section(label) {
  const wrapper = el("section", "section");
  wrapper.append(el("div", "label", label));
  return wrapper;
}

function scoreAt(value, outputIndex) {
  if (Array.isArray(value)) return value[outputIndex] || "";
  return value || "";
}

function renderComparisons(task, source) {
  if (!source.comparisons?.length) return null;
  const wrapper = section(`历史对照 · ${source.comparisons.length} 轮 · 只读`);
  const grid = el("div", "comparison-grid");
  source.comparisons.forEach((comparison) => {
    const panel = el("article", "comparison");
    const heading = el("div", "comparison-head");
    heading.append(
      el("strong", "", comparison.label),
      el("span", "", `人评 ${scoreAt(comparison.human_score, state.output) || "未填"}`),
    );
    panel.append(heading);
    const details = [
      ["机评", scoreAt(comparison.machine_score, state.output)],
      ["标签", comparison.tags?.join("、")],
      ["归因", comparison.reason],
      ["Review", comparison.review_label],
      ["Review 归因", comparison.review_reason],
    ].filter(([, value]) => String(value || "").trim());
    details.forEach(([label, value]) => {
      const row = el("div", "comparison-row");
      row.append(el("span", "", label), el("p", "", value));
      panel.append(row);
    });
    const mos = task.comparison_mos?.find((item) => item.label === comparison.label);
    if (mos) {
      const row = el("div", "comparison-row");
      row.append(
        el("span", "", "MOS"),
        el("p", "", scoreAt(mos.scores, state.output) || "未填"),
      );
      panel.append(row);
    }
    grid.append(panel);
  });
  wrapper.append(grid);
  return wrapper;
}

function renderOverallArbitration(task) {
  const result = resultFor(task);
  if (!result.arbitration) return null;
  const wrapper = section("整体仲裁");
  const select = document.createElement("select");
  select.append(new Option("未选择", ""));
  (state.manifest.options.overall_arbitration_labels || []).forEach(
    (option) => select.append(new Option(option, option)),
  );
  select.value = result.arbitration.label || "";
  select.addEventListener("change", () => {
    result.arbitration.label = select.value;
    queuePersist();
  });
  const reason = document.createElement("textarea");
  reason.value = result.arbitration.reason || "";
  reason.placeholder = "记录三轮最终仲裁原因";
  reason.addEventListener("input", () => {
    result.arbitration.reason = reason.value;
    queuePersist();
  });
  wrapper.append(select);
  if (state.manifest.schema.arbitration_columns?.reason) wrapper.append(reason);
  return wrapper;
}

function renderOverallFields(task) {
  const wrapper = el("div", "overall-fields");
  const values = resultFor(task).overall || {};
  const options = state.manifest.options.overall || {};
  const labels = {reason: "MOS 打分归因", tags: "MOS 打分标签", review_label: "MOS Review 标签", review_reason: "MOS Review 归因"};
  Object.entries(values).forEach(([field, value]) => {
    const group = section(labels[field] || field);
    if (field === "tags") {
      (options.tags || []).forEach((option) => {
        const button = el("button", `tag${value.includes(option) ? " active" : ""}`, option);
        button.addEventListener("click", () => {
          values.tags = value.includes(option) ? value.filter((item) => item !== option) : [...value, option];
          queuePersist();
          renderForm();
        });
        group.append(button);
      });
    } else {
      const input = document.createElement(field === "review_label" ? "select" : "textarea");
      if (field === "review_label") {
        input.append(new Option("未选择", ""));
        (options.review_labels || []).forEach((option) => input.append(new Option(option, option)));
      }
      input.value = value || "";
      input.addEventListener("input", () => { values[field] = input.value; queuePersist(); });
      group.append(input);
    }
    wrapper.append(group);
  });
  Object.entries(task.expert_values || {}).forEach(([label, value]) => {
    wrapper.append(el("div", "machine", `${label} · 只读：${value || "未填"}`));
  });
  return wrapper;
}

function renderForm() {
  const form = $("form");
  const scrollTop = form.scrollTop;
  form.replaceChildren();
  const task = currentTask();
  if (!task) return;
  const blind = state.manifest.schema.blind && !state.revealed.has(task.row);
  if (blind) {
    const panel = section("独立评分阶段 · 机评与历史对照暂未展示");
    const reveal = el("button", "primary", "保存独立评分，进入 Review");
    reveal.addEventListener("click", async () => {
      if (!isDone(task)) { showToast("请先完成所有结果的独立评分"); return; }
      const result = resultFor(task);
      result.blind_snapshot = JSON.parse(JSON.stringify({
        dimensions: result.dimensions, mos: result.mos, saved_at: new Date().toISOString(),
      }));
      queuePersist();
      reveal.disabled = true;
      if (await persist()) { state.revealed.add(task.row); renderForm(); }
      else { delete result.blind_snapshot; reveal.disabled = false; }
    });
    panel.append(reveal);
    form.append(panel);
  }
  const dimension = currentDimension();
  if (!dimension) {
    if (!blind) (task.comparison_mos || []).forEach((item) => form.append(el("div", "machine", `${item.label} · 只读 MOS：${scoreAt(item.scores, state.output) || "未填"}`)));
    form.append(el("div", "machine", "在下方填写当前结果的 MOS 分数"));
    form.append(renderOverallFields(task));
    const arbitration = renderOverallArbitration(task);
    if (arbitration) form.append(arbitration);
    form.scrollTop = scrollTop;
    return;
  }
  const source = task.dimensions[dimension.key];
  const value = resultFor(task).dimensions[dimension.key];
  const options = state.manifest.options[dimension.key];

  const comparisons = renderComparisons(task, source);
  if (comparisons && !blind) form.append(comparisons);

  const machineScore = Array.isArray(source.machine_score)
    ? source.machine_score[state.output]
    : source.machine_score;
  if (dimension.columns.machine_score && !blind) form.append(el("div", "machine", `机评分数：${machineScore || "未提供"}`));
  if (!blind) (source.warnings || []).forEach((warning) => form.append(el("div", "machine", warning)));

  const score = section("人评打分");
  const scoreGrid = el("div", "score-grid");
  const activeScore = value.human_score[state.output] || "";
  options.scores.forEach((option) => {
    const button = el("button", String(activeScore) === String(option) ? "active" : "", option);
    button.addEventListener("click", () => {
      updateDimension("human_score", option);
      renderForm();
    });
    scoreGrid.append(button);
  });
  score.append(scoreGrid);
  form.append(score);

  const tagSectionKey = `${task.row}:${dimension.key}`;
  const tagsExpanded = state.expandedTagSections.has(tagSectionKey);
  const tags = el("section", "section tag-section");
  const tagLabel = el("div", "label");
  tagLabel.append(el("span", "", "打分标签"));
  tags.append(tagLabel);
  const tagToggle = el("button", "section-toggle");
  const tagGridId = `tag-grid-${task.row}-${dimension.key}`;
  const toggleText = value.tags.length ? `已选择 ${value.tags.length} 个标签` : "请选择标签";
  tagToggle.append(
    el("span", "selection-count", toggleText),
    el("span", "toggle-chevron", tagsExpanded ? "▴" : "▾"),
  );
  tagToggle.type = "button";
  tagToggle.title = tagsExpanded ? "收起打分标签" : "展开打分标签";
  tagToggle.setAttribute("aria-label", tagToggle.title);
  tagToggle.setAttribute("aria-controls", tagGridId);
  tagToggle.setAttribute("aria-expanded", String(tagsExpanded));
  tagToggle.addEventListener("click", () => {
    if (tagsExpanded) state.expandedTagSections.delete(tagSectionKey);
    else state.expandedTagSections.add(tagSectionKey);
    renderForm();
  });
  tags.append(tagToggle);
  const tagGrid = el("div", "tag-grid");
  tagGrid.id = tagGridId;
  tagGrid.hidden = !tagsExpanded;
  options.tags.forEach((option) => {
    const button = el("button", `tag${value.tags.includes(option) ? " active" : ""}`, option);
    button.addEventListener("click", () => {
      const next = value.tags.includes(option)
        ? value.tags.filter((item) => item !== option)
        : [...value.tags, option];
      updateDimension("tags", next);
      renderForm();
    });
    tagGrid.append(button);
  });
  tags.append(tagGrid);
  if (dimension.columns.tags) form.append(tags);

  if (Object.hasOwn(value, "arbitration_label")) {
    const arbitration = section("维度仲裁标签");
    const arbitrationSelect = document.createElement("select");
    arbitrationSelect.append(new Option("未选择", ""));
    (options.arbitration_labels || []).forEach(
      (option) => arbitrationSelect.append(new Option(option, option)),
    );
    arbitrationSelect.value = value.arbitration_label || "";
    arbitrationSelect.addEventListener(
      "change",
      () => updateDimension("arbitration_label", arbitrationSelect.value),
    );
    arbitration.append(arbitrationSelect);
    form.append(arbitration);
  }

  const reason = section("打分归因");
  const reasonInput = document.createElement("textarea");
  reasonInput.value = value.reason || "";
  reasonInput.placeholder = "记录关键问题和出现位置";
  reasonInput.addEventListener("input", () => updateDimension("reason", reasonInput.value));
  reason.append(reasonInput);
  if (dimension.columns.reason) form.append(reason);

  const review = section("人机 review 打签");
  const select = document.createElement("select");
  select.append(new Option("未选择", ""));
  options.review_labels.forEach((option) => select.append(new Option(option, option)));
  select.value = value.review_label || "";
  select.addEventListener("change", () => updateDimension("review_label", select.value));
  review.append(select);
  if (dimension.columns.review_label && !blind) form.append(review);

  const reviewReason = section("Review 归因");
  const reviewInput = document.createElement("textarea");
  reviewInput.value = value.review_reason || "";
  reviewInput.placeholder = "记录人机差异原因";
  reviewInput.addEventListener("input", () => updateDimension("review_reason", reviewInput.value));
  reviewReason.append(reviewInput);
  if (dimension.columns.review_reason && !blind) form.append(reviewReason);

  form.append(renderOverallFields(task));
  const overallArbitration = renderOverallArbitration(task);
  if (overallArbitration) form.append(overallArbitration);
  form.scrollTop = scrollTop;
}

function renderMos(task) {
  $("mos").value = resultFor(task).mos[state.output] || "";
  $("mosLabel").textContent = task.outputs.length > 1 ? `MOS · 结果 ${state.output + 1}` : "MOS";
}

function render() {
  const task = currentTask();
  renderProgress();
  renderQueue();
  renderTabs();
  if (!task) {
    $("title").textContent = "当前筛选下没有任务";
    const outputTabs = $("outputTabs");
    outputTabs.replaceChildren();
    outputTabs.dataset.row = "";
    ["media", "form"].forEach((id) => $(id).replaceChildren());
    $("prompt").textContent = "";
    $("mos").value = "";
    $("saveNext").disabled = true;
    return;
  }
  state.selectedRow = task.row;
  $("saveNext").disabled = false;
  $("kind").textContent = task.kind === "video" ? "视频评测" : "图片评测";
  $("title").textContent = `任务 #${task.id} · 表格第 ${task.row} 行`;
  $("prompt").textContent = task.prompt;
  renderMos(task);
  renderOutputTabs(task);
  renderMedia(task);
  renderForm();
}

document.querySelectorAll("[data-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    if (state.navigating) return;
    document.querySelectorAll("[data-filter]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.filter = button.dataset.filter;
    selectTask(visibleTasks()[0]);
  });
});

$("previous").addEventListener("click", () => {
  if (state.navigating) return;
  const tasks = visibleTasks();
  const index = tasks.findIndex((task) => task.row === currentTask()?.row);
  selectTask(tasks[Math.max(0, index - 1)]);
});

$("next").addEventListener("click", () => {
  if (state.navigating) return;
  const tasks = visibleTasks();
  const index = tasks.findIndex((task) => task.row === currentTask()?.row);
  selectTask(tasks[Math.min(tasks.length - 1, index + 1)]);
});

$("saveNext").addEventListener("click", async () => {
  if (state.navigating) return;
  const task = currentTask();
  if (!task) return;
  const tasks = visibleTasks();
  const index = tasks.findIndex((item) => item.row === task.row);
  const next = tasks[index + 1];
  state.navigating = true;
  $("saveNext").disabled = true;
  const saved = await persist(task);
  state.navigating = false;
  $("saveNext").disabled = false;
  if (!saved) {
    showToast("尚未保存成功，请重试");
    return;
  }
  selectTask(next || (state.filter === "pending" ? visibleTasks()[0] : task));
  showToast("已保存到本地，并标记为绿色");
});

$("mos").addEventListener("input", () => {
  const task = currentTask();
  if (!task) return;
  resultFor(task).mos[state.output] = $("mos").value;
  queuePersist();
});

try {
  $("reviewerName").value = localStorage.getItem(REVIEWER_STORAGE_KEY) || "";
} catch (_error) {
  $("reviewerName").value = "";
}
$("reviewerName").addEventListener("input", () => {
  try {
    localStorage.setItem(REVIEWER_STORAGE_KEY, $("reviewerName").value);
  } catch (_error) {
    // Reviewer identity is optional browser-local metadata.
  }
});

document.addEventListener("keydown", (event) => {
  if (event.target.matches("textarea, input, select, button")) return;
  if (event.key === "ArrowLeft") $("previous").click();
  if (event.key === "ArrowRight") $("next").click();
});

window.addEventListener("beforeunload", (event) => {
  if (state.dirty.size || state.navigating) {
    event.preventDefault();
    event.returnValue = "";
  }
});

async function init() {
  try {
    const response = await fetch("/api/session");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "会话读取失败");
    state.manifest = payload.manifest;
    state.tasks = payload.tasks.rows;
    state.results = payload.results;
    state.tasks.forEach((task) => {
      if (resultFor(task)?.blind_snapshot) state.revealed.add(task.row);
    });
    normalizeResults();
    $("sheetName").textContent = state.manifest.schema.target_group || "本地评分 · 保存后可同步飞书";
    $("sourceLink").href = state.manifest.source.url;
    $("sourceLink").title = state.manifest.source.url;
    $("sourceUrl").textContent = state.manifest.source.url;
    render();
  } catch (error) {
    setSaveState(error.message, "error");
    $("title").textContent = "会话载入失败";
  }
}

initLayout();
init();
