const state = {
  jobs: [],
  coverage: [],
  meta: {},
  tab: "all",
  roles: new Set(),
  grade: "all",
  group: "all",
  exp: "all",
  sort: "latest",
  query: "",
  selectedIndex: -1,
  bookmarks: new Set(JSON.parse(localStorage.getItem("hrRadarBookmarks") || "[]")),
  readJobs: new Set(JSON.parse(localStorage.getItem("hrRadarReadJobs") || "[]")),
  interestGroups: new Set(JSON.parse(localStorage.getItem("hrRadarInterestGroups") || '["SK","카카오","딜로이트"]')),
  previousVisitAt: localStorage.getItem("hrRadarLastVisitAt") || "1970-01-01T00:00:00+09:00",
};

const roleLabels = {
  TA: "채용",
  HRM: "인사운영",
  HRD: "교육",
  CB: "평가보상",
  ER: "노무",
  OD: "조직문화",
  BP: "HRBP",
  PAY: "급여",
  HRC: "HR컨설팅",
};

const gradeLabels = {
  member: "실무자",
  mid: "준리더",
  lead: "리더급",
};

const els = {
  syncTime: document.querySelector("#syncTime"),
  newCount: document.querySelector("#newCount"),
  tabAll: document.querySelector("#tabAll"),
  tabNew: document.querySelector("#tabNew"),
  tabSaved: document.querySelector("#tabSaved"),
  tabReview: document.querySelector("#tabReview"),
  resultSummary: document.querySelector("#resultSummary"),
  coverageSummary: document.querySelector("#coverageSummary"),
  jobList: document.querySelector("#jobList"),
  coverageList: document.querySelector("#coverageList"),
  loadingState: document.querySelector("#loadingState"),
  emptyState: document.querySelector("#emptyState"),
  jobsView: document.querySelector("#jobsView"),
  coverageView: document.querySelector("#coverageView"),
  searchInput: document.querySelector("#searchInput"),
  groupSelect: document.querySelector("#groupSelect"),
  expSelect: document.querySelector("#expSelect"),
  sortSelect: document.querySelector("#sortSelect"),
  filtersPanel: document.querySelector("#filtersPanel"),
  openFilters: document.querySelector("#openFilters"),
  closeFilters: document.querySelector("#closeFilters"),
  clearFilters: document.querySelector("#clearFilters"),
  sheetBackdrop: document.querySelector("#sheetBackdrop"),
};

async function init() {
  bindEvents();

  try {
    const [jobs, coverage, meta] = await Promise.all([
      fetchJson("data/jobs.json"),
      fetchJson("data/coverage.json"),
      fetchJson("data/meta.json"),
    ]);

    state.jobs = Array.isArray(jobs) ? jobs : [];
    state.coverage = Array.isArray(coverage.sources) ? coverage.sources : [];
    state.meta = meta || {};
    hydrateGroupFilter();
    localStorage.setItem("hrRadarLastVisitAt", new Date().toISOString());
    render();
  } catch (error) {
    renderError(error);
  }
}

async function fetchJson(path) {
  const response = await fetch(`${path}?v=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${path} ${response.status}`);
  }
  return response.json();
}

function bindEvents() {
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      state.tab = button.dataset.tab;
      state.selectedIndex = -1;
      render();
    });
  });

  document.querySelectorAll("[data-role]").forEach((button) => {
    button.addEventListener("click", () => {
      const role = button.dataset.role;
      if (state.roles.has(role)) {
        state.roles.delete(role);
      } else {
        state.roles.add(role);
      }
      state.selectedIndex = -1;
      render();
    });
  });

  document.querySelectorAll("[data-grade]").forEach((button) => {
    button.addEventListener("click", () => {
      state.grade = button.dataset.grade;
      state.selectedIndex = -1;
      render();
    });
  });

  els.searchInput.addEventListener("input", (event) => {
    state.query = event.target.value.trim().toLowerCase();
    state.selectedIndex = -1;
    render();
  });

  els.groupSelect.addEventListener("change", (event) => {
    state.group = event.target.value;
    state.selectedIndex = -1;
    render();
  });

  els.expSelect.addEventListener("change", (event) => {
    state.exp = event.target.value;
    state.selectedIndex = -1;
    render();
  });

  els.sortSelect.addEventListener("change", (event) => {
    state.sort = event.target.value;
    state.selectedIndex = -1;
    render();
  });

  els.openFilters.addEventListener("click", openFilterSheet);
  els.closeFilters.addEventListener("click", closeFilterSheet);
  els.sheetBackdrop.addEventListener("click", closeFilterSheet);
  els.clearFilters.addEventListener("click", clearFilters);

  document.addEventListener("keydown", handleKeyboard);
}

function hydrateGroupFilter() {
  const groups = [...new Set(state.jobs.map((job) => job.company_group).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ko"));
  els.groupSelect.innerHTML = '<option value="all">전체</option>';
  groups.forEach((group) => {
    const option = document.createElement("option");
    option.value = group;
    option.textContent = group;
    els.groupSelect.appendChild(option);
  });
}

function render() {
  els.loadingState.classList.add("is-hidden");
  renderControls();
  renderStats();

  if (state.tab === "coverage") {
    els.jobsView.classList.add("is-hidden");
    els.coverageView.classList.remove("is-hidden");
    renderCoverage();
    return;
  }

  els.coverageView.classList.add("is-hidden");
  els.jobsView.classList.remove("is-hidden");
  renderJobs();
}

function renderControls() {
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.tab === state.tab);
  });
  document.querySelectorAll("[data-role]").forEach((button) => {
    button.classList.toggle("is-active", state.roles.has(button.dataset.role));
  });
  document.querySelectorAll("[data-grade]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.grade === state.grade);
  });
}

function renderStats() {
  const newJobs = state.jobs.filter(isPersonalNew);
  const savedJobs = state.jobs.filter((job) => state.bookmarks.has(job.id));
  const reviewJobs = state.jobs.filter((job) => job.hr_confidence === "review");
  const filtered = getVisibleJobs();
  const updatedAt = state.meta.updated_at || newestDate(state.jobs.map((job) => job.first_seen));
  const okCount = state.coverage.filter((source) => source.status === "ok").length;
  const warnCount = state.coverage.filter((source) => source.status === "warn").length;
  const failCount = state.coverage.filter((source) => source.status === "fail").length;

  els.tabAll.textContent = state.jobs.length;
  els.tabNew.textContent = newJobs.length;
  els.tabSaved.textContent = savedJobs.length;
  els.tabReview.textContent = reviewJobs.length;
  els.newCount.textContent = `신규 ${newJobs.length}`;
  els.syncTime.textContent = updatedAt ? `최근 갱신 ${formatDateTime(updatedAt)}` : "갱신 정보 없음";
  els.resultSummary.textContent = state.tab === "coverage" ? `소스 ${state.coverage.length}개` : `결과 ${filtered.length}건`;
  els.coverageSummary.textContent = `정상 ${okCount} · 의심 ${warnCount} · 실패 ${failCount}`;
}

function renderJobs() {
  const jobs = getVisibleJobs();
  els.jobList.innerHTML = jobs.map((job, index) => jobTemplate(job, index)).join("");
  els.emptyState.classList.toggle("is-hidden", jobs.length > 0);

  els.jobList.querySelectorAll(".bookmark-button").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      toggleBookmark(button.dataset.id);
    });
  });

  els.jobList.querySelectorAll(".open-button").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openJob(button.dataset.id);
    });
  });

  els.jobList.querySelectorAll(".job-row").forEach((row) => {
    row.addEventListener("click", () => {
      state.selectedIndex = Number(row.dataset.index);
      renderJobs();
    });
    row.addEventListener("dblclick", () => {
      openJob(row.dataset.id);
    });
  });
}

function renderCoverage() {
  if (!state.coverage.length) {
    els.coverageList.innerHTML = '<div class="empty-state"><h2>커버리지 데이터가 없습니다</h2><p>수집 워크플로 실행 후 표시됩니다.</p></div>';
    return;
  }

  els.coverageList.innerHTML = state.coverage.map((source) => {
    const history = Array.isArray(source.count_history) ? source.count_history : [];
    const max = Math.max(1, ...history);
    const bars = history.slice(-10).map((count) => `<i style="height:${Math.max(3, Math.round((count / max) * 22))}px"></i>`).join("");
    const delta = formatDelta(history);
    const statusLabel = { ok: "정상", warn: "의심", fail: "실패", info: "정보" }[source.status] || "정보";
    return `
      <article class="coverage-row">
        <div class="source-name"><span class="status-dot ${escapeHtml(source.status || "info")}"></span><span>${escapeHtml(source.label || source.id)}</span></div>
        <div class="coverage-count">${escapeHtml(String(source.current_count ?? 0))}건 ${delta}</div>
        <div class="spark" aria-label="최근 수집 건수">${bars}</div>
        <div class="coverage-note">${escapeHtml(statusLabel)} · ${escapeHtml(source.note || source.last_ok || "")}</div>
      </article>
    `;
  }).join("");
}

function getVisibleJobs() {
  return state.jobs
    .filter((job) => {
      if (state.tab === "new" && !isPersonalNew(job)) return false;
      if (state.tab === "saved" && !state.bookmarks.has(job.id)) return false;
      if (state.tab === "review" && job.hr_confidence !== "review") return false;
      if (state.roles.size && !(job.role || []).some((role) => state.roles.has(role))) return false;
      if (state.grade !== "all" && job.grade !== state.grade) return false;
      if (state.group !== "all" && job.company_group !== state.group) return false;
      if (!matchesExp(job)) return false;
      if (state.query && !searchText(job).includes(state.query)) return false;
      return true;
    })
    .sort(sortJobs);
}

function jobTemplate(job, index) {
  const roles = (job.role || []).map((role) => `<span class="token role" title="${escapeHtml(roleLabels[role] || role)}">${escapeHtml(role)}</span>`).join("");
  const grade = job.grade ? `<span class="token ${job.grade === "lead" ? "lead" : ""}">${escapeHtml(gradeLabels[job.grade] || job.grade)}</span>` : "";
  const review = job.hr_confidence === "review" ? '<span class="token review">검토 필요</span>' : "";
  const safety = (job.also_on || []).length ? `<span class="source-token">안전망 ${escapeHtml(job.also_on.join(", "))}</span>` : "";
  const isSaved = state.bookmarks.has(job.id);
  const isRead = state.readJobs.has(job.id);
  const isInterest = state.interestGroups.has(job.company_group) || state.interestGroups.has(job.company);
  const deadline = formatDeadline(job.deadline);
  const selected = index === state.selectedIndex;
  const exp = formatExp(job.exp_min, job.exp_max);

  return `
    <article class="job-row ${isRead ? "is-read" : ""} ${isInterest ? "is-interest" : ""} ${selected ? "is-selected" : ""}" role="option" aria-selected="${selected}" data-id="${escapeHtml(job.id)}" data-index="${index}">
      <div class="job-main">
        <div class="job-title-line">
          ${isPersonalNew(job) ? '<span class="new-badge">NEW</span>' : ""}
          <span class="job-title">${escapeHtml(job.title)}</span>
        </div>
        <div class="job-meta-line">
          <span class="company">${escapeHtml(job.company)}</span>
          ${job.company_group ? `<span>${escapeHtml(job.company_group)}</span>` : ""}
          ${roles}
          ${grade}
          ${exp ? `<span class="token">${escapeHtml(exp)}</span>` : ""}
          ${job.location ? `<span class="token">${escapeHtml(job.location)}</span>` : ""}
          ${review}
          ${safety}
        </div>
      </div>
      <div class="job-side">
        <div class="job-actions">
          <button class="job-action bookmark-button" type="button" data-id="${escapeHtml(job.id)}" aria-label="북마크">${isSaved ? "★" : "☆"}</button>
          <button class="job-action open-button" type="button" data-id="${escapeHtml(job.id)}">원문</button>
        </div>
        <span class="deadline ${deadline.hot ? "is-hot" : ""}">${escapeHtml(deadline.text)}</span>
        <span>${escapeHtml(job.source_label || job.source || "")}</span>
      </div>
    </article>
  `;
}

function matchesExp(job) {
  if (state.exp === "all") return true;
  const min = Number.isFinite(job.exp_min) ? job.exp_min : 0;
  const max = Number.isFinite(job.exp_max) ? job.exp_max : min;
  if (state.exp === "junior") return min <= 3;
  if (state.exp === "mid") return max >= 4 && min <= 7;
  if (state.exp === "senior") return max >= 8 || min >= 8;
  return true;
}

function sortJobs(a, b) {
  if (state.sort === "deadline") {
    return dateValue(a.deadline) - dateValue(b.deadline);
  }
  if (state.sort === "company") {
    return `${a.company}${a.title}`.localeCompare(`${b.company}${b.title}`, "ko");
  }
  return dateValue(b.first_seen) - dateValue(a.first_seen);
}

function searchText(job) {
  return [
    job.title,
    job.company,
    job.company_group,
    job.source,
    job.location,
    ...(job.role || []),
    job.description,
  ].filter(Boolean).join(" ").toLowerCase();
}

function isPersonalNew(job) {
  return dateValue(job.first_seen) > dateValue(state.previousVisitAt);
}

function toggleBookmark(id) {
  if (state.bookmarks.has(id)) {
    state.bookmarks.delete(id);
  } else {
    state.bookmarks.add(id);
  }
  localStorage.setItem("hrRadarBookmarks", JSON.stringify([...state.bookmarks]));
  render();
}

function openJob(id) {
  const job = state.jobs.find((item) => item.id === id);
  if (!job) return;
  state.readJobs.add(id);
  localStorage.setItem("hrRadarReadJobs", JSON.stringify([...state.readJobs]));
  window.open(job.url, "_blank", "noopener,noreferrer");
  render();
}

function handleKeyboard(event) {
  const tag = event.target.tagName;
  if (["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(tag)) return;
  if (state.tab === "coverage") return;

  const jobs = getVisibleJobs();
  if (!jobs.length) return;

  if (event.key === "j") {
    event.preventDefault();
    state.selectedIndex = Math.min(jobs.length - 1, state.selectedIndex + 1);
    renderJobs();
    scrollSelectedIntoView();
  }

  if (event.key === "k") {
    event.preventDefault();
    state.selectedIndex = Math.max(0, state.selectedIndex - 1);
    renderJobs();
    scrollSelectedIntoView();
  }

  if (event.key === "Enter" && state.selectedIndex >= 0) {
    event.preventDefault();
    openJob(jobs[state.selectedIndex].id);
  }

  if (event.key === "b" && state.selectedIndex >= 0) {
    event.preventDefault();
    toggleBookmark(jobs[state.selectedIndex].id);
  }
}

function scrollSelectedIntoView() {
  requestAnimationFrame(() => {
    const selected = els.jobList.querySelector(".job-row.is-selected");
    selected?.scrollIntoView({ block: "nearest" });
  });
}

function clearFilters() {
  state.roles.clear();
  state.grade = "all";
  state.group = "all";
  state.exp = "all";
  state.sort = "latest";
  state.query = "";
  state.selectedIndex = -1;
  els.searchInput.value = "";
  els.groupSelect.value = "all";
  els.expSelect.value = "all";
  els.sortSelect.value = "latest";
  render();
}

function openFilterSheet() {
  els.filtersPanel.classList.add("is-open");
  els.sheetBackdrop.hidden = false;
}

function closeFilterSheet() {
  els.filtersPanel.classList.remove("is-open");
  els.sheetBackdrop.hidden = true;
}

function renderError(error) {
  els.loadingState.classList.add("is-hidden");
  els.emptyState.classList.remove("is-hidden");
  els.emptyState.querySelector("h2").textContent = "데이터를 불러오지 못했습니다";
  els.emptyState.querySelector("p").textContent = error.message;
  els.syncTime.textContent = "로딩 실패";
}

function formatDateTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatDeadline(value) {
  if (!value) return { text: "상시", hot: false };
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const deadline = new Date(`${value}T00:00:00+09:00`);
  if (Number.isNaN(deadline.getTime())) return { text: value, hot: false };
  const days = Math.ceil((deadline - today) / 86400000);
  if (days < 0) return { text: "마감", hot: true };
  if (days === 0) return { text: "오늘 마감", hot: true };
  return { text: `D-${days}`, hot: days <= 3 };
}

function formatExp(min, max) {
  if (!Number.isFinite(min) && !Number.isFinite(max)) return "";
  if (Number.isFinite(min) && Number.isFinite(max) && min !== max) return `${min}-${max}년`;
  if (Number.isFinite(min)) return `${min}년+`;
  return `${max}년 이하`;
}

function formatDelta(history) {
  if (!history || history.length < 2) return "";
  const delta = history[history.length - 1] - history[history.length - 2];
  if (delta === 0) return "(0)";
  return delta > 0 ? `(+${delta})` : `(${delta})`;
}

function newestDate(values) {
  const dates = values.map((value) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date.getTime();
  }).filter(Boolean);
  if (!dates.length) return "";
  return new Date(Math.max(...dates)).toISOString();
}

function dateValue(value) {
  if (!value) return 8640000000000000;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 8640000000000000 : date.getTime();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

init();
