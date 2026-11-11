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

                pdfContainer.innerHTML = '';
                pdfContainer.appendChild(canvas);

                page.render({ 
                    canvasContext: ctx, viewport: viewport 
                });

                const pageNumEl = document.getElementById('page-num');
                const pageCountEl = document.getElementById('page-count');

                if (pageNumEl) pageNumEl.textContent = pageNum;
                if (pageCountEl) pageCountEl.textContent = pdfDoc.numPages;

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
                        cursor: grab;
                        user-select: none;
                        transform-origin: center center;
                        transition: transform 0.05s ease;
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

                if (imageScale === 1) {
                    translateX = 0;
                    translateY = 0;
                }

                updateTransform();
            };

            img.addEventListener("dragstart", (e) => {
                e.preventDefault();
            });

            img.addEventListener("mousedown", (e) => {
                if (imageScale <= 1) return; // solo mover si está ampliada

                isDragging = true;
                startX = e.clientX - translateX;
                startY = e.clientY - translateY;

                img.style.cursor = "grabbing";
            });

            window.addEventListener("mousemove", (e) => {
                if (!isDragging) return;

                translateX = e.clientX - startX;
                translateY = e.clientY - startY;

                updateTransform();
            });

            window.addEventListener("mouseup", () => {
                isDragging = false;
                img.style.cursor = "grab";
            });

            imageContainer.addEventListener("dblclick", () => {
                imageScale = 1;
                translateX = 0;
                translateY = 0;
                updateTransform();
            });

        }

        // wheel zoom para pdf
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

            let isDragging = false;
            let startX, startY, scrollLeft, scrollTop;

            pdfContainer.addEventListener("mousedown", (e) => {
                if (scale <= 1) return;
                isDragging = true;
                startX = e.pageX - pdfContainer.offsetLeft;
                startY = e.pageY - pdfContainer.offsetTop;
                scrollLeft = pdfContainer.scrollLeft;
                scrollTop = pdfContainer.scrollTop;
            });

            pdfContainer.addEventListener("mousemove", (e) => {
                if (!isDragging) return;
                e.preventDefault();
                const x = e.pageX - pdfContainer.offsetLeft;
                const y = e.pageY - pdfContainer.offsetTop;
                pdfContainer.scrollLeft = scrollLeft - (x - startX);
                pdfContainer.scrollTop = scrollTop - (y - startY);
            });

            pdfContainer.addEventListener("mouseup", () => isDragging = false);
            pdfContainer.addEventListener("mouseleave", () => isDragging = false);

            pdfContainer.addEventListener("dblclick" , (e) => {
                scale = 1.2;
                renderPage(pageNum);
            })
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
                    renderPage(pageNum);
                }
            });
        }

        if (nextBtn) {
            nextBtn.addEventListener('click', () => {
                if (pdfDoc && pageNum < pdfDoc.numPages) {
                    pageNum++;
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
    