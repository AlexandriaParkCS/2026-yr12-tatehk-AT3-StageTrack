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
