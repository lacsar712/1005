class MultiImageSync {
    constructor(container, photos, options = {}) {
        this.container = typeof container === 'string' ? document.querySelector(container) : container;
        this.photos = photos;
        this.views = [];
        this.syncEnabled = true;
        this.onStateChange = options.onStateChange || (() => {});
        this.render();
    }

    render() {
        const count = this.photos.length;
        let colsClass = 'grid-cols-1';
        if (count === 2) colsClass = 'grid-cols-2';
        else if (count === 3) colsClass = 'grid-cols-3';
        else if (count >= 4) colsClass = 'grid-cols-2 md:grid-cols-4';

        this.container.innerHTML = `
            <div class="pc-multi-grid grid ${colsClass} gap-2 h-full w-full">
                ${this.photos.map((photo, idx) => `
                    <div class="pc-multi-pane relative rounded-lg overflow-hidden bg-gray-900 flex flex-col" data-index="${idx}">
                        <div class="px-2 py-1.5 bg-black/50 text-white text-xs truncate backdrop-blur-sm flex-shrink-0">
                            图${idx + 1}: ${photo.originalFilename}
                        </div>
                        <div class="pc-canvas-wrap flex-1 overflow-hidden cursor-grab active:cursor-grabbing relative" data-index="${idx}">
                            <canvas class="pc-canvas block"></canvas>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;

        this.panes = this.container.querySelectorAll('.pc-multi-pane');
        this.initCanvases();
        this.bindEvents();
    }

    initCanvases() {
        this.panes.forEach((pane, idx) => {
            const wrap = pane.querySelector('.pc-canvas-wrap');
            const canvas = pane.querySelector('.pc-canvas');
            const photo = this.photos[idx];

            const view = {
                index: idx,
                wrap,
                canvas,
                ctx: canvas.getContext('2d'),
                photo,
                scale: 1,
                offsetX: 0,
                offsetY: 0,
                baseScale: 1
            };
            this.views.push(view);

            const fitToPane = () => {
                const wrapRect = wrap.getBoundingClientRect();
                canvas.width = wrapRect.width;
                canvas.height = wrapRect.height;
                view.baseScale = Math.min(
                    canvas.width / photo.width,
                    canvas.height / photo.height
                );
                view.scale = view.baseScale;
                view.offsetX = (canvas.width - photo.width * view.scale) / 2;
                view.offsetY = (canvas.height - photo.height * view.scale) / 2;
                this.drawView(view);
            };

            photo.load().then(() => fitToPane());
            new ResizeObserver(() => fitToPane()).observe(wrap);
        });
    }

    drawView(view) {
        const { ctx, canvas, photo, scale, offsetX, offsetY } = view;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.save();
        ctx.fillStyle = '#111827';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        if (photo.image) {
            ctx.drawImage(photo.image, offsetX, offsetY, photo.width * scale, photo.height * scale);
        }
        ctx.restore();
    }

    bindEvents() {
        this.views.forEach(view => {
            const wrap = view.wrap;
            let isPanning = false;
            let startX = 0, startY = 0;

            wrap.addEventListener('mousedown', (e) => {
                isPanning = true;
                startX = e.clientX;
                startY = e.clientY;
            });
            window.addEventListener('mousemove', (e) => {
                if (!isPanning) return;
                const dx = e.clientX - startX;
                const dy = e.clientY - startY;
                startX = e.clientX;
                startY = e.clientY;
                this.pan(view, dx, dy);
            });
            window.addEventListener('mouseup', () => { isPanning = false; });

            wrap.addEventListener('touchstart', (e) => {
                if (e.touches.length === 1) {
                    isPanning = true;
                    startX = e.touches[0].clientX;
                    startY = e.touches[0].clientY;
                }
            }, { passive: true });
            wrap.addEventListener('touchmove', (e) => {
                if (!isPanning || e.touches.length !== 1) return;
                const dx = e.touches[0].clientX - startX;
                const dy = e.touches[0].clientY - startY;
                startX = e.touches[0].clientX;
                startY = e.touches[0].clientY;
                this.pan(view, dx, dy);
            }, { passive: true });
            wrap.addEventListener('touchend', () => { isPanning = false; });

            wrap.addEventListener('wheel', (e) => {
                e.preventDefault();
                const rect = wrap.getBoundingClientRect();
                const mx = e.clientX - rect.left;
                const my = e.clientY - rect.top;
                const delta = e.deltaY > 0 ? 0.9 : 1.1;
                this.zoom(view, mx, my, delta);
            }, { passive: false });
        });
    }

    pan(sourceView, dx, dy) {
        if (this.syncEnabled) {
            this.views.forEach(v => {
                v.offsetX += dx;
                v.offsetY += dy;
                this.drawView(v);
            });
        } else {
            sourceView.offsetX += dx;
            sourceView.offsetY += dy;
            this.drawView(sourceView);
        }
        this.onStateChange({ type: 'pan' });
    }

    zoom(sourceView, mx, my, factor) {
        const applyZoom = (v) => {
            const newScale = Math.max(v.baseScale * 0.1, Math.min(v.scale * factor, v.baseScale * 20));
            const ratio = newScale / v.scale;
            v.offsetX = mx - (mx - v.offsetX) * ratio;
            v.offsetY = my - (my - v.offsetY) * ratio;
            v.scale = newScale;
            this.drawView(v);
        };

        if (this.syncEnabled) {
            this.views.forEach(v => applyZoom(v));
        } else {
            applyZoom(sourceView);
        }
        this.onStateChange({ type: 'zoom' });
    }

    resetView() {
        this.views.forEach(v => {
            v.scale = v.baseScale;
            v.offsetX = (v.canvas.width - v.photo.width * v.scale) / 2;
            v.offsetY = (v.canvas.height - v.photo.height * v.scale) / 2;
            this.drawView(v);
        });
        this.onStateChange({ type: 'reset' });
    }

    setSyncEnabled(enabled) {
        this.syncEnabled = enabled;
        if (enabled && this.views.length > 0) {
            const ref = this.views[0];
            this.views.forEach((v, i) => {
                if (i === 0) return;
                const scaleRatio = ref.scale / ref.baseScale;
                v.scale = v.baseScale * scaleRatio;
                const xRatio = ref.offsetX / (ref.canvas.width || 1);
                const yRatio = ref.offsetY / (ref.canvas.height || 1);
                v.offsetX = xRatio * v.canvas.width;
                v.offsetY = yRatio * v.canvas.height;
                this.drawView(v);
            });
        }
        this.onStateChange({ type: 'sync', enabled });
    }

    destroy() {
        this.container.innerHTML = '';
        this.views = [];
    }
}

if (typeof window !== 'undefined') {
    window.MultiImageSync = MultiImageSync;
}
