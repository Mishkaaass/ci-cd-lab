"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  let viewerToken = null;
  let busy = false;
  let refreshInterval = null;
  let toastTimeout = null;
  const pages = new Set(["guided", "learning", "overview", "docker", "kubernetes", "security", "showcase", "runbook"]);
  let showcaseActive = false;
  let terminalSignature = "";
  let latestTerminal = [];
  let demoPoll = null;
  // The guided tour interprets existing evidence; it never creates GitHub
  // changes or authorizes an additional server-side operation.
  let guidedSelection = 0;
  let guidedOverview = {};
  let guidedShowcase = {};
  let guidedMilestones = {docker: false, gitops: false};
  const REQUIRED_CI_GATES = Object.freeze([
    "Python tests", "Code quality", "Dependency security", "Secret security",
    "Container security", "API and browser security", "Isolated API attack scan"
  ]);
  const GUIDE_SOURCE = "https://github.com/Mishkaaass/ci-cd-lab";
  const GUIDE_STAGES = Object.freeze([
    {
      title: "A change enters review.",
      intro: "Start with a real pull request. Inspect what changed, the checks it required, and how it was merged into protected main.",
      why: "Code review and CI are separate controls. A merged example demonstrates the process; opening it here does not run CI again.",
      note: "Historical example (PR #53). This step is read-only and is not marked as a new execution.",
      source: `${GUIDE_SOURCE}/pull/53`,
      sourceLabel: "Inspect example PR ↗"
    },
    {
      title: "Seven gates protect main.",
      intro: "GitHub Actions tests Python code, formatting, dependencies, secrets, containers, the API/browser boundary, and a controlled attack scan.",
      why: "A release should not advance merely because a build works. All seven independent required quality and security checks must pass.",
      note: "LIVE READ-ONLY EVIDENCE. Results are read from GitHub, not launched by this button. Unavailable data never means success.",
      source: `${GUIDE_SOURCE}/actions/workflows/ci.yml`,
      sourceLabel: "Open CI workflow ↗"
    },
    {
      title: "CI hands off to CD.",
      intro: "After merge, the dedicated CD workflow builds, scans and publishes an image. Its commit identity must match the checked main revision.",
      why: "A successful CI run is not a successful delivery. CD must complete independently on the correct source commit.",
      note: "LIVE READ-ONLY EVIDENCE. A successful historical CD run is not proof that the latest main was published.",
      source: `${GUIDE_SOURCE}/actions/workflows/cd.yml`,
      sourceLabel: "Open CD workflow ↗"
    },
    {
      title: "An image needs provenance.",
      intro: "Inspect the CD build, vulnerability scan, SBOM and image-publishing steps. Production identity is an immutable digest, not a moving tag.",
      why: "A green workflow reports its job result, but this console does not independently read and verify the GHCR artifact digest.",
      note: "EVIDENCE BOUNDARY. To verify the exact published image, inspect GHCR and the workflow artifacts. GitOps promotion is separately reviewed.",
      source: `${GUIDE_SOURCE}/actions/workflows/cd.yml`,
      sourceLabel: "Inspect publishing logs ↗"
    },
    {
      title: "Reject. Promote. Recover.",
      intro: "Now run the real Docker drill. Watch an unhealthy candidate get blocked, a valid Green release receive traffic, and exact Blue rollback.",
      why: "Readiness and release identity must be verified before Nginx switches traffic. Rollback must restore the original version and SHA.",
      note: "LOCAL LAB ACTION. This recreates the inactive candidate and briefly changes local Nginx traffic, then rolls back. It does not change GitHub.",
      action: "docker",
      sourceLabel: "Run Docker demonstration ↗"
    },
    {
      title: "Git repairs configuration drift.",
      intro: "In the dedicated kind cluster, temporarily change replicas from 1 to 2 and watch Argo CD restore Git's desired count of 1.",
      why: "GitOps is continuous reconciliation, not another Docker traffic switch. A separate cluster and reviewed manifest govern its desired state.",
      note: "LOCAL LAB ACTION. This uses the existing fixed drift-test and never edits the GitOps repository or selects a user-supplied cluster.",
      action: "gitops",
      sourceLabel: "Run GitOps demonstration ↗"
    }
  ]);
  function guideEvidence() {
    const ci = guidedOverview.ci || {};
    const cd = guidedOverview.cd || {};
    const status = guidedShowcase || {};
    const checks = new Map((Array.isArray(ci.jobs) ? ci.jobs : [])
      .filter((x) => x && typeof x.name === "string")
      .map((x) => [x.name, String(x.result || "").toLowerCase()]));
    const ciVerified = Boolean(ci.available && ci.jobs_available &&
      String(ci.conclusion || "").toLowerCase() === "success" &&
      REQUIRED_CI_GATES.every((name) => checks.get(name) === "success"));
    const cdVerified = Boolean(ciVerified && cd.available && cd.matches_ci &&
      cd.ci_sha && cd.ci_sha === ci.sha &&
      String(cd.conclusion || "").toLowerCase() === "success");
    const dockerVerified = guidedMilestones.docker;
    const gitopsVerified = guidedMilestones.gitops;
    return {ci, cd, status, checks, ciVerified, cdVerified,
      dockerVerified, gitopsVerified};
  }
  function guideStatusFor(index, ev) {
    if (index === 0) return ["EXAMPLE", ""];
    if (index === 3) return ["INSPECT", ""];
    if (index === 1) return ev.ciVerified ? ["VERIFIED", "verified"] :
      [String(ev.ci.conclusion || "").toLowerCase() === "failure" ? "FAILED" : "CHECK",
        String(ev.ci.conclusion || "").toLowerCase() === "failure" ? "problem" : ""];
    if (index === 2) return ev.cdVerified ? ["VERIFIED", "verified"] :
      [ev.cd.available && ev.cd.ci_observed && !ev.cd.matches_ci ? "DIFFERENT SHA" :
        String(ev.cd.conclusion || "").toLowerCase() === "failure" ? "FAILED" : "CHECK",
        String(ev.cd.conclusion || "").toLowerCase() === "failure" && ev.cd.matches_ci ? "problem" : ""];
    const passed = index === 4 ? ev.dockerVerified : ev.gitopsVerified;
    const running = ["running", "preparing", "queued", "waiting_auth"].includes(ev.status.status);
    return passed ? ["VERIFIED", "verified"] : running ? ["IN PROGRESS", "running"] :
      [ev.status.status === "failed" ? "CHECK LOG" : "NOT RUN", ev.status.status === "failed" ? "problem" : ""];
  }
  function safeGuideRunUrl(value) {
    return typeof value === "string" &&
      /^https:\/\/github\.com\/Mishkaaass\/ci-cd-lab\/actions\/runs\/[0-9]+$/.test(value)
      ? value : null;
  }
  function renderGuided() {
    const ev = guideEvidence();
    const verified = [ev.ciVerified, ev.cdVerified, ev.dockerVerified, ev.gitopsVerified]
      .filter(Boolean).length;
    setText("guide-verified-count", `${verified} / 4`);
    GUIDE_STAGES.forEach((_stage, i) => {
      const button = document.querySelector(`button[data-guide-step="${i}"]`);
      if (!button) return;
      button.classList.toggle("selected", i === guidedSelection);
      if (i === guidedSelection) button.setAttribute("aria-current", "step");
      else button.removeAttribute("aria-current");
      const label = $(`guide-step-state-${i}`);
      if (!label) return;
      const [message, css] = guideStatusFor(i, ev);
      label.textContent = message;
      label.className = "guide-step-status" + (css ? ` ${css}` : "");
    });
    const i = guidedSelection;
    const stage = GUIDE_STAGES[i];
    const [stageState, stageCss] = guideStatusFor(i, ev);
    setText("guide-current-step", `STAGE ${String(i + 1).padStart(2, "0")} / 06`);
    setText("guide-focus-status", stageState);
    $("guide-focus-status").className = "guide-focus-status" + (stageCss ? ` ${stageCss}` : "");
    setText("guide-focus-title", stage.title);
    setText("guide-focus-intro", stage.intro);
    setText("guide-focus-why", stage.why);
    setText("guide-safety-note", stage.note);
    const proofLight = $("guide-proof-light");
    proofLight.className = "guide-proof-light" + (stageCss === "verified" ? " verified" : stageCss === "problem" ? " problem" : "");
    const ciRun = safeGuideRunUrl(ev.ci.url);
    const cdRun = safeGuideRunUrl(ev.cd.url);
    let title = "Review the linked evidence";
    let description = "No action is required on GitHub.";
    if (i === 0) {
      title = "Real pull request #53 (historical example)";
      description = "Inspect what changed, its required checks, and the merge. This step does not claim a new PR was created.";
    } else if (i === 1) {
      title = ev.ciVerified ? `7 / 7 CI gates succeeded · ${ev.ci.sha || "unknown SHA"}` :
        ev.ci.available ? `CI: ${String(ev.ci.conclusion || "pending").toUpperCase()} · ${ev.ci.sha || "unknown SHA"}` : "GitHub CI is not observable";
      description = ev.ciVerified ? "Seven exact job names returned success on the observed main-branch run." :
        "CI was not fully verified. Check the live job results and GitHub link before drawing conclusions.";
    } else if (i === 2) {
      title = ev.cdVerified ? `CD succeeded on main · ${ev.cd.sha || "unknown SHA"}` :
        ev.cd.available ? `CD: ${String(ev.cd.conclusion || ev.cd.status || "pending").toUpperCase()} · ${ev.cd.sha || "unknown SHA"}` : "GitHub CD is not observable";
      description = ev.cdVerified ? "Latest observed CI and CD commit identities match, and both workflows report success." :
        ev.cd.available && ev.cd.ci_observed && !ev.cd.matches_ci ? "CD belongs to a different commit. Do not treat it as proof for the latest CI revision." :
          "A successful, matching CD execution has not been verified for the observed CI commit.";
    } else if (i === 3) {
      title = "Artifact digest: not independently verified";
      description = ev.cdVerified ? "CD reports success for the CI commit. Open its publishing job and GHCR to inspect the image digest, SBOM and provenance." :
        "First verify the matching CD run. Then inspect the published image and immutable digest separately.";
    } else if (i === 4) {
      title = ev.dockerVerified ? "Verified: broken gate → Green → exact Blue rollback" :
        "Awaiting a completed Docker drill";
      description = ev.dockerVerified ? "A verified Docker completion marker was observed in this browser session. See Live Demo for the latest run." :
        "Start the Docker drill, then inspect readiness rejection, successful promotion and restored version/SHA in Live Demo.";
    } else if (i === 5) {
      title = ev.gitopsVerified ? "Verified: Argo CD restored replicas to 1" :
        "Awaiting a completed GitOps drift test";
      description = ev.gitopsVerified ? "A verified GitOps reconciliation marker was observed in this browser session. Inspect live cluster health separately." :
        "Run the dedicated drift test and watch Argo CD return 2 replicas to Git's desired 1.";
    }
    setText("guide-proof-title", title);
    setText("guide-proof-detail", description);
    const source = $("guide-source-link");
    const run = $("guide-run-selected");
    $("guide-practice-link").hidden = i !== 1;
    source.hidden = Boolean(stage.action);
    if (!stage.action) {
      source.href = i === 1 ? (ciRun || stage.source) :
        (i === 2 || i === 3) ? (cdRun || stage.source) : stage.source;
      source.textContent = i === 1 && ciRun ? "View actual CI run ↗" :
        (i === 2 || i === 3) && cdRun ? "View actual CD run ↗" : stage.sourceLabel;
    }
    run.hidden = !stage.action;
    if (stage.action) {
      run.textContent = stage.sourceLabel;
      run.disabled = !Boolean(ev.status.enabled) || showcaseActive;
      run.title = ev.status.enabled ? "Run an approved local lab action" :
        "Start bash scripts/showcase.sh in a local terminal first";
    }
    const jobList = $("guide-job-grid");
    jobList.hidden = i !== 1 || !Array.isArray(ev.ci.jobs) || !ev.ci.jobs.length;
    jobList.replaceChildren();
    if (!jobList.hidden) {
      REQUIRED_CI_GATES.forEach((name) => {
        const chip = document.createElement("span");
        const result = ev.checks.get(name) || "not observed";
        chip.className = "guide-job-item" + (result === "success" ? " pass" : "");
        chip.textContent = `${result === "success" ? "✓" : "•"} ${name}`;
        jobList.append(chip);
      });
    }
    setText("guide-next-stage", i === 5 ? "Restart tour ↺" : "Next stage →");
  }
  function selectGuideStep(index) {
    if (!Number.isInteger(index) || index < 0 || index >= GUIDE_STAGES.length) return;
    guidedSelection = index;
    renderGuided();
  }


  function setText(id, value, empty = "—") {
    const el = $(id);
    if (el) el.textContent = value === null || value === undefined || value === "" ? empty : String(value);
  }
  function tone(el, state) {
    if (!el) return;
    el.classList.remove("good", "bad", "warn");
    if (state) el.classList.add(state);
  }
  function signal(labelId, dotId, value, caption, state) {
    setText(labelId, value);
    if (dotId) tone($(dotId), state);
    if (caption) setText(caption[0], caption[1]);
  }
  function sanitizeState(v) {
    const text = String(v || "").toLowerCase();
    return ["success", "successful", "synced", "healthy", "bound", "ready", "passed", "ok", "completed"].includes(text)
      ? "good" : ["failed", "failure", "unhealthy", "error", "outofsync", "degraded"].includes(text)
        ? "bad" : "warn";
  }
  function short(value, max = 24) {
    if (value === null || value === undefined || value === "") return "—";
    const s = String(value);
    return s.length > max ? `${s.slice(0, max - 1)}…` : s;
  }
  function setView(view) {
    if (!pages.has(view)) return;
    for (const key of pages) {
      const section = $(`page-${key}`);
      if (section) section.hidden = key !== view;
    }
    document.querySelectorAll("[data-view]").forEach((button) => {
      if (!button.classList.contains("nav-link")) return;
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    setText("crumb-label", view === "kubernetes" ? "KUBERNETES GITOPS" : view === "docker" ? "DOCKER DELIVERY" : view === "security" ? "PIPELINE & SECURITY" : view === "showcase" ? "LIVE DEMO" : view === "learning" ? "ENGINEERING LEARNING LAB" : view.toUpperCase());
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function toast(message) {
    const el = $("toast");
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => el.classList.remove("show"), 2300);
  }
  async function copyCommand(value) {
    if (!navigator.clipboard) {
      toast("Clipboard access unavailable. Select the command manually.");
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
      toast("Command copied");
    } catch {
      toast("Copy blocked by browser permissions");
    }
  }
  function renderEvents(items, available) {
    const target = $("docker-events");
    target.replaceChildren();
    setText("docker-history", available ? (items.length ? `${items.length} recent events` : "No recorded events") : "Dashboard offline");
    setText("history-note", available ? "Read-only release audit" : "Docker OpsBoard API unavailable");
    if (!Array.isArray(items) || items.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = available ? "No deployments recorded yet." : "Release history unavailable. Start the existing Docker OpsBoard dashboard to expose its read-only API.";
      target.append(empty);
      return;
    }
    items.slice(0, 6).forEach((item) => {
      const row = document.createElement("div");
      row.className = "event-row";
      const fields = [[item.type || "Release event", "strong"], [item.status || "—", "span"], [item.version || "—", "span"], [item.when || "—", "span"]];
      fields.forEach(([value, kind]) => {
        const el = document.createElement(kind);
        el.textContent = String(value);
        row.append(el);
      });
      target.append(row);
    });
  }
  function renderJobs(jobs) {
    const target = $("ci-jobs");
    target.replaceChildren();
    const list = Array.isArray(jobs) ? jobs : [];
    setText("ci-count", list.length || "—");
    if (!list.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Job details are not available from GitHub right now. A missing API response is not a passed check.";
      target.append(empty);
      return;
    }
    list.forEach((job) => {
      const row = document.createElement("div");
      row.className = "ci-job";
      const name = document.createElement("strong");
      name.textContent = job.name || "Unnamed job";
      const result = document.createElement("span");
      result.className = "job-result";
      result.textContent = String(job.result || "Unknown").toUpperCase();
      tone(result, sanitizeState(job.result));
      row.append(name, result);
      target.append(row);
    });
  }
  function render(data) {
    const docker = data.docker || {};
    const kube = data.kubernetes || {};
    const ci = data.ci || {};
    const dockerState = !docker.available ? "warn" : docker.healthy ? "good" : "bad";
    const kubeHealthy = kube.available && kube.sync === "Synced" && kube.health === "Healthy";
    const kubeState = !kube.available ? "warn" : kubeHealthy ? "good" : "bad";
    const ciState = ci.available ? sanitizeState(ci.conclusion) : "warn";
    const pvcState = sanitizeState(kube.pvc);
    signal("metric-docker", "dot-docker", docker.version ? short(docker.version, 23) : "Not observed", ["metric-docker-detail", !docker.available ? "Port 8080 unavailable" : docker.healthy ? "Live endpoint ready" : "Readiness not verified"], dockerState);
    signal("metric-ci", "dot-ci", ci.available ? String(ci.conclusion || "Running").toUpperCase() : "Not observed", ["metric-ci-detail", ci.sha ? `Commit ${ci.sha}` : "Latest run not available"], ciState);
    signal("metric-argo", "dot-argo", kube.available ? (kube.sync || "Unknown") : "Not observed", ["metric-argo-detail", kube.health || "Cluster unavailable"], kubeState);
    signal("metric-pvc", "dot-pvc", kube.pvc || "Not observed", ["metric-pvc-detail", kube.pvc === "Bound" ? "Persistent claim bound" : "Persistence not verified"], pvcState);
    setText("docker-state", !docker.available ? "OFFLINE" : docker.healthy ? "HEALTHY" : "DEGRADED");
    tone($("docker-state"), dockerState);
    setText("docker-slot", docker.slot ? docker.slot.toUpperCase() : "Not confirmed");
    setText("docker-version", docker.version || "—");
    renderEvents(docker.events || [], Boolean(docker.events_available));
    setText("kube-state", !kube.available ? "OFFLINE" : kubeHealthy ? "HEALTHY" : "DRIFT / WARNING");
    tone($("kube-state"), kubeState);
    setText("kube-sync", kube.available ? `${kube.sync || "Unknown"} / ${kube.health || "Unknown"}` : "Not connected");
    setText("kube-replicas", kube.available && kube.ready !== null && kube.desired !== null ? `${kube.ready} / ${kube.desired}` : "—");
    setText("kube-revision", kube.revision || "—");
    setText("docker-detail-release", docker.version || "No release detected");
    setText("docker-detail-sha", docker.git_sha ? `Git SHA  ${docker.git_sha}` : "Release identity not observed");
    for (const slot of ["blue", "green"]) {
      const info = (docker.slots || {})[slot] || {};
      setText(`slot-${slot}`, info.version || "—");
      setText(`slot-${slot}-state`, info.up ? docker.slot === slot ? "Active / serving traffic" : "Candidate / standby" : "Not available");
    }
    setText("argo-health", kube.health || "Not observed");
    setText("argo-sync-state", (kube.sync || "NOT CONNECTED").toUpperCase());
    tone($("argo-sync-state"), sanitizeState(kube.sync));
    setText("argo-revision", kube.revision || "—");
    setText("argo-ready", kube.available ? `${kube.ready ?? 0} / ${kube.desired ?? "?"}` : "—");
    setText("argo-pvc", kube.pvc || "Not observed");
    setText("argo-image", kube.image || "Runtime image not observed");
    setText("ci-result", ci.available ? String(ci.conclusion || "Running").toUpperCase() : "Not connected");
    setText("ci-revision", ci.sha ? `Main · ${ci.sha}` : "GH CLI could not retrieve latest main run");
    const ciLink = $("ci-link");
    if (typeof ci.url === "string" && /^https:\/\/github\.com\/Mishkaaass\/ci-cd-lab\/actions\/runs\/\d+$/.test(ci.url)) ciLink.href = ci.url;
    renderJobs(ci.jobs || []);
    if (data.observed_at) {
      const date = new Date(data.observed_at);
      if (!Number.isNaN(date.getTime())) {
        setText("last-sync", `CHECKED ${date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`);
        setText("overview-date", date.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" }).toUpperCase());
      }
    }
    setText("footer-status", docker.healthy && kubeHealthy ? "TWO LABS OBSERVED" : "PARTIAL OPERATIONAL VISIBILITY");
    if (window.OpsboardLearning) window.OpsboardLearning.update(data);
  }
  function renderTerminal(rows, active) {
    const list = Array.isArray(rows) ? rows.slice(-125) : [];
    const panel = $("showcase-terminal-output");
    const target = $("showcase-terminal-lines");
    const signature = JSON.stringify(list);
    $("terminal-live-dot").classList.toggle("active", active);
    $("terminal-line-count").textContent = `${list.length} lines`;
    $("terminal-copy").disabled = !list.length;
    latestTerminal = list;
    if (signature === terminalSignature) return;
    const follow = panel.scrollTop + panel.clientHeight >= panel.scrollHeight - 48;
    terminalSignature = signature;
    target.replaceChildren();
    if (!list.length) {
      const empty = document.createElement("div");
      empty.className = "terminal-empty";
      empty.textContent = "Waiting for a guarded lab run. Output appears here live.";
      target.append(empty);
      return;
    }
    list.forEach((entry) => {
      if (!entry || typeof entry.text !== "string") return;
      const line = document.createElement("div");
      line.className = "terminal-line " + (["notice", "command", "error"].includes(entry.kind) ? entry.kind : "output");
      const ts = document.createElement("time");
      const date = new Date(entry.at);
      ts.textContent = Number.isNaN(date.getTime()) ? "--:--:--" : date.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false});
      const label = document.createElement("span");
      label.className = "terminal-track";
      label.textContent = ["docker", "gitops"].includes(entry.track) ? entry.track.toUpperCase() : "SYS";
      const text = document.createElement("span");
      text.className = "terminal-text";
      text.textContent = entry.text;
      line.append(ts, label, text);
      target.append(line);
    });
    if (follow) panel.scrollTop = panel.scrollHeight;
  }

  function renderShowcase(status) {
    const enabled = Boolean(status.enabled);
    const state = String(status.status || "offline");
    showcaseActive = ["queued", "running", "preparing", "waiting_auth"].includes(state);
    const light = $("showcase-light");
    light.className = "showcase-light" + (showcaseActive ? " busy" : state === "failed" ? " bad" : enabled ? " live" : "");
    const labels = { idle: "Ready to demonstrate", queued: "Queued", preparing: "Preparing local services", waiting_auth: "Waiting for terminal authorization", running: "Live test running", passed: "Verified run complete", failed: "Attention required", offline: "Viewer-only session" };
    setText("showcase-state", labels[state] || state.toUpperCase());
    setText("showcase-summary", status.summary || (enabled ? "Click to begin" : "Start scripts/showcase.sh in a terminal to enable guided drills."));
    const notice = status.attention && status.attention.kind === "sudo" ? status.attention : null;
    $("showcase-attention").hidden = !notice;
    if (notice) {
      setText("showcase-attention-title", notice.title || "Authorize Docker in the terminal");
      setText("showcase-attention-message", notice.message || "Return to the terminal running scripts/showcase.sh.");
    }
    renderTerminal(status.terminal, showcaseActive);
    const phases = {
      broken: "Broken candidate test", blocked: "Broken release blocked", healthy: "Validating new release",
      verified: "Version and SHA verified", green: "GREEN: live traffic", blue: "Rollback: BLUE restored", complete: "Rollback verified",
      drift: "Changing replicas", scaled: "Drift introduced", restored: "Reconciled to Git"
    };
    guidedShowcase = status;
    if (["passed", "running"].includes(status.status)) {
      if (status.docker_phase === "complete") guidedMilestones.docker = true;
      if (status.gitops_phase === "restored") guidedMilestones.gitops = true;
    }
    renderGuided();
    setText("showcase-docker", phases[status.docker_phase] || "Not run");
    setText("showcase-gitops", phases[status.gitops_phase] || "Not run");
    const when = status.started_at ? new Date(status.started_at) : null;
    setText("showcase-when", when && !Number.isNaN(when.getTime()) ? when.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}) : "—");
    document.querySelectorAll("button[data-start]").forEach((el) => {
      el.disabled = !enabled || showcaseActive;
    });
    const entries = Array.isArray(status.steps) ? status.steps : [];
    setText("showcase-event-count", entries.length ? `${entries.length} verified events` : "No events yet");
    const parent = $("showcase-events");
    parent.replaceChildren();
    if (!entries.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = enabled ? "Run a real drill to record release transitions here." : "The session is view-only. Run scripts/showcase.sh to enable the local demonstration.";
      parent.append(empty);
      return;
    }
    entries.slice().reverse().forEach((entry) => {
      const item = document.createElement("div");
      item.className = "showcase-event " + (["success", "error", "info"].includes(entry.kind) ? entry.kind : "info");
      const at = document.createElement("time");
      at.className = "event-time";
      const d = new Date(entry.at);
      at.textContent = Number.isNaN(d.getTime()) ? "—" : d.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false});
      const track = document.createElement("span");
      track.className = "event-track " + (["docker", "gitops"].includes(entry.track) ? entry.track : "");
      track.textContent = (entry.track || "system").toUpperCase();
      const text = document.createElement("div");
      const heading = document.createElement("div");
      heading.className = "event-title";
      heading.textContent = entry.title || "Event";
      text.append(heading);
      if (entry.detail) {
        const detail = document.createElement("div");
        detail.className = "event-detail";
        detail.textContent = entry.detail;
        text.append(detail);
      }
      item.append(at, track, text);
      parent.append(item);
    });
  }
  async function pollShowcase() {
    if (!viewerToken) return;
    try {
      const res = await fetch("/api/showcase/status", {
        headers: {Authorization: `Bearer ${viewerToken}`, Accept: "application/json"},
        credentials: "omit", cache: "no-store", signal: AbortSignal.timeout(4000)
      });
      if (res.ok) renderShowcase(await res.json());
    } catch {
      renderShowcase({enabled:false,status:"offline",steps:[],summary:"Live demo status is temporarily unavailable."});
    }
  }
  async function startDemo(action) {
    if (!viewerToken || showcaseActive || !["all", "docker", "gitops"].includes(action)) return;
    showcaseActive = true;
    document.querySelectorAll("button[data-start]").forEach((button) => button.disabled = true);
    try {
      const response = await fetch("/api/showcase/start", {
        method: "POST", headers: {Authorization: `Bearer ${viewerToken}`, "Content-Type": "application/json"},
        credentials: "omit", cache: "no-store", body: JSON.stringify({action}), signal: AbortSignal.timeout(7000)
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || `Request blocked (${response.status})`);
      }
      toast("Real lab drill queued");
      await pollShowcase();
    } catch (error) {
      toast(`Demo not started: ${error.message}`);
      showcaseActive = false;
      await pollShowcase();
    }
  }
  async function update() {
    if (!viewerToken || busy) return false;
    busy = true;
    $("refresh").disabled = true;
    try {
      const response = await fetch("/api/overview", {
        headers: { Authorization: `Bearer ${viewerToken}`, Accept: "application/json" },
        cache: "no-store", signal: AbortSignal.timeout(28000), credentials: "omit"
      });
      if (response.status === 401) {
        viewerToken = null;
        $("shell").hidden = true;
        $("gate").hidden = false;
        setText("unlock-error", "Token no longer valid. Unlock again.");
        return false;
      }
      if (!response.ok) throw new Error(`Status request returned ${response.status}`);
      const json = await response.json();
      render(json);
      guidedOverview = json;
      renderGuided();
      setText("unlock-error", "");
      return true;
    } catch {
      setText("last-sync", "CONNECTION LOST");
      setText("footer-status", "STATUS UNAVAILABLE · RETRY");
      toast("Status unavailable. Check that the console server is running.");
      return false;
    } finally {
      busy = false;
      $("refresh").disabled = false;
    }
  }
  $("unlock-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const field = $("viewer-token");
    const token = field.value.trim();
    if (token.length < 40) {
      setText("unlock-error", "Enter the viewer token from your local file.");
      return;
    }
    viewerToken = token;
    field.value = "";
    const success = await update();
    if (!success) {
      viewerToken = null;
      setText("unlock-error", "Unable to unlock. Verify the token and local server.");
      return;
    }
    $("gate").hidden = true;
    $("shell").hidden = false;
    setView("guided");
    await pollShowcase();
    if (!refreshInterval) refreshInterval = setInterval(update, 14000);
    if (!demoPoll) demoPoll = setInterval(pollShowcase, 1000);
  });
  $("lock-console").addEventListener("click", () => {
    viewerToken = null;
    if (window.OpsboardLearning) window.OpsboardLearning.reset();
    $("shell").hidden = true;
    $("gate").hidden = false;
    if (refreshInterval) clearInterval(refreshInterval);
    refreshInterval = null;
    if (demoPoll) clearInterval(demoPoll);
    demoPoll = null;
    $("viewer-token").focus();
  });
  $("terminal-copy").addEventListener("click", async () => {
    const copy = latestTerminal.map((x) => `${x.at || ""} [${x.track || "system"}] ${x.text || ""}`).join("\n");
    if (!copy) return;
    try {
      await navigator.clipboard.writeText(copy);
      toast("Sanitized terminal output copied");
    } catch {
      toast("Copy unavailable; select the terminal text instead");
    }
  });
  $("guide-next-stage").addEventListener("click", () => {
    selectGuideStep((guidedSelection + 1) % GUIDE_STAGES.length);
  });
  $("guide-run-selected").addEventListener("click", () => {
    const action = GUIDE_STAGES[guidedSelection].action;
    if (!action || showcaseActive || !guidedShowcase.enabled) return;
    setView("showcase");
    startDemo(action);
  });
  $("refresh").addEventListener("click", update);
  document.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-view],button[data-copy],button[data-start],button[data-guide-step]");
    if (!button) return;
    if (button.dataset.guideStep !== undefined) selectGuideStep(Number(button.dataset.guideStep));
    if (button.dataset.view) setView(button.dataset.view);
    if (button.dataset.copy) copyCommand(button.dataset.copy);
    if (button.dataset.start) startDemo(button.dataset.start);
  });
})();
