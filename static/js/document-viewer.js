/* Visor de PDF/imagen (pdf.js) compartido por detalle y rectificación.
   Requiere pdf.min.js y un elemento [data-file-url][data-file-type]. */
    document.addEventListener("DOMContentLoaded", function () {
        
        const host = document.querySelector("[data-file-url]");
        if (!host) return;
        const url = host.dataset.fileUrl;
        const fileType = host.dataset.fileType;
        const pdfContainer = document.getElementById('pdf-viewer');
        const fallback = document.getElementById('pdf-fallback');
        const imageContainer = document.getElementById('image-container');
        
        if (!pdfContainer) {
            console.warn("pdf-viewer no existe en este layout");
        }
        
        let pdfDoc = null;
        let pageNum = 1;
        let scale = 1.2;

        let imageScale = 1;
        const MIN_SCALE = 0.5;
        const MAX_SCALE = 4;
        let translateX = 0;
        let translateY = 0;
        let isDragging = false;
        let startX = 0;
        let startY = 0;
        let rotation = 0;
        let currentCanvas = null;

        // Arrastrar para mover el documento con cualquier zoom (ratón y táctil).
        // Mueve con translate, así funciona también cuando el documento es más pequeño que el visor.
        function enablePan(surface, apply) {
            surface.style.touchAction = "none";
            surface.style.cursor = "grab";
            let dragging = false, sx = 0, sy = 0;

            surface.addEventListener("pointerdown", (e) => {
                if (e.button !== undefined && e.button !== 0) return;
                dragging = true;
                sx = e.clientX - translateX;
                sy = e.clientY - translateY;
                surface.setPointerCapture(e.pointerId);
                surface.style.cursor = "grabbing";
                e.preventDefault();
            });
            surface.addEventListener("pointermove", (e) => {
                if (!dragging) return;
                translateX = e.clientX - sx;
                translateY = e.clientY - sy;
                apply();
            });
            const end = () => { dragging = false; surface.style.cursor = "grab"; };
            surface.addEventListener("pointerup", end);
            surface.addEventListener("pointercancel", end);
        }

        function applyPdfPan() {
            if (currentCanvas) currentCanvas.style.transform = `translate(${translateX}px, ${translateY}px)`;
        }

        pdfjsLib.GlobalWorkerOptions.workerSrc =
        "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.9.179/pdf.worker.min.js";
                    
        function renderPage(num) {
            if (!pdfDoc) return;

            pdfDoc.getPage(num).then(page => {

                const viewport = page.getViewport({
                    scale: scale,
                    rotation: rotation
                });
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');

                canvas.height = viewport.height;
                canvas.width = viewport.width;

                canvas.style.display = "block";
                canvas.style.margin = "0 auto";
                pdfContainer.innerHTML = '';
                pdfContainer.appendChild(canvas);
                currentCanvas = canvas;
                applyPdfPan();

                page.render({ 
                    canvasContext: ctx, viewport: viewport 
                });

                const pageNumEl = document.getElementById('page-num');
                const pageCountEl = document.getElementById('page-count');

                if (pageNumEl) pageNumEl.textContent = pageNum;
                if (pageCountEl) pageCountEl.textContent = pdfDoc.numPages;

                // Avisa a otras partes de la página (p. ej. las líneas de la factura)
                document.dispatchEvent(new CustomEvent("viewer:page", {
                    detail: { page: num, total: pdfDoc.numPages },
                }));

            }).catch(err => {
                console.error("Error renderizando página:", err);
            });
        }

        function loadPDF() {
            pdfjsLib.getDocument({ url: url}).promise
                .then(pdf => {
                    pdfDoc = pdf;
                    renderPage(pageNum);
                })
                .catch(err => {
                    console.warn("No es un PDF válido, mostrando imagen:", err);
                    showImage();
                });
        }


        function showImage() {
            imageScale = 1;
            translateX = 0;
            translateY = 0;

            imageContainer.innerHTML = `
                <img id="zoomable-image" 
                    src="${url}" 
                    style="
                        max-width:100%;
                        height:auto;
                        user-select: none;
                        -webkit-user-drag: none;
                        transform-origin: center center;
                    "
                />
            `;

            const img = document.getElementById("zoomable-image");

            function updateTransform() {
                img.style.transform = `translate(${translateX}px, ${translateY}px) scale(${imageScale})`;
            }

            imageContainer.onwheel = function (e) {
                e.preventDefault();

                const zoomIntensity = 0.1;

                if (e.deltaY < 0) {
                    imageScale = Math.min(MAX_SCALE, imageScale + zoomIntensity);
                } else {
                    imageScale = Math.max(MIN_SCALE, imageScale - zoomIntensity);
                }

                updateTransform();
            };

            img.addEventListener("dragstart", (e) => {
                e.preventDefault();
            });

            enablePan(imageContainer, updateTransform);

            imageContainer.addEventListener("dblclick", () => {
                imageScale = 1;
                translateX = 0;
                translateY = 0;
                updateTransform();
            });

        }

        // wheel zoom + arrastre para pdf
        if (pdfContainer) {
            pdfContainer.addEventListener("wheel", function (e) {
                e.preventDefault();
                const zoomIntensity = 0.05;
                if (e.deltaY < 0) {
                    scale = Math.min(MAX_SCALE, scale + zoomIntensity); // Zoom in
                } else {
                    scale = Math.max(MIN_SCALE, scale - zoomIntensity); // Zoom out
                }
                renderPage(pageNum);
            }, { passive: false });

            enablePan(pdfContainer, applyPdfPan);

            pdfContainer.addEventListener("dblclick", () => {
                scale = 1.2;
                translateX = 0;
                translateY = 0;
                renderPage(pageNum);
            });
        }

        // Detectar extensión
        if (fileType === "pdf") {
            loadPDF();
        } else {
            showImage();
        }

        // Toolbar events (protegidos)
        const prevBtn = document.getElementById('prev-page');
        const nextBtn = document.getElementById('next-page');
        const zoomInBtn = document.getElementById('zoom-in');
        const zoomOutBtn = document.getElementById('zoom-out');
        const rotateRightBtn = document.getElementById('rotate-right');
        const rotateLeftBtn = document.getElementById('rotate-left');

        if (prevBtn) {
            prevBtn.addEventListener('click', () => {
                if (pageNum > 1) {
                    pageNum--;
                    translateX = 0; translateY = 0;
                    renderPage(pageNum);
                }
            });
        }

        if (nextBtn) {
            nextBtn.addEventListener('click', () => {
                if (pdfDoc && pageNum < pdfDoc.numPages) {
                    pageNum++;
                    translateX = 0; translateY = 0;
                    renderPage(pageNum);
                }
            });
        }

        if (zoomInBtn) {
            zoomInBtn.addEventListener('click', () => {
                scale += 0.2;
                renderPage(pageNum);
            });
        }

        if (zoomOutBtn) {
            zoomOutBtn.addEventListener('click', () => {
                scale = Math.max(0.2, scale - 0.2);
                renderPage(pageNum);
            });
        }

        function rotateRight() {
            rotation = (rotation + 90) % 360;
            renderPage(pageNum);
        }

        function rotateLeft() {
            rotation = (rotation - 90 + 360) % 360;
            renderPage(pageNum);
        }

        if (rotateRightBtn) {
            rotateRightBtn.addEventListener('click', () => {
                rotateRight();
            });
        }

        if (rotateLeftBtn) {
            rotateLeftBtn.addEventListener('click', () => {
                rotateLeft();
            });
        }

    });
    