document.querySelectorAll("form").forEach((form) => {
    const destructiveButton = form.querySelector(".button-link");
    if (!destructiveButton) {
        return;
    }

    form.addEventListener("submit", (event) => {
        const confirmed = window.confirm("Are you sure you want to delete this item?");
        if (!confirmed) {
            event.preventDefault();
        }
    });
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
