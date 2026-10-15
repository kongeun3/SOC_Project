/* API wiring only. Layout belongs in index.html; appearance belongs in style.css. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const state = { sessionId: null, uploadId: null, file: null, uploaded: false, result: null, busy: false, previewUrl: null, imageUrls: new Set(), health: null, scenarios: {} };
  // Zaemit's preview uses its own /api routes, not the analysis server's routes.
  const previewOnly = location.protocol === "file:" || Boolean(document.getElementById("zaemit-editor-base"));
  const conditionsPanel = document.querySelectorAll(".input-panel")[1];
  const captureDate = $("captureDate");
  const captureDateHint = $("captureDateHint");
  if (conditionsPanel && captureDate && captureDateHint) {
    const scenario = $("scenario");
    const dateLabel = document.querySelector('label[for="captureDate"]');
    if (dateLabel && scenario) {
      conditionsPanel.insertBefore(dateLabel, scenario);
      conditionsPanel.insertBefore(captureDate, scenario);
      conditionsPanel.insertBefore(captureDateHint, scenario);
    }
  }
  const allowedExtensions = new Set(["png", "jpg", "jpeg", "csv", "tif", "tiff", "bmp"]);
  const format = (value, decimals = 2) => typeof value === "number" && Number.isFinite(value)
    ? new Intl.NumberFormat("ko-KR", { maximumFractionDigits: decimals }).format(value) : "—";
  const text = (id, value) => { $(id).textContent = value ?? "—"; };
  const extension = (file) => file.name.split(".").pop().toLowerCase();

  async function request(path, { timeout = 30000, ...options } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const headers = new Headers(options.headers);
      if (state.sessionId) headers.set("X-SOC-Session", state.sessionId);
      const response = await fetch(`/api${path}`, { ...options, headers, signal: controller.signal, cache: "no-store" });
      let data;
      try { data = await response.json(); }
      catch { throw new Error(`서버가 분석 데이터를 반환하지 않았습니다. (HTTP ${response.status})`); }
      if (response.status === 401) {
        state.sessionId = null; state.uploaded = false; state.health = null;
        throw new Error("사용 세션이 만료되었습니다. 새로고침한 뒤 파일을 다시 업로드하세요.");
      }
      if (!response.ok) {
        const error = new Error(data.error || (typeof data.detail === "string" ? data.detail : `요청 실패: HTTP ${response.status}`));
        error.status = response.status;
        throw error;
      }
      if (data.error && data.status !== "failed") throw new Error(data.error);
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("응답 대기 시간이 초과되었습니다. 서버 로그를 확인하고 다시 시도하세요.");
      if (error instanceof TypeError) throw new Error("서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.");
      throw error;
    } finally { clearTimeout(timer); }
  }

  async function runJob(kind, payload, runningMessage, onStatus = () => {}) {
    const submitted = await request(`/jobs/${kind}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    if (!submitted.job_id) throw new Error("작업 번호를 받지 못했습니다. 새로고침 후 다시 시도하세요.");
    let job = submitted, failures = 0;
    while (true) {
      if (job.status === "completed") return job.result;
      if (job.status === "failed") throw new Error(job.error || "작업을 완료하지 못했습니다.");
      const message = job.status === "queued"
        ? `요청이 접수되었습니다. 대기 순서 ${job.queue_position || 1}번째입니다.`
        : runningMessage;
      text("operationStatus", message); onStatus(message);
      await new Promise(resolve => setTimeout(resolve, 1000));
      try {
        job = await request(`/jobs/${encodeURIComponent(submitted.job_id)}`, { timeout: 15000 });
        failures = 0;
      } catch (error) {
        if (!state.sessionId || (error.status && error.status < 500) || ++failures > 3) throw error;
        text("operationStatus", "작업 상태 연결을 다시 확인하고 있습니다…");
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
    }
  }

  function releaseResultImages() {
    for (const url of state.imageUrls) URL.revokeObjectURL(url);
    state.imageUrls.clear();
  }

  function showError(message = "") {
    text("errorMessage", message);
    $("errorMessage").hidden = !message;
  }

  function refreshControls() {
    $("inputSettings").disabled = state.busy || previewOnly || !state.sessionId;
    $("customFields").disabled = !$("customProps").checked;
    $("clearFileButton").disabled = state.busy;
    $("analyzeButton").disabled = state.busy || !state.uploaded || previewOnly || !state.health;
    $("downloadButton").disabled = !state.result;
    $("diagnoseButton").disabled = state.busy || !state.result || previewOnly;
    $("chatInput").disabled = state.busy || !state.result || previewOnly;
    $("chatButton").disabled = state.busy || !state.result || previewOnly;
  }

  function setBusy(busy, message) {
    state.busy = busy;
    $("operationProgress").hidden = !busy;
    $("resultsHeading").setAttribute("aria-busy", String(busy));
    if (message) text("operationStatus", message);
    refreshControls();
  }

  function resetResults() {
    state.result = null;
    releaseResultImages();
    $("gradeBanner").dataset.grade = "idle";
    text("gradeBadge", "분석 대기");
    text("gradeTitle", "곧 진단이 완료됩니다.");
    text("gradeDescription", "왼쪽 배너에서 파일과 분석 조건을 확인할 수 있습니다.");
    for (const id of ["maxStress", "maxRatio", "crackRatio", "criticalCount", "resultScenario", "resultDate", "resultMesh", "resultInput", "resultProps", "temperatureUncertainty", "stressRange", "ratioRange", "verificationV1", "verificationV2"]) text(id, "—");
    text("crackPixels", "총 —pixel"); text("totalElements", "전체 해석 요소 기준");
    text("distributionText", "");
    text("diagnosisContent", "분석이 끝나면 결과를 바탕으로 종합 진단을 생성할 수 있습니다.");
    $("diagnosisContent").classList.add("muted");
    $("chatMessages").replaceChildren();
    const empty = document.createElement("p");
    empty.className = "muted chat-empty"; empty.textContent = "분석을 완료하면 후속 질문을 할 수 있습니다.";
    $("chatMessages").append(empty);
    document.querySelectorAll("[data-result-image]").forEach((image) => {
      image.onload = null; image.onerror = null; image.hidden = true; image.removeAttribute("src");
      const placeholder = image.parentElement.querySelector(".chart-placeholder, .image-empty");
      if (placeholder) placeholder.hidden = false;
    });
    refreshControls();
  }

  function clearSelection() {
    if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
    state.file = null; state.uploadId = null; state.uploaded = false; state.previewUrl = null;
    $("fileInput").value = ""; $("selectedFile").hidden = true;
    $("filePreview").hidden = true; $("filePreview").removeAttribute("src");
    resetResults(); showError();
    $("workspace").classList.remove("has-file");
    text("operationStatus", "분석할 파일을 먼저 선택하세요.");
  }

  async function selectFile(file) {
    if (!file || state.busy || previewOnly) return;
    if (!state.sessionId || !state.health) {
      showError("서버 연결을 확인한 뒤 파일을 업로드하세요."); return;
    }
    if (!allowedExtensions.has(extension(file))) {
      $("fileInput").value = "";
      showError("PNG, JPG, TIFF, BMP 이미지 또는 CSV 파일을 선택하세요.");
      return;
    }
    if (!file.size) { showError("내용이 없는 파일입니다. 다른 파일을 선택하세요."); return; }
    clearSelection();
    state.file = file;
    text("fileName", file.name);
    text("fileMeta", `${format(file.size / 1024 / 1024, 2)} MB · ${extension(file).toUpperCase()}`);
    $("selectedFile").hidden = false;
    if (["png", "jpg", "jpeg", "bmp"].includes(extension(file))) {
      state.previewUrl = URL.createObjectURL(file);
      $("filePreview").src = state.previewUrl; $("filePreview").hidden = false;
      $("filePreview").onerror = () => { $("filePreview").hidden = true; };
    }
    setBusy(true, "파일을 업로드하고 있습니다…");
    try {
      const form = new FormData(); form.append("file", file, file.name);
      const uploaded = await request("/upload", { method: "POST", body: form, timeout: 120000 });
      if (!uploaded.upload_id) throw new Error("업로드 번호를 받지 못했습니다. 다시 업로드하세요.");
      state.uploadId = uploaded.upload_id;
      state.uploaded = true;
      text("operationStatus", "업로드 완료. 분석 조건을 확인하고 시작하세요.");
    } catch (error) {
      showError(error.message);
      text("operationStatus", "업로드하지 못했습니다. 파일을 다시 선택하세요.");
    } finally { setBusy(false); }
  }

  function loadResultImages() {
    releaseResultImages();
    const result = state.result;
    document.querySelectorAll("[data-result-image]").forEach(async (image) => {
      const placeholder = image.parentElement.querySelector(".chart-placeholder, .image-empty");
      image.onload = () => { image.hidden = false; if (placeholder) placeholder.hidden = true; };
      const failed = () => {
        if (state.result !== result) return;
        image.hidden = true;
        if (placeholder) {
          placeholder.hidden = false;
          const label = placeholder.querySelector("p") || placeholder;
          label.textContent = "이 분석의 이미지가 생성되지 않았습니다.";
        }
      };
      image.onerror = failed;
      image.loading = "eager";
      image.hidden = true;
      image.removeAttribute("src");
      const path = result.images?.[image.dataset.resultImage];
      if (!path) { failed(); return; }
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 30000);
      try {
        const response = await fetch(`/api${path}`, {
          headers: { "X-SOC-Session": state.sessionId }, cache: "no-store", signal: controller.signal,
        });
        if (!response.ok) throw new Error("결과 이미지를 불러오지 못했습니다.");
        const blob = await response.blob();
        if (state.result !== result) return;
        const url = URL.createObjectURL(blob);
        state.imageUrls.add(url); image.src = url;
      } catch { failed(); }
      finally { clearTimeout(timer); }
    });
  }

  function renderResult(data) {
    const { fem, sam2, uncertainty } = data.result;
    state.result = data;
    const grades = {
      Safe: ["safe", "안전", "이 균열의 위험 수준은 안전입니다."],
      Warning: ["warning", "경고", "이 균열의 위험 수준은 경고입니다."],
      Critical: ["critical", "위험", "이 균열의 위험 수준은 위험입니다."],
    };
    const grade = grades[data.result.grade] || ["idle", data.result.grade, "분석 결과를 확인하세요."];
    $("gradeBanner").dataset.grade = grade[0];
    text("gradeBadge", `종합 등급 · ${grade[1]}`); text("gradeTitle", grade[2]);
    text("gradeDescription", `최대 주응력: ${format(fem.max_stress_MPa, 4)} MPa · 최대 응력비: ${format(fem.max_ratio, 4)}`);
    text("maxStress", format(fem.max_stress_MPa, 4));
    text("maxRatio", format(fem.max_ratio, 4));
    text("crackRatio", `${format(sam2.crack_ratio * 100)}%`);
    text("crackPixels", `총 ${format(sam2.crack_pixels, 0)}pixel`);
    text("criticalCount", format(fem.critical, 0));
    text("totalElements", `전체 ${format(fem.total, 0)}개 중`);
    text("distributionText", `안전 ${format(fem.safe, 0)} · 경고 ${format(fem.warning, 0)} · 위험 ${format(fem.critical, 0)}`);
    text("resultScenario", data.scenario_info.name);
    text("resultDate", data.capture_date); text("resultMesh", data.mesh_resolution);
    text("resultInput", data.input_mode === "csv_absolute" ? "CSV 절대온도" : "이미지 그레이스케일");
    const props = data.props;
    text("resultProps", `E ${format(props.E)} MPa / ν ${format(props.nu)} / α ${format(props.alpha * 1e5)} ×10⁻⁵ /K / Sₜ ${format(props.S_t)} MPa`);
    text("temperatureUncertainty", `±${format(uncertainty.delta_T_C)} °C`);
    text("stressRange", `${format(uncertainty.stress_range_MPa[0], 4)} ~ ${format(uncertainty.stress_range_MPa[1], 4)} MPa`);
    text("ratioRange", `${format(uncertainty.SR_range[0], 4)} ~ ${format(uncertainty.SR_range[1], 4)}`);
    text("verificationV1", `${format(data.verification.V1_error_pct)}%`);
    text("verificationV2", `${format(data.verification.V2_tsrst_error_pct)}%`);
    text("diagnosisContent", "분석이 완료되었습니다. AI 진단을 생성할 수 있습니다.");
    $("chatMessages").replaceChildren();
    loadResultImages(); refreshControls();
  }

  function renderDiagnosis(message) {
    const container = $("diagnosisContent");
    container.classList.remove("muted"); container.replaceChildren();
    let paragraph = null, list = null;
    // Build DOM nodes instead of injecting model text as HTML.
    for (const line of message.split(/\r?\n/)) {
      if (!line.trim()) { paragraph = null; list = null; continue; }
      const heading = line.match(/^#{1,6}\s+(.+)/);
      const item = line.match(/^(?:[-*]|\d+[.)])\s+(.+)/);
      if (heading) {
        const node = document.createElement("h4"); node.textContent = heading[1]; container.append(node);
        paragraph = null; list = null;
      } else if (item) {
        if (!list) { list = document.createElement("ul"); container.append(list); }
        const node = document.createElement("li"); node.textContent = item[1]; list.append(node); paragraph = null;
      } else {
        if (!paragraph) { paragraph = document.createElement("p"); container.append(paragraph); }
        paragraph.append(document.createTextNode((paragraph.textContent ? " " : "") + line)); list = null;
      }
    }
  }

  async function diagnose() {
    setBusy(true, "AI 진단을 생성하고 있습니다. 수 분이 걸릴 수 있습니다…");
    text("diagnosisContent", "분석 데이터를 바탕으로 AI 보고서를 작성하고 있습니다…");
    try {
      const data = await runJob("diagnose", { analysis_id: state.result.analysis_id }, "AI 진단을 생성하고 있습니다. 수 분이 걸릴 수 있습니다…", message => text("diagnosisContent", message));
      if (typeof data.diagnosis !== "string" || !data.diagnosis.trim()) throw new Error("AI 진단 응답이 비어 있습니다.");
      if (/^[❌⚠]/u.test(data.diagnosis)) throw new Error(data.diagnosis);
      renderDiagnosis(data.diagnosis);
      text("operationStatus", "분석과 AI 진단이 완료되었습니다.");
    } catch (error) {
      text("diagnosisContent", "AI 진단을 생성하지 못했습니다. 위 분석 결과는 확인할 수 있으며, 진단 생성 버튼으로 다시 시도할 수 있습니다.");
      text("operationStatus", "분석 완료 · AI 진단은 다시 시도할 수 있습니다.");
      showError(error.message);
    } finally { setBusy(false); }
  }

  $("analysisForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (state.busy || !state.uploaded || !$("analysisForm").reportValidity()) return;
    if (!state.health.sam2 && extension(state.file) !== "csv") {
      showError("SAM2 모델이 준비되지 않았습니다. 서버 로그를 확인하세요."); return;
    }
    showError();
    setBusy(true, "균열 검출과 FEM 열응력 분석을 진행하고 있습니다…");
    $("workspace").classList.add("has-file");
    const params = { upload_id: state.uploadId, scenario: $("scenario").value, mesh_size: Number($("meshSize").value) };
    if ($("captureDate").value) params.capture_date = $("captureDate").value;
    if ($("customProps").checked) {
      for (const [key, id, scale] of [["e_override", "elasticModulus", 1], ["nu_override", "poissonRatio", 1], ["alpha_override", "thermalExpansion", 1e-5], ["st_override", "tensileStrength", 1]]) {
        params[key] = Number($(id).value) * scale;
      }
    }
    try {
      const result = await runJob("analyze", params, "균열 검출과 FEM 열응력 분석을 진행하고 있습니다…");
      renderResult(result);
      $("resultsHeading").focus({ preventScroll: true });
      text("operationStatus", "분석이 완료되었습니다.");
      if ($("autoDiagnose").checked) await diagnose();
    } catch (error) {
      showError(error.message); text("operationStatus", "분석하지 못했습니다. 조건을 확인하고 다시 시도하세요.");
    } finally { setBusy(false); }
  });
  $("diagnoseButton").addEventListener("click", () => {
    if (!state.busy && state.result) { showError(); void diagnose(); }
  });
  $("fileInput").addEventListener("change", (event) => { void selectFile(event.target.files[0]); });
  $("clearFileButton").addEventListener("click", () => { if (!state.busy) clearSelection(); });
  $("customProps").addEventListener("change", refreshControls);
  $("scenario").addEventListener("change", () => text("scenarioDescription", state.scenarios[$("scenario").value]?.desc || "선택한 조건으로 분석합니다."));
  for (const name of ["dragenter", "dragover"]) $("dropZone").addEventListener(name, (event) => {
    event.preventDefault(); if (!state.busy) $("dropZone").classList.add("is-dragging");
  });
  for (const name of ["dragleave", "drop"]) $("dropZone").addEventListener(name, (event) => {
    event.preventDefault(); $("dropZone").classList.remove("is-dragging");
    if (name === "drop") void selectFile(event.dataTransfer.files[0]);
  });
  $("downloadButton").addEventListener("click", () => {
    if (!state.result) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(state.result, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a"); anchor.href = url;
    anchor.download = `${state.file.name.replace(/\.[^.]+$/, "")}_analysis.json`;
    document.body.append(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  function appendChat(role, message) {
    $("chatMessages").querySelector(".chat-empty")?.remove();
    const node = document.createElement("p"); node.className = "chat-message";
    node.dataset.role = role; node.textContent = message;
    $("chatMessages").append(node); $("chatMessages").scrollTop = $("chatMessages").scrollHeight;
    return node;
  }

  $("chatForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = $("chatInput").value.trim();
    if (!message || state.busy || !state.result) return;
    showError(); appendChat("user", message); $("chatInput").value = "";
    const waiting = appendChat("assistant", "답변을 작성하고 있습니다…");
    setBusy(true, "분석 결과에 대한 답변을 작성하고 있습니다…");
    try {
      const data = await runJob("chat", { analysis_id: state.result.analysis_id, message }, "분석 결과에 대한 답변을 작성하고 있습니다…", status => { waiting.textContent = status; });
      if (typeof data.reply !== "string" || !data.reply.trim()) throw new Error("답변이 비어 있습니다.");
      if (/^[❌⚠]/u.test(data.reply)) throw new Error(data.reply);
      waiting.textContent = data.reply; text("operationStatus", "답변이 도착했습니다.");
    } catch (error) {
      waiting.dataset.role = "error"; waiting.textContent = error.message;
      text("operationStatus", "답변을 생성하지 못했습니다. 다시 질문할 수 있습니다.");
    } finally { setBusy(false); }
  });

  async function initialize() {
    $("previewNotice").hidden = !previewOnly;
    showError();
    refreshControls();
    if (previewOnly) {
      $("previewNotice").hidden = false;
      $("connectionStatus").dataset.state = "checking"; text("connectionText", "디자인 미리보기");
      return;
    }
    try {
      const session = await request("/session", { method: "POST" });
      if (!session.session_id) throw new Error("사용 세션을 만들지 못했습니다. 새로고침 후 다시 시도하세요.");
      state.sessionId = session.session_id;
      state.health = await request("/", { timeout: 15000 });
      $("connectionStatus").dataset.state = state.health.sam2 ? "ready" : "warning";
      text("connectionText", state.health.sam2 ? "분석 서버 연결됨" : "SAM2 준비 필요");
      refreshControls();
      try {
        state.scenarios = await request("/scenarios");
        for (const option of $("scenario").options) if (state.scenarios[option.value]) option.title = state.scenarios[option.value].desc;
        text("scenarioDescription", state.scenarios[$("scenario").value]?.desc);
      } catch { /* Static scenario labels remain usable. */ }
    } catch (error) {
      $("connectionStatus").dataset.state = "error"; text("connectionText", "서버 연결 확인 필요");
      showError(error.message);
    }
  }
  void initialize();
})();
