"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  let viewerToken = null;
  let busy = false;
  let refreshInterval = null;
  let toastTimeout = null;
  const pages = new Set(["overview", "docker", "kubernetes", "security", "showcase", "runbook"]);
  let showcaseActive = false;
  let demoPoll = null;

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
    setText("crumb-label", view === "kubernetes" ? "KUBERNETES GITOPS" : view === "docker" ? "DOCKER DELIVERY" : view === "security" ? "PIPELINE & SECURITY" : view === "showcase" ? "LIVE DEMO" : view.toUpperCase());
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
  }
  function renderShowcase(status) {
    const enabled = Boolean(status.enabled);
    const state = String(status.status || "offline");
    showcaseActive = state === "queued" || state === "running";
    const light = $("showcase-light");
    light.className = "showcase-light" + (showcaseActive ? " busy" : state === "failed" ? " bad" : enabled ? " live" : "");
    const labels = { idle: "Ready to demonstrate", queued: "Queued", running: "Live test running", passed: "Verified run complete", failed: "Attention required", offline: "Viewer-only session" };
    setText("showcase-state", labels[state] || state.toUpperCase());
    setText("showcase-summary", status.summary || (enabled ? "Click to begin" : "Start scripts/showcase.sh in a terminal to enable guided drills."));
    const phases = {
      broken: "Broken candidate test", blocked: "Broken release blocked", healthy: "Validating new release",
      verified: "Version and SHA verified", green: "GREEN: live traffic", blue: "Rollback: BLUE restored", complete: "Rollback verified",
      drift: "Changing replicas", scaled: "Drift introduced", restored: "Reconciled to Git"
    };
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
    setView("overview");
    await pollShowcase();
    if (!refreshInterval) refreshInterval = setInterval(update, 14000);
    if (!demoPoll) demoPoll = setInterval(pollShowcase, 1000);
  });
  $("lock-console").addEventListener("click", () => {
    viewerToken = null;
    $("shell").hidden = true;
    $("gate").hidden = false;
    if (refreshInterval) clearInterval(refreshInterval);
    refreshInterval = null;
    if (demoPoll) clearInterval(demoPoll);
    demoPoll = null;
    $("viewer-token").focus();
  });
  $("refresh").addEventListener("click", update);
  document.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-view],button[data-copy],button[data-start]");
    if (!button) return;
    if (button.dataset.view) setView(button.dataset.view);
    if (button.dataset.copy) copyCommand(button.dataset.copy);
    if (button.dataset.start) startDemo(button.dataset.start);
  });
})();
