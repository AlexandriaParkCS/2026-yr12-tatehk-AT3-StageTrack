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

const templateForm = document.querySelector("[data-template-form]");

if (templateForm) {
    const templateList = templateForm.querySelector("[data-template-list]");
    const templateTemplate = templateForm.querySelector("[data-template-row-template]");
    const templateCountInput = templateForm.querySelector("[data-template-count]");
    const addTemplateButton = templateForm.querySelector("[data-add-template-row]");

    const syncTemplateRows = () => {
        const rows = Array.from(templateList.querySelectorAll("[data-template-row]"));
        rows.forEach((row, index) => {
            row.querySelector("[data-template-title]")?.setAttribute("name", `template_title_${index}`);
            row.querySelector("[data-template-role]")?.setAttribute("name", `template_role_${index}`);
            row.querySelector("[data-template-offset]")?.setAttribute("name", `template_due_offset_${index}`);
            row.querySelector("[data-template-description]")?.setAttribute("name", `template_description_${index}`);
            const removeButton = row.querySelector("[data-remove-template-row]");
            if (removeButton) {
                removeButton.hidden = rows.length === 1;
            }
        });
        templateCountInput.value = rows.length;
    };

    const addTemplateRow = () => {
        const fragment = templateTemplate.content.cloneNode(true);
        templateList.appendChild(fragment);
        syncTemplateRows();
    };

    addTemplateButton?.addEventListener("click", addTemplateRow);
    templateList?.addEventListener("click", (event) => {
        const removeButton = event.target.closest("[data-remove-template-row]");
        if (!removeButton) {
            return;
        }
        removeButton.closest("[data-template-row]")?.remove();
        syncTemplateRows();
    });

    syncTemplateRows();
}

const templateApplyForm = document.querySelector("[data-template-apply-form]");

if (templateApplyForm) {
    templateApplyForm.addEventListener("submit", (event) => {
        const templateSelect = templateApplyForm.querySelector("[data-template-select]");
        const templateId = templateSelect?.value;
        if (!templateId) {
            event.preventDefault();
            window.alert("Choose a task template first.");
            return;
        }
        templateApplyForm.action = templateApplyForm.action.replace(/\/0\/apply$/, `/${templateId}/apply`);
    });
}

document.querySelectorAll("[data-live-task]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const submitter = event.submitter;
        const formData = new FormData(form);
        if (submitter?.name && submitter?.value) {
            formData.set(submitter.name, submitter.value);
        }

        const response = await fetch(form.action, {
            method: "POST",
            headers: { "X-Requested-With": "XMLHttpRequest" },
            body: formData,
        });

        if (!response.ok) {
            window.location.reload();
            return;
        }

        const payload = await response.json();
        const card = form.closest(".dashboard-item");
        const statusPill = card?.querySelector(".status-pill");
        if (statusPill) {
            statusPill.textContent = payload.display_status;
            statusPill.classList.toggle("status-pill-danger", payload.display_status === "Overdue");
        }
        if (payload.status === "Completed") {
            card?.remove();
            return;
        }
        const buttons = form.querySelectorAll("button[name='status']");
        buttons.forEach((button) => {
            if (button.value === "In Progress") {
                button.hidden = payload.status === "In Progress";
            }
            if (button.value === "Completed") {
                button.hidden = payload.status === "Completed";
            }
            if (button.value === "Pending") {
                button.hidden = payload.status !== "Completed";
            }
        });
    });
});
