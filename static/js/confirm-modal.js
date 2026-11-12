/* Modal de confirmación (aprobar/rechazar/archivar/rectificar...). */
    document.addEventListener("DOMContentLoaded", function () {
        const modal = document.getElementById("confirm-modal");
        const confirmBtn = document.getElementById("modal-confirm");
        const form = document.getElementById("modal-form");
        const modalReason = document.getElementById("modal-reason");
        
        let currentAction = null;
        
        document.querySelectorAll(".confirm-action").forEach(btn => {
        btn.addEventListener("click", function () {
            currentAction = this.dataset.action;

            const docData = document.getElementById("doc-data");
            const docName = docData.dataset.name;
            const docType = docData.dataset.type;
            const docTotalAmount = docData.dataset.totalAmount;


            const docDataContent = `
                <div class="modal-doc-summary">
                    <strong>${docName}</strong>
                    <div class="meta">
                    ${docType} · ${docTotalAmount} €
                    </div>
                </div>
            `;


            const icon = document.querySelector(".modal-icon i");
            const docInfo = document.getElementById("modal-doc-info");
            const title = document.getElementById("modal-title");
            const text = document.getElementById("modal-text");
            const confirmBtn = document.getElementById("modal-confirm");

            // 👉 Siempre mostrar info del documento
            docInfo.innerHTML = docDataContent;

            switch (currentAction) {
                case "approve":
                    icon.className = "fa-solid fa-check";
                    icon.style.color = "var(--color-success)";
                    title.textContent = "Confirmar aprobación";
                    text.textContent = "El documento se marcará como aprobado.";
                    confirmBtn.textContent = "Aprobar";
                    confirmBtn.className = "btn btn-success";
                    modalReason.classList.add("hidden");
                    modalReason.value = "";
                    break;
                case "reject":
                    icon.className = "fa-solid fa-xmark";
                    icon.style.color = "var(--color-danger)";
                    title.textContent = "Confirmar rechazo";
                    text.textContent = "El documento será rechazado definitivamente.";
                    confirmBtn.textContent = "Rechazar";
                    confirmBtn.className = "btn btn-danger";
                    modalReason.classList.remove("hidden");
                    modalReason.placeholder = "Motivo del rechazo (opcional)";
                    break;
                case "archive":
                    icon.className = "fa-solid fa-box-archive";
                    icon.style.color = "var(--muted-color)";
                    title.textContent = "Confirmar archivo";
                    text.textContent = "El documento será archivado.";
                    confirmBtn.textContent = "Archivar";
                    confirmBtn.className = "btn btn-primary";
                    modalReason.classList.add("hidden");
                    modalReason.value = "";
                    break;
                case "unarchive":
                    icon.className = "fa-solid fa-box-open";
                    icon.style.color = "var(--muted-color)";
                    title.textContent = "Confirmar desarchivo";
                    text.textContent = "El documento volverá a estar activo.";
                    confirmBtn.textContent = "Desarchivar";
                    confirmBtn.className = "btn btn-primary";
                    modalReason.classList.add("hidden");
                    modalReason.value = "";
                    break;
                case "rectify":
                    icon.className = "fa-solid fa-pen-to-square";
                    icon.style.color = "var(--color-warning)";
                    title.textContent = "Crear rectificación";
                    text.textContent = "Podrá crear una nueva versión de este documento. Los datos originales se conservarán.";
                    confirmBtn.textContent = "Rectificar";
                    confirmBtn.className = "btn btn-warning";
                    modalReason.classList.add("hidden");
                    modalReason.value = "";
                    break;
                default:
                    break;
            }

            modal.classList.add("open");
        });
    });

    confirmBtn.addEventListener("click", function () {
        if (!currentAction) return;

        // Crear input hidden dinámicamente
        const hiddenInput = document.createElement("input");
        hiddenInput.type = "hidden";
        hiddenInput.name = "action";
        hiddenInput.value = currentAction;

        // Aprobar envía el formulario de revisión: así no se pierden los cambios sin guardar.
        const reviewForm = document.getElementById("review-form");
        const target = currentAction === "approve" && reviewForm ? reviewForm : form;
        target.appendChild(hiddenInput);
        target.submit();
    });

    document.querySelectorAll("[data-close]").forEach(btn => {
        btn.addEventListener("click", function () {
        modal.classList.remove("open");
        });
    });

    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") {
        modal.classList.remove("open");
        }
    });

    });
    