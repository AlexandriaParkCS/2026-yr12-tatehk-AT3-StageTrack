document.querySelectorAll("form").forEach((form) => {
    const destructiveButtons = form.querySelectorAll(".button-link");
    if (!destructiveButtons.length) {
        return;
    }

    let submitter = null;

    destructiveButtons.forEach((button) => {
        button.addEventListener("click", () => {
            submitter = button;
        });
    });

    form.addEventListener("submit", (event) => {
        const actionButton = submitter || form.querySelector(".button-link");
        const message = actionButton?.getAttribute("data-confirm-message") || "Are you sure you want to delete this item?";
        const confirmed = window.confirm(message);
        if (!confirmed) {
            event.preventDefault();
        }
        submitter = null;
    });
});

document.querySelectorAll("[data-auto-submit-filter]").forEach((form) => {
    let submitTimer = null;
    const searchInput = form.querySelector('input[type="search"]');

    form.querySelectorAll("select").forEach((select) => {
        select.addEventListener("change", () => {
            form.submit();
        });
    });

    if (searchInput) {
        searchInput.addEventListener("input", () => {
            window.clearTimeout(submitTimer);
            submitTimer = window.setTimeout(() => {
                form.submit();
            }, 350);
        });

        searchInput.addEventListener("search", () => {
            window.clearTimeout(submitTimer);
            form.submit();
        });
    }
});

const modalTriggers = document.querySelectorAll("[data-open-modal]");
const modalClosers = document.querySelectorAll("[data-close-modal]");

modalTriggers.forEach((trigger) => {
    trigger.addEventListener("click", () => {
        const modalId = trigger.getAttribute("data-open-modal");
        const modal = document.getElementById(modalId);
        if (!modal) {
            return;
        }
        modal.hidden = false;
        document.body.classList.add("modal-open");
    });
});

modalClosers.forEach((closer) => {
    closer.addEventListener("click", () => {
        const modal = closer.closest(".modal-backdrop");
        if (!modal) {
            return;
        }
        modal.hidden = true;
        document.body.classList.remove("modal-open");
    });
});

document.querySelectorAll(".modal-backdrop").forEach((modal) => {
    modal.addEventListener("click", (event) => {
        if (event.target === modal) {
            modal.hidden = true;
            document.body.classList.remove("modal-open");
        }
    });
});

document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") {
        return;
    }

    document.querySelectorAll(".modal-backdrop").forEach((modal) => {
        if (!modal.hidden) {
            modal.hidden = true;
        }
    });
    document.body.classList.remove("modal-open");
});

const crewForm = document.querySelector("[data-crew-form]");

if (crewForm) {
    const crewList = crewForm.querySelector("[data-crew-list]");
    const crewTemplate = crewForm.querySelector("[data-crew-row-template]");
    const crewCountInput = crewForm.querySelector("[data-crew-count]");
    const addCrewButton = crewForm.querySelector("[data-add-crew-row]");

    const syncCrewRows = () => {
        const rows = Array.from(crewList.querySelectorAll("[data-crew-row]"));
        rows.forEach((row, index) => {
            const emailInput = row.querySelector("[data-crew-email]");
            const roleInput = row.querySelector("[data-crew-role]");
            const removeButton = row.querySelector("[data-remove-crew-row]");

            if (emailInput) {
                emailInput.name = `crew_email_${index}`;
            }
            if (roleInput) {
                roleInput.name = `crew_role_${index}`;
            }
            if (removeButton) {
                removeButton.hidden = rows.length === 1;
            }
        });
        crewCountInput.value = rows.length;
    };

    const addCrewRow = () => {
        const fragment = crewTemplate.content.cloneNode(true);
        crewList.appendChild(fragment);
        syncCrewRows();
        const rows = crewList.querySelectorAll("[data-crew-row]");
        const newestRow = rows[rows.length - 1];
        newestRow?.querySelector("[data-crew-email]")?.focus();
    };

    addCrewButton?.addEventListener("click", () => {
        addCrewRow();
    });

    crewList?.addEventListener("click", (event) => {
        const removeButton = event.target.closest("[data-remove-crew-row]");
        if (!removeButton) {
            return;
        }

        const row = removeButton.closest("[data-crew-row]");
        if (!row) {
            return;
        }

        row.remove();
        syncCrewRows();
    });

    crewList?.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") {
            return;
        }

        const target = event.target;
        if (!(target instanceof HTMLInputElement) || target.tagName !== "INPUT") {
            return;
        }

        if (!target.closest("[data-crew-row]")) {
            return;
        }

        event.preventDefault();
        addCrewRow();
    });

    syncCrewRows();
}

const taskBulkForm = document.querySelector("[data-task-bulk-form]");

if (taskBulkForm) {
    const taskList = taskBulkForm.querySelector("[data-task-list]");
    const taskTemplate = taskBulkForm.querySelector("[data-task-row-template]");
    const taskCountInput = taskBulkForm.querySelector("[data-task-count]");
    const addTaskButton = taskBulkForm.querySelector("[data-add-task-row]");

    const syncTaskRows = () => {
        const rows = Array.from(taskList.querySelectorAll("[data-task-row]"));
        rows.forEach((row, index) => {
            const titleInput = row.querySelector("[data-task-title]");
            const assigneeInput = row.querySelector("[data-task-assignee]");
            const dueInput = row.querySelector("[data-task-due]");
            const statusInput = row.querySelector("[data-task-status]");
            const descriptionInput = row.querySelector("[data-task-description]");
            const removeButton = row.querySelector("[data-remove-task-row]");

            if (titleInput) {
                titleInput.name = `title_${index}`;
            }
            if (assigneeInput) {
                assigneeInput.name = `assigned_to_${index}`;
            }
            if (dueInput) {
                dueInput.name = `due_time_${index}`;
            }
            if (statusInput) {
                statusInput.name = `status_${index}`;
            }
            if (descriptionInput) {
                descriptionInput.name = `description_${index}`;
            }
            if (removeButton) {
                removeButton.hidden = rows.length === 1;
            }
        });
        taskCountInput.value = rows.length;
    };

    const addTaskRow = () => {
        const fragment = taskTemplate.content.cloneNode(true);
        taskList.appendChild(fragment);
        syncTaskRows();
        const rows = taskList.querySelectorAll("[data-task-row]");
        const newestRow = rows[rows.length - 1];
        newestRow?.querySelector("[data-task-title]")?.focus();
    };

    addTaskButton?.addEventListener("click", () => {
        addTaskRow();
    });

    taskList?.addEventListener("click", (event) => {
        const removeButton = event.target.closest("[data-remove-task-row]");
        if (!removeButton) {
            return;
        }

        const row = removeButton.closest("[data-task-row]");
        if (!row) {
            return;
        }

        row.remove();
        syncTaskRows();
    });

    syncTaskRows();
}
