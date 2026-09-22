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
        button.disabled = disabled;
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
        const response = await fetch(
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
            await response.json();

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
    try {
        const response = await fetch(
            "/api/operations",
        );

        if (!response.ok) {
            return;
        }

        const operations =
            await response.json();

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


async function refreshService() {
    try {
        const response = await fetch(
            "/api/services/demo",
        );

        if (!response.ok) {
            return;
        }

        const service =
            await response.json();

        updateServiceStatus(
            service,
        );

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
        refreshService,
        5000,
    );
}


document.addEventListener(
    "DOMContentLoaded",
    () => {
        connectActions();

        refreshOperations();
        refreshService();

        startPolling();
    },
);
