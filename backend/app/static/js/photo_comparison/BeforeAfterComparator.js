class BeforeAfterComparator {
    constructor(container, photoA, photoB, options = {}) {
        this.container = typeof container === 'string' ? document.querySelector(container) : container;
        this.photoA = photoA;
        this.photoB = photoB;
        this.dividerPosition = 0.5;
        this.showDiff = false;
        this.diffHighlighter = options.diffHighlighter || new DiffHighlighter();
        this.diffResult = null;
        this.diffCanvas = null;
        this.isDragging = false;
        this.onStateChange = options.onStateChange || (() => {});
        this.render();
    }

    render() {
        this.container.innerHTML = `
            <div class="pc-before-after relative w-full h-full select-none overflow-hidden rounded-lg bg-gray-900" style="min-height: 400px;">
                <div class="pc-layer pc-layer-before absolute inset-0 flex items-center justify-center">
                    <img class="pc-image max-w-full max-h-full object-contain" src="${this.photoA.url}" alt="Before">
                </div>
                <div class="pc-layer pc-layer-after absolute inset-0 flex items-center justify-center overflow-hidden" style="clip-path: inset(0 0 0 50%);">
                    <img class="pc-image max-w-full max-h-full object-contain" src="${this.photoB.url}" alt="After">
                </div>
                <div class="pc-diff-layer absolute inset-0 flex items-center justify-center pointer-events-none" style="display: none;"></div>
                <div class="pc-divider absolute top-0 bottom-0 w-1 bg-white shadow-lg cursor-ew-resize z-10" style="left: 50%; transform: translateX(-50%);">
                    <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-10 h-10 bg-white rounded-full shadow-lg flex items-center justify-center cursor-grab active:cursor-grabbing">
                        <svg class="w-5 h-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l4-4 4 4m0 6l-4 4-4-4"></path></svg>
                    </div>
                </div>
                <div class="pc-labels absolute inset-x-0 bottom-3 flex justify-between px-4 pointer-events-none">
                    <span class="bg-black/60 text-white text-xs px-3 py-1 rounded-full backdrop-blur-sm">图1: ${this.photoA.originalFilename}</span>
                    <span class="bg-black/60 text-white text-xs px-3 py-1 rounded-full backdrop-blur-sm">图2: ${this.photoB.originalFilename}</span>
                </div>
            </div>
        `;

        this.layerAfter = this.container.querySelector('.pc-layer-after');
        this.divider = this.container.querySelector('.pc-divider');
        this.diffLayer = this.container.querySelector('.pc-diff-layer');

        this.bindEvents();
    }

    bindEvents() {
        const dividerHandle = this.divider;

        const onPointerDown = (e) => {
            this.isDragging = true;
            e.preventDefault();
        };

        const onPointerMove = (e) => {
            if (!this.isDragging) return;
            const rect = this.container.querySelector('.pc-before-after').getBoundingClientRect();
            let percent = (e.clientX - rect.left) / rect.width;
            percent = Math.max(0, Math.min(1, percent));
            this.setDividerPosition(percent);
        };

        const onPointerUp = () => {
            this.isDragging = false;
        };

        dividerHandle.addEventListener('mousedown', onPointerDown);
        dividerHandle.addEventListener('touchstart', (e) => {
            this.isDragging = true;
        }, { passive: true });

        window.addEventListener('mousemove', onPointerMove);
        window.addEventListener('touchmove', (e) => {
            if (!this.isDragging) return;
            const touch = e.touches[0];
            const rect = this.container.querySelector('.pc-before-after').getBoundingClientRect();
            let percent = (touch.clientX - rect.left) / rect.width;
            percent = Math.max(0, Math.min(1, percent));
            this.setDividerPosition(percent);
        }, { passive: true });

        window.addEventListener('mouseup', onPointerUp);
        window.addEventListener('touchend', onPointerUp);
    }

    setDividerPosition(percent) {
        this.dividerPosition = percent;
        this.layerAfter.style.clipPath = `inset(0 0 0 ${percent * 100}%)`;
        this.divider.style.left = `${percent * 100}%`;
        this.onStateChange({ type: 'divider', position: percent });
    }

    async toggleDiff(show) {
        this.showDiff = show;
        if (show) {
            if (!this.diffResult) {
                try {
                    this.diffResult = await this.diffHighlighter.computeDiff(this.photoA, this.photoB);
                } catch (e) {
                    this.showToast(e.message || '差异计算失败');
                    this.showDiff = false;
                    this.onStateChange({ type: 'diff', enabled: false });
                    return;
                }
            }
            this.diffLayer.innerHTML = '';
            const img = this.container.querySelector('.pc-layer-before img');
            const cloneCanvas = document.createElement('canvas');
            cloneCanvas.style.cssText = 'max-width:100%;max-height:100%;object-fit:contain;';
            cloneCanvas.width = this.diffResult.canvas.width;
            cloneCanvas.height = this.diffResult.canvas.height;
            cloneCanvas.getContext('2d').drawImage(this.diffResult.canvas, 0, 0);
            this.diffLayer.appendChild(cloneCanvas);
            this.diffLayer.style.display = '';
        } else {
            this.diffLayer.style.display = 'none';
        }
        this.onStateChange({ type: 'diff', enabled: this.showDiff, result: this.diffResult });
    }

    setDiffThreshold(threshold) {
        this.diffHighlighter.setThreshold(threshold);
        if (this.showDiff) {
            this.diffResult = null;
            this.toggleDiff(true);
        }
    }

    showToast(msg) {
        if (typeof Swal !== 'undefined') {
            const Toast = Swal.mixin({ toast: true, position: 'top', showConfirmButton: false, timer: 2500 });
            Toast.fire({ icon: 'warning', title: msg });
        } else {
            alert(msg);
        }
    }

    destroy() {
        this.container.innerHTML = '';
    }
}

if (typeof window !== 'undefined') {
    window.BeforeAfterComparator = BeforeAfterComparator;
}
