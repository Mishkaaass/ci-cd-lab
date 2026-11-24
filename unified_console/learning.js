"use strict";

/* Educational-only interactions. No network requests, command execution, or persistence. */
(() => {
  const SOURCE = "https://github.com/Mishkaaass/ci-cd-lab/blob/main/";
  const LABS = Object.freeze([
    {
      id: "docker", name: "Docker & Nginx", icon: "⬡", topic: "TRAFFIC & RELEASE SAFETY",
      intro: "Two Docker application slots exist, but only one receives traffic through Nginx. Observe identity, predict failure behavior, then inspect the live route.",
      source: "scripts/nginx_route.py", command: "curl -fsS http://127.0.0.1:8080/version", target: "docker",
      challenges: [
        {question: "Green starts but fails /ready. Where should Nginx keep sending requests?",
         options: ["To Green, because it is newer", "To Blue, the currently validated release", "To both slots at random"],
         correct: 1, because: "The guarded deploy validates the inactive candidate before changing the Nginx route. A failed readiness gate leaves Blue serving requests.",
         proof: "Run the guarded Docker drill and compare the proxy /version before and after the broken candidate."},
        {question: "Green passes readiness and version/SHA verification. What actually redirects users?",
         options: ["GitHub Actions changes DNS", "Nginx validates and reloads its local backend route", "PostgreSQL selects the new version"],
         correct: 1, because: "Docker runs the containers; Nginx is the local traffic entry point. The deploy script validates its config and reloads Nginx only after candidate verification.",
         proof: "Compare /version on :8001, :8002 and through the proxy on :8080."},
        {question: "The deployment script prints SUCCESS. Which independent observation best proves Green received traffic?",
         options: ["The container image was built", "GET /version through :8080 reports Green's version and SHA", "Both containers exist in Docker"],
         correct: 1, because: "A success message or a running container is not proof of live routing. Observe the identity returned through Nginx, then verify exact Blue restoration after rollback.",
         proof: "Observe the live proxy response; the automated acceptance test recorded 18 Green samples and exact Blue rollback."}
      ]
    },
    {
      id: "gitops", name: "Kubernetes & Argo CD", icon: "◇", topic: "DESIRED STATE & SELF-HEALING",
      intro: "Kubernetes runs the workload. Argo CD compares the running configuration to the Git revision, and reconciles drift in an isolated kind cluster.",
      source: "scripts/gitops-demo.sh", command: "bash scripts/gitops-demo.sh status", target: "kubernetes",
      challenges: [
        {question: "Git specifies one replica, but someone scales the running Deployment to two. What should Argo CD do with self-heal enabled?",
         options: ["Leave two replicas permanently", "Restore the Deployment to one replica", "Delete the PostgreSQL PVC"],
         correct: 1, because: "Argo CD reconciles the actual state to the declarative Git specification. This lab's drift drill temporarily scales to two, then verifies one again.",
         proof: "Run the fixed GitOps drift-test, then inspect desired/ready replicas and Synced / Healthy."},
        {question: "The OpsBoard Pod is Ready, but the PostgreSQL PVC is Pending. Is storage persistence verified?",
         options: ["Yes: a Ready application always means its PVC is Bound", "No: inspect PVC binding separately", "Yes: kind automatically provides cloud backups"],
         correct: 1, because: "Application readiness and persistent volume binding are different signals. Bound is necessary for this lab's storage check, but it is NOT a backup guarantee.",
         proof: "Inspect PostgreSQL PVC state independently from Deployment readiness."},
        {question: "CD publishes a new GHCR image. Does Argo CD automatically run that new image in this project?",
         options: ["Yes: every successful CD changes Kubernetes", "No: a reviewed GitOps manifest update is required", "Yes: the mutable latest tag is an immutable deployment identity"],
         correct: 1, because: "OpsBoard's Docker and GitOps demonstrations are separate. Kubernetes uses a digest-pinned image in its manifest; publishing an image alone does not promote it.",
         proof: "Compare the pinned Kubernetes image digest with the CD run; do not infer they are identical."}
      ]
    },
    {
      id: "backend", name: "Python & FastAPI", icon: "{ }", topic: "HEALTH, READINESS & API CONTRACTS",
      intro: "Learn how application endpoints, readiness gates and controlled API boundaries fit together. The FastAPI dashboard and the minimal demo service are distinct components.",
      source: "app.py", command: "curl -fsS http://127.0.0.1:18001/ready", target: "runbook",
      challenges: [
        {question: "FastAPI returns HTTP 200 for /health, but PostgreSQL is unreachable. Is the dashboard ready?",
         options: ["Yes: /health always checks the database", "No: /ready can return 503 when SELECT 1 fails", "Yes: container uptime guarantees database access"],
         correct: 1, because: "In app.py, /health reports process health. /ready separately checks authentication readiness and database connectivity, returning 503 if either fails.",
         proof: "Compare app.py /health and /ready handlers; use :18001/ready while the dashboard is running."},
        {question: "FastAPI runs SELECT 1 through its DB session. What does that prove?",
         options: ["Basic database connectivity", "All tables, backups and migrations are correct", "A new container release was deployed"],
         correct: 0, because: "SELECT 1 is a lightweight readiness probe. It is not an end-to-end database, business logic or recovery test.",
         proof: "Inspect the /ready handler in app.py and the separate API deployment-history endpoints."},
        {question: "The Guided Journey's Live Terminal displays output. Can a reviewer submit arbitrary shell commands through it?",
         options: ["Yes: every terminal panel is a shell", "Only if PostgreSQL is running", "No: the browser can request only predefined local showcase actions"],
         correct: 2, because: "The console is read-only by default. An explicitly started local supervisor accepts only fixed Docker and GitOps demo actions; it does not accept arbitrary shell input.",
         proof: "Inspect unified_console/server.py and showcase.py for their action allowlists."}
      ]
    },
    {
      id: "postgres", name: "PostgreSQL & Persistence", icon: "▤", topic: "STATE & STORAGE",
      intro: "Separate database availability, retained deployment records and volume binding. A green infrastructure badge is not proof of backups.",
      source: "compose.yml", command: "curl -fsS http://127.0.0.1:18001/ready", target: "runbook",
      challenges: [
        {question: "The Docker PostgreSQL container is recreated, but its named volume is preserved. What should happen to stored data?",
         options: ["It should remain on the named volume", "All data must disappear when a container is recreated", "Nginx automatically replays a database backup"],
         correct: 0, because: "The Compose service mounts opsboard_postgres_data. Container recreation is distinct from deleting the named volume; this is not a substitute for tested backups.",
         proof: "Inspect compose.yml volumes and the recorded deployment history after a guarded Docker drill."},
        {question: "The Kubernetes PostgreSQL PVC says Bound. Can we claim disaster recovery is proven?",
         options: ["Yes: Bound means an off-site backup exists", "No: binding is not backup or restore verification", "Yes: Argo CD backs up the database every sync"],
         correct: 1, because: "Bound means the PersistentVolumeClaim is bound to storage. It does not test backups, restore, replication or off-site durability.",
         proof: "Inspect the claim in the Kubernetes panel; note the project explicitly does not claim production disaster recovery."},
        {question: "Where does OpsBoard expose recorded deployment history?",
         options: ["Only in an unprotected public SQL console", "Through its authenticated FastAPI /api/deployments endpoint", "By rewriting the Kubernetes image digest"],
         correct: 1, because: "The FastAPI dashboard uses SQLAlchemy with PostgreSQL and has authenticated deployment-history API routes. No arbitrary SQL browser endpoint is provided.",
         proof: "Inspect app.py /api/deployments and opsboard/database.py."}
      ]
    },
    {
      id: "pipeline", name: "CI/CD & Artifacts", icon: "↗", topic: "RELEASE IDENTITY & EVIDENCE",
      intro: "A green status badge is insufficient by itself. Verify seven checks, CI/CD commit identity, and the boundary between published and deployed artifacts.",
      source: ".github/workflows/cd.yml", command: "gh run list -R Mishkaaass/ci-cd-lab --branch main --limit 5", target: "security",
      challenges: [
        {question: "CI succeeds for commit A and CD succeeds for commit B. Is that proof that A was published?",
         options: ["Yes: both runs are green", "No: the complete commit SHAs must match", "Yes: main is a protected branch"],
         correct: 1, because: "The guided pipeline observer compares CI and CD source revisions. Different commits mean the run evidence cannot prove the same release.",
         proof: "Inspect the CI and CD run links and compare their full Git SHAs."},
        {question: "The CD job publishes an image to GHCR. What does that prove about the version in the kind cluster?",
         options: ["It is already running there", "The newest latest tag must be running there", "Nothing without comparing the reviewed pinned image digest"],
         correct: 2, because: "Publishing and deployment are separate operations. An immutable digest in the GitOps manifest identifies the Kubernetes workload; CD success alone is not proof of promotion.",
         proof: "Compare the live Kubernetes image digest with actual GHCR artifact evidence, if available."},
        {question: "A workflow succeeded, but only six of seven required gates are visible. What should the reviewer conclude?",
         options: ["All seven are verified", "The missing gate is unknown until its job result is observed", "Skip the missing check when the image builds"],
         correct: 1, because: "The seven mandatory CI controls are individually verified. Missing or unavailable evidence must not be presented as passing.",
         proof: "Inspect all seven real jobs in the Pipeline & Security view."}
      ]
    },
    {
      id: "security", name: "Security & Failure Design", icon: "◈", topic: "TRUST BOUNDARIES",
      intro: "Understand why protected credentials, strict action boundaries and evidence-based status are just as important as successful builds.",
      source: "unified_console/server.py", command: "bash scripts/reviewer.sh doctor", target: "security",
      challenges: [
        {question: "The lab needs sudo authorization. Where should the reviewer enter their password?",
         options: ["Into the Guided Journey browser form", "In the original trusted launcher terminal", "Into a public GitHub issue"],
         correct: 1, because: "Local Docker permissions are authorized in the original terminal. The browser only receives the private Viewer token and never handles Linux sudo passwords.",
         proof: "Read the launcher sudo instructions and the security model in README.md."},
        {question: "Which permissions should the in-browser learning exercises have?",
         options: ["An unrestricted terminal and Docker socket", "No execution at all; read existing evidence and link to guarded demo actions", "Write access to arbitrary namespaces"],
         correct: 1, because: "These learning quizzes are entirely client-side. They only inspect the already-authorized local snapshot; running real drills still requires the existing fixed-action supervisor.",
         proof: "Inspect the static learning asset and existing server-side action allowlist."},
        {question: "A GitHub or Kubernetes API request fails. What status is truthful?",
         options: ["VERIFIED because the last run once worked", "Unknown / not observed until evidence becomes available", "Healthy because the README says so"],
         correct: 1, because: "No result is not success. The console should mark missing information as unavailable and keep historical demonstration separate from current verification.",
         proof: "Observe an offline component's signal in the console and compare it with the source evidence rules."}
      ]
    }
  ]);

  const byId = (id) => document.getElementById(id);
  const answers = new Map();
  const passed = new Set();
  let selected = 0;
  let challenge = 0;
  let snapshot = null;
  const total = LABS.reduce((sum, lab) => sum + lab.challenges.length, 0);

  function key() { return LABS[selected].id + ":" + challenge; }
  function format(value) {
    return value === null || value === undefined || value === "" ? "Not observed" : String(value);
  }
  function liveEvidence() {
    const data = snapshot || {};
    const lab = LABS[selected];
    const docker = data.docker || {};
    const k = data.kubernetes || {};
    const ci = data.ci || {};
    const cd = data.cd || {};
    if (lab.id === "docker") {
      if (!docker.available) return {status: "NOT OBSERVED", rows: ["Nginx :8080 is not observable in the current session."]};
      return {status: "LIVE SNAPSHOT", rows: [
        "Nginx /ready: " + (docker.healthy ? "Healthy" : "Not verified"),
        "Serving slot: " + format(docker.slot),
        "Live /version: " + format(docker.version),
        "Live Git SHA: " + format(docker.git_sha),
        "Blue: " + format((docker.slots || {}).blue && docker.slots.blue.version),
        "Green: " + format((docker.slots || {}).green && docker.slots.green.version)
      ]};
    }
    if (lab.id === "gitops") {
      if (!k.available) return {status: "NOT OBSERVED", rows: ["Dedicated kind cluster or Argo CD is unavailable. Do not infer reconciliation success."]};
      return {status: "LIVE SNAPSHOT", rows: [
        "Argo CD: " + format(k.sync) + " / " + format(k.health),
        "Replicas ready / desired: " + format(k.ready) + " / " + format(k.desired),
        "Git revision: " + format(k.revision),
        "PostgreSQL PVC: " + format(k.pvc),
        "Image: " + format(k.image)
      ]};
    }
    if (lab.id === "backend") {
      return {status: docker.available ? "PARTIAL OBSERVATION" : "NOT OBSERVED", rows: [
        "Docker demo HTTP readiness: " + (docker.available ? (docker.healthy ? "Healthy" : "Not verified") : "Unavailable"),
        "The separate FastAPI dashboard /ready (port 18001) is not independently probed by this console.",
        "Use the read-only curl command below to inspect its database readiness."
      ]};
    }
    if (lab.id === "postgres") {
      return {status: k.available ? "PARTIAL OBSERVATION" : "NOT OBSERVED", rows: [
        "Kubernetes PostgreSQL PVC: " + (k.available ? format(k.pvc) : "Unavailable"),
        "Database connectivity and backup restoration are NOT established by PVC binding.",
        "Check :18001/ready for FastAPI's separate PostgreSQL connectivity probe."
      ]};
    }
    if (lab.id === "pipeline") {
      return {status: ci.available || cd.available ? "LIVE GITHUB EVIDENCE" : "NOT OBSERVED", rows: [
        "CI result: " + (ci.available ? format(ci.conclusion) : "Unavailable"),
        "CI commit: " + format(ci.sha),
        "CD result: " + (cd.available ? format(cd.conclusion) : "Unavailable"),
        "CD commit: " + format(cd.sha),
        "Exact CI/CD SHA match: " + (cd.matches_ci === true ? "Confirmed by observer" : "Not verified"),
        "GHCR digest/provenance: not independently verified by this console."
      ]};
    }
    const jobs = Array.isArray(ci.jobs) ? ci.jobs : [];
    const good = jobs.filter((job) => job.result === "success").length;
    return {status: ci.available ? "LIVE GITHUB EVIDENCE" : "NOT OBSERVED", rows: [
      "CI result: " + (ci.available ? format(ci.conclusion) : "Unavailable"),
      "Successful reported jobs: " + good + " / " + jobs.length + " observed",
      "No API/shell credentials or arbitrary commands are accepted by this learning page."
    ]};
  }
  function render() {
    const current = LABS[selected];
    byId("learning-count").textContent = passed.size + " / " + total;
    byId("learning-module-title").textContent = current.name;
    byId("learning-module-topic").textContent = current.topic;
    byId("learning-intro").textContent = current.intro;
    byId("learning-stage").textContent = "CHALLENGE " + (challenge + 1) + " / " + current.challenges.length;
    const tabs = byId("learning-module-list");
    tabs.replaceChildren();
    LABS.forEach((lab, i) => {
      const complete = lab.challenges.filter((_, j) => passed.has(lab.id + ":" + j)).length;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "learning-tab" + (i === selected ? " active" : "");
      button.setAttribute("aria-pressed", String(i === selected));
      button.textContent = lab.icon + "  " + lab.name + "   " + complete + "/" + lab.challenges.length;
      button.addEventListener("click", () => { selected = i; challenge = 0; render(); });
      tabs.append(button);
    });
    const item = current.challenges[challenge];
    const id = key();
    const choice = answers.get(id);
    const success = passed.has(id);
    byId("learning-question").textContent = item.question;
    const options = byId("learning-choices");
    options.replaceChildren();
    item.options.forEach((name, i) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "learning-answer";
      if (choice === i) button.classList.add(success ? "correct" : "incorrect");
      if (success && i === item.correct) button.classList.add("correct");
      button.setAttribute("aria-pressed", String(choice === i));
      button.textContent = String.fromCharCode(65 + i) + ".  " + name;
      button.disabled = success;
      button.addEventListener("click", () => {
        answers.set(id, i);
        if (i === item.correct) passed.add(id);
        render();
      });
      options.append(button);
    });
    const feedback = byId("learning-feedback");
    feedback.hidden = choice === undefined;
    feedback.className = "learning-feedback" + (success ? " correct" : " incorrect");
    feedback.textContent = choice === undefined ? "" :
      (success ? "CORRECT — " : "NOT QUITE — ") + item.because;
    byId("learning-proof").textContent = item.proof;
    const evidence = liveEvidence();
    byId("learning-live-state").textContent = evidence.status;
    const evidenceRows = byId("learning-evidence");
    evidenceRows.replaceChildren();
    evidence.rows.forEach((s) => { const li = document.createElement("li"); li.textContent = s; evidenceRows.append(li); });
    const link = byId("learning-source");
    link.href = SOURCE + current.source;
    link.textContent = "Inspect " + current.source + " ↗";
    byId("learning-command").textContent = current.command;
    byId("learning-inspect").dataset.view = current.target;
    byId("learning-inspect").textContent = "Open " + (current.target === "runbook" ? "runbooks" : current.target === "security" ? "pipeline evidence" : current.target === "kubernetes" ? "GitOps details" : "Docker details") + " ↗";
    byId("learning-next").textContent = challenge + 1 === current.challenges.length ? "Next module →" : "Next challenge →";
  }
  function initialize() {
    if (!byId("learning-module-list")) return;
    byId("learning-next").addEventListener("click", () => {
      if (challenge + 1 < LABS[selected].challenges.length) challenge += 1;
      else { selected = (selected + 1) % LABS.length; challenge = 0; }
      render();
    });
    byId("learning-back").addEventListener("click", () => {
      if (challenge > 0) challenge -= 1;
      else { selected = (selected + LABS.length - 1) % LABS.length; challenge = LABS[selected].challenges.length - 1; }
      render();
    });
    byId("learning-copy").addEventListener("click", async () => {
      const button = byId("learning-copy");
      try {
        await navigator.clipboard.writeText(LABS[selected].command);
        button.textContent = "Copied ✓";
      } catch {
        button.textContent = "Copy unavailable; select the command";
      }
      button.blur();
    });
    byId("learning-reset").addEventListener("click", () => {
      answers.clear();
      passed.clear();
      selected = 0;
      challenge = 0;
      render();
    });
    render();
  }
  window.OpsboardLearning = {
    update(data) { snapshot = data && typeof data === "object" ? data : null; if (byId("learning-module-list")) render(); },
    reset() { snapshot = null; answers.clear(); passed.clear(); selected = 0; challenge = 0; if (byId("learning-module-list")) render(); }
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, {once: true});
  else initialize();
})();