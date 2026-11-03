(() => {
"use strict";
let accessToken = "";
let authEpoch = 0;
let accessExpiresAt = 0;
let expiryTimer;
let canExecuteOperations = false;
const responseEpochs = new WeakMap();

const ACTIVE_STATUSES = new Set([
    "queued",
    "running",
]);


function byId(id) {
    return document.getElementById(id);
}


function setText(id, value) {
    const element = byId(id);

    if (element) {
        element.textContent = value;
    }
}


function setFeedback(message, type = "neutral") {
    const element = byId("control-feedback");

    if (!element) {
        return;
    }

    element.textContent = message;
    element.dataset.type = type;
}


function deploymentButtons() {
    return [
        byId("deploy-healthy-button"),
        byId("deploy-broken-button"),
        byId("rollback-button"),
    ].filter(Boolean);
}


function setControlsDisabled(disabled) {
    for (const button of deploymentButtons()) {
        button.disabled = disabled || !canExecuteOperations;
    }
}


function normalizeValue(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    return String(value);
}


function updateSlotDisplay(operation) {
    const blueState = byId(
        "blue-slot-state",
    );

    const greenState = byId(
        "green-slot-state",
    );

    if (!blueState || !greenState) {
        return;
    }

    blueState.textContent = "—";
    greenState.textContent = "—";

    if (operation?.slot === "blue") {
        blueState.textContent =
            "Latest target";
    }

    if (operation?.slot === "green") {
        greenState.textContent =
            "Latest target";
    }
}


function createTimelineStep(step) {
    const wrapper =
        document.createElement("div");

    wrapper.className =
        `timeline-step timeline-${step.status}`;

    const marker =
        document.createElement("div");

    marker.className =
        "timeline-marker";

    const content =
        document.createElement("div");

    const title =
        document.createElement("strong");

    title.textContent = step.name;

    const status =
        document.createElement("span");

    status.textContent =
        step.status.charAt(0).toUpperCase()
        + step.status.slice(1);

    content.appendChild(
        title,
    );

    content.appendChild(
        status,
    );

    wrapper.appendChild(
        marker,
    );

    wrapper.appendChild(
        content,
    );

    return wrapper;
}


function renderTimeline(operation) {
    const timeline = byId(
        "operation-timeline",
    );

    if (!timeline) {
        return;
    }

    timeline.replaceChildren();

    if (!operation?.steps?.length) {
        const empty =
            document.createElement("p");

        empty.className = "empty";

        empty.textContent =
            "No deployment operation recorded yet.";

        timeline.appendChild(
            empty,
        );

        return;
    }

    for (const step of operation.steps) {
        timeline.appendChild(
            createTimelineStep(
                step,
            ),
        );
    }
}


function renderOperation(operation) {
    if (!operation) {
        return;
    }

    setText(
        "operation-id",
        `#${operation.id}`,
    );

    setText(
        "operation-action",
        operation.action,
    );

    setText(
        "operation-version",
        normalizeValue(
            operation.version,
        ),
    );

    setText(
        "operation-git-sha",
        normalizeValue(
            operation.git_sha,
        ),
    );

    setText(
        "operation-status",
        operation.status.toUpperCase(),
    );

    updateSlotDisplay(
        operation,
    );

    renderTimeline(
        operation,
    );

    const isActive = ACTIVE_STATUSES.has(
        operation.status,
    );

    setControlsDisabled(
        isActive,
    );

    if (operation.status === "queued") {
        setFeedback(
            `Operation #${operation.id} queued.`,
            "running",
        );
    }

    if (operation.status === "running") {
        setFeedback(
            `Operation #${operation.id} is running.`,
            "running",
        );
    }

    if (operation.status === "success") {
        setFeedback(
            `Operation #${operation.id} completed successfully.`,
            "success",
        );
    }

    if (operation.status === "failed") {
        setFeedback(
            `Operation #${operation.id} failed. Production protection remains in effect.`,
            "failed",
        );
    }
}


function renderOperationHistory(
    operations,
) {
    const container = byId(
        "operation-history",
    );

    if (!container) {
        return;
    }

    container.replaceChildren();

    if (!operations.length) {
        const empty =
            document.createElement("p");

        empty.className = "empty";

        empty.textContent =
            "No operations recorded.";

        container.appendChild(
            empty,
        );

        return;
    }

    for (
        const operation
        of operations.slice(0, 10)
    ) {
        const row =
            document.createElement("div");

        row.className =
            "operation-history-row";

        const left =
            document.createElement("div");

        const title =
            document.createElement("strong");

        title.textContent =
            `#${operation.id} ${operation.action}`;

        const release =
            document.createElement("p");

        release.textContent =
            operation.version || "rollback";

        left.appendChild(
            title,
        );

        left.appendChild(
            release,
        );

        const status =
            document.createElement("span");

        status.textContent =
            operation.status.toUpperCase();

        row.appendChild(
            left,
        );

        row.appendChild(
            status,
        );

        container.appendChild(
            row,
        );
    }
}


async function parseError(response) {
    try {
        const payload =
            await response.json();

        if (payload.detail) {
            if (
                typeof payload.detail
                === "string"
            ) {
                return payload.detail;
            }

            return JSON.stringify(
                payload.detail,
            );
        }
    } catch {
        return `HTTP ${response.status}`;
    }

    return `HTTP ${response.status}`;
}


function deploymentPayload() {
    const version =
        byId(
            "deployment-version",
        )?.value.trim();

    const gitSha =
        byId(
            "deployment-git-sha",
        )?.value.trim();

    if (!version || !gitSha) {
        throw new Error(
            "Version and Git SHA are required.",
        );
    }

    return {
        version,
        git_sha: gitSha,
    };
}


async function submitOperation(action) {
    if (!accessToken || !canExecuteOperations) {
        setFeedback("An authorized operator and enabled deployment backend are required.", "failed");
        return;
    }
    let endpoint;

    const options = {
        method: "POST",
        headers: {
            "Content-Type":
                "application/json",
        },
    };

    if (action === "rollback") {
        endpoint =
            "/api/operations/rollback";
    } else {
        let payload;

        try {
            payload =
                deploymentPayload();
        } catch (error) {
            setFeedback(
                error.message,
                "failed",
            );

            return;
        }

        endpoint = (
            action === "deploy_healthy"
                ? "/api/operations/deploy-healthy"
                : "/api/operations/deploy-broken"
        );

        options.body =
            JSON.stringify(
                payload,
            );
    }

    setControlsDisabled(
        true,
    );

    setFeedback(
        "Submitting approved operation...",
        "running",
    );

    try {
        const response = await authorizedFetch(
            endpoint,
            options,
        );

        if (!response.ok) {
            throw new Error(
                await parseError(
                    response,
                ),
            );
        }

        const operation =
            await authorizedJSON(response);

        renderOperation(
            operation,
        );

        await refreshOperations();

    } catch (error) {
        setControlsDisabled(
            false,
        );

        setFeedback(
            error.message,
            "failed",
        );
    }
}


async function refreshOperations() {
    if (!accessToken) return;
    try {
        const response = await authorizedFetch(
            "/api/operations?limit=10",
        );

        if (!response.ok) {
            return;
        }

        const operations =
            await authorizedJSON(response);

        renderOperationHistory(
            operations,
        );

        if (operations.length > 0) {
            renderOperation(
                operations[0],
            );
        } else {
            setControlsDisabled(
                false,
            );
        }

    } catch {
        setFeedback(
            "Unable to refresh deployment operations.",
            "failed",
        );
    }
}


function updateServiceStatus(service) {
    setText(
        "service-name",
        service.name,
    );

    setText(
        "service-latency",
        service.latency_ms === null
            ? "—"
            : `${service.latency_ms} ms`,
    );

    setText(
        "service-readiness",
        service.ready
            ? "Ready"
            : "Not Ready",
    );

    setText(
        "service-version",
        normalizeValue(
            service.version,
        ),
    );

    setText(
        "service-git-sha",
        normalizeValue(
            service.git_sha,
        ),
    );

    setText(
        "production-version",
        normalizeValue(
            service.version,
        ),
    );

    setText(
        "production-git-sha",
        normalizeValue(
            service.git_sha,
        ),
    );

    setText(
        "production-readiness",
        service.ready
            ? "Ready"
            : "Not Ready",
    );

    const status = byId(
        "service-status",
    );

    if (status) {
        status.textContent =
            service.status.charAt(0)
            .toUpperCase()
            + service.status.slice(1);

        status.className =
            `status status-${service.status}`;
    }
}


async function refreshDashboard() {
    if (!accessToken) return;
    try {
        const response = await authorizedFetch("/api/dashboard");

        if (!response.ok) {
            return;
        }

        const data = await authorizedJSON(response);
        updateServiceStatus(data.service);
        renderRecords(data.deployments, data.incidents, data.active_incident_count);
        renderOperationHistory(data.operations);
        if (data.operations.length) renderOperation(data.operations[0]);

    } catch {
        return;
    }
}


function connectActions() {
    byId(
        "deploy-healthy-button",
    )?.addEventListener(
        "click",
        () => submitOperation(
            "deploy_healthy",
        ),
    );

    byId(
        "deploy-broken-button",
    )?.addEventListener(
        "click",
        () => submitOperation(
            "deploy_broken",
        ),
    );

    byId(
        "rollback-button",
    )?.addEventListener(
        "click",
        () => submitOperation(
            "rollback",
        ),
    );
}


function startPolling() {
    window.setInterval(
        refreshOperations,
        1500,
    );

    window.setInterval(
        refreshDashboard,
        5000,
    );
}


document.addEventListener(
    "DOMContentLoaded",
    () => {
        connectActions();
        connectAuthentication();
        setControlsDisabled(true);
        refreshOperations();
        refreshDashboard();

        startPolling();
    },
);


async function authorizedFetch(url, options = {}) {
    checkExpiry();
    if (!accessToken) throw new Error("Unlock the dashboard first.");
    const epoch = authEpoch;
    const token = accessToken;
    const response = await fetch(url, {
        ...options,
        credentials: "omit",
        cache: "no-store",
        headers: {...options.headers, Authorization: `Bearer ${token}`},
    });
    if (epoch !== authEpoch || token !== accessToken) {
        throw new Error("Access changed while the request was pending.");
    }
    if (response.status === 401) {
        lockDashboard("Access expired or was revoked. Unlock again.");
        throw new Error("Authentication required.");
    }
    responseEpochs.set(response, epoch);
    return response;
}

async function authorizedJSON(response) {
    const payload = await response.json();
    if (responseEpochs.get(response) !== authEpoch || !accessToken) {
        throw new Error("Access changed while the response was pending.");
    }
    return payload;
}

function emptyMessage(container, message) {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = message;
    container.appendChild(p);
}

function renderRecords(deployments, incidents, activeCount) {
    const rows = byId("deployment-rows");
    const incidentRows = byId("incident-rows");
    if (!rows || !incidentRows) return;
    rows.replaceChildren();
    incidentRows.replaceChildren();
    for (const deployment of deployments) {
        const row = document.createElement("div");
        row.className = "table-row";
        for (const value of [deployment.version, deployment.git_sha, deployment.status,
            deployment.duration_ms === null ? "—" : `${deployment.duration_ms} ms`]) {
            const cell = document.createElement("span");
            cell.textContent = String(value);
            row.appendChild(cell);
        }
        rows.appendChild(row);
    }
    if (!deployments.length) emptyMessage(rows, "No deployment history.");
    for (const incident of incidents) {
        const row = document.createElement("div");
        row.className = "incident";
        const detail = document.createElement("div");
        for (const [tag, value] of [["span", incident.severity], ["strong", incident.reason], ["p", incident.service]]) {
            const element = document.createElement(tag);
            element.textContent = String(value);
            detail.appendChild(element);
        }
        const status = document.createElement("span");
        status.className = "incident-state";
        status.textContent = incident.status;
        row.append(detail, status);
        incidentRows.appendChild(row);
    }
    if (!incidents.length) emptyMessage(incidentRows, "No incidents recorded.");
    setText("active-incident-count", activeCount);
    const summary = byId("active-incident-summary");
    if (summary) {
        summary.replaceChildren();
        const active = incidents.find(item => item.status === "active");
        const text = document.createElement("p");
        text.textContent = active ? `${active.severity}: ${active.reason}` :
            (activeCount ? "Active incidents exist outside the recent list." : "No active incidents");
        summary.appendChild(text);
    }
}

function checkExpiry() {
    if (accessToken && Date.now() >= accessExpiresAt) {
        lockDashboard("Access expired. Unlock again.");
    }
}

function scheduleExpiry() {
    window.clearTimeout(expiryTimer);
    if (!accessToken) return;
    const remaining = accessExpiresAt - Date.now();
    if (remaining <= 0) {
        checkExpiry();
        return;
    }
    expiryTimer = window.setTimeout(() => {
        checkExpiry();
        scheduleExpiry();
    }, Math.min(remaining, 2147483647));
}

function lockDashboard(message = "Locked — operational data requires authentication.") {
    authEpoch += 1;
    accessToken = "";
    accessExpiresAt = 0;
    window.clearTimeout(expiryTimer);
    canExecuteOperations = false;
    byId("access-token").value = "";
    for (const id of ["deployment-version", "deployment-git-sha"]) {
        if (byId(id)) byId(id).value = "";
    }
    setControlsDisabled(true);
    setText("auth-status", message);
    setFeedback("Unlock with an operator token to use deployment controls.");
    updateServiceStatus({name: "demo-api", status: "unknown", ready: false,
        latency_ms: null, version: "—", git_sha: "—"});
    for (const id of ["operation-id", "operation-action", "operation-version", "operation-git-sha",
        "blue-slot-state", "green-slot-state"]) setText(id, "—");
    setText("operation-status", "LOCKED");
    renderTimeline(null);
    renderOperationHistory([]);
    renderRecords([], [], 0);
}

function connectAuthentication() {
    window.addEventListener("focus", checkExpiry);
    document.addEventListener("visibilitychange", checkExpiry);
    byId("lock-button")?.addEventListener("click", () => lockDashboard());
    byId("auth-form")?.addEventListener("submit", async event => {
        event.preventDefault();
        const token = byId("access-token").value.trim();
        lockDashboard("Checking access...");
        const epoch = authEpoch;
        try {
            const response = await fetch("/api/auth/me", {
                credentials: "omit", cache: "no-store",
                headers: {Authorization: `Bearer ${token}`},
            });
            if (epoch !== authEpoch) return;
            if (!response.ok) throw new Error(await parseError(response));
            const actor = await response.json();
            if (epoch !== authEpoch) return;
            accessExpiresAt = Number(actor.expires_at) * 1000;
            if (!Number.isFinite(accessExpiresAt) || accessExpiresAt <= Date.now()) {
                throw new Error("Access expired. Unlock again.");
            }
            accessToken = token;
            scheduleExpiry();
            canExecuteOperations = actor.deployment_actions_enabled;
            setText("auth-status", `${actor.name} — ${actor.role}`);
            setFeedback(canExecuteOperations ? "Operator access enabled." :
                "Read access enabled; deployment controls are unavailable for this role or runtime.");
            setControlsDisabled(false);
            await refreshDashboard();
            await refreshOperations();
        } catch (error) {
            if (epoch === authEpoch) lockDashboard(error.message);
        }
    });
}
})();
