class ComparisonController {
    constructor(options = {}) {
        this.photos = [];
        this.selectedPhotos = [];
        this.currentMode = null;
        this.activeComparator = null;
        this.activeMultiSync = null;
        this.histogramAnalyzer = new HistogramAnalyzer();
        this.exifDiffAnalyzer = new ExifDiffAnalyzer();
        this.rootMount = options.mount || document.body;
        this.selectorMount = null;
        this.viewerMount = null;
        this.isAdmin = options.isAdmin !== false;
    }

    setAlbumPhotos(rawPhotos) {
        this.photos = rawPhotos.map(p => new PhotoData(
            p.id,
            p.url,
            p.original_filename,
            p.exif || {}
        ));
    }

    openSelector() {
        if (!this.isAdmin) return;
        if (!this.selectorMount) {
            this.selectorMount = document.createElement('div');
            this.selectorMount.id = 'pc-selector-mount';
            document.body.appendChild(this.selectorMount);
        }
        new PhotoSelector(this.selectorMount, this.photos, {
            minSelect: 2,
            maxSelect: 4,
            onConfirm: (selected) => this.onPhotosSelected(selected),
            onCancel: () => {}
        });
    }

    async onPhotosSelected(selected) {
        this.selectedPhotos = selected;
        await Promise.all(selected.map(p => p.load().catch(e => console.warn('加载失败:', p.originalFilename, e))));
        this.openViewer();
    }

    openViewer() {
        this.closeViewer();
        this.viewerMount = document.createElement('div');
        this.viewerMount.id = 'pc-viewer-mount';
        document.body.appendChild(this.viewerMount);

        const count = this.selectedPhotos.length;
        const isTwoMode = count === 2;
        this.currentMode = isTwoMode ? 'before-after' : 'multi';

        this.viewerMount.innerHTML = `
            <div class="pc-viewer fixed inset-0 z-[100] bg-gray-950 text-white flex flex-col">
                <div class="pc-toolbar flex-shrink-0 flex items-center justify-between px-4 py-3 bg-gray-900/80 backdrop-blur border-b border-gray-800">
                    <div class="flex items-center gap-2">
                        <button class="pc-close-btn p-2 rounded-lg hover:bg-gray-700 transition" title="关闭">
                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                        </button>
                        <h3 class="text-sm font-semibold">照片对比 · ${count} 张</h3>
                    </div>

                    <div class="pc-mode-switch flex items-center gap-1 bg-gray-800 rounded-lg p-1">
                        <button class="pc-mode-btn px-3 py-1.5 rounded-md text-xs font-medium transition ${isTwoMode ? 'bg-primary text-white' : 'text-gray-400 hover:text-white'}" data-mode="before-after" ${count !== 2 ? 'disabled style="opacity:0.4;cursor:not-allowed;"' : ''}>
                            双图对比
                        </button>
                        <button class="pc-mode-btn px-3 py-1.5 rounded-md text-xs font-medium transition ${!isTwoMode ? 'bg-primary text-white' : 'text-gray-400 hover:text-white'}" data-mode="multi">
                            多图并排
                        </button>
                    </div>

                    <div class="pc-actions flex items-center gap-2">
                        ${isTwoMode ? `
                            <label class="pc-diff-toggle flex items-center gap-2 px-3 py-1.5 bg-gray-800 hover:bg-gray-700 rounded-lg cursor-pointer transition text-xs">
                                <input type="checkbox" class="pc-show-diff w-3.5 h-3.5 accent-primary">
                                <span>差异高亮</span>
                            </label>
                            <div class="pc-threshold-wrap hidden flex items-center gap-2 text-xs bg-gray-800 rounded-lg px-3 py-1.5">
                                <span>阈值</span>
                                <input type="range" min="5" max="150" value="30" class="pc-threshold w-24 accent-primary">
                                <span class="pc-threshold-val w-8 text-right text-gray-400">30</span>
                            </div>
                        ` : `
                            <label class="pc-sync-toggle flex items-center gap-2 px-3 py-1.5 bg-gray-800 rounded-lg cursor-pointer transition text-xs">
                                <input type="checkbox" class="pc-sync-enabled w-3.5 h-3.5 accent-primary" checked>
                                <span>同步缩放/平移</span>
                            </label>
                            <button class="pc-reset-view px-3 py-1.5 bg-gray-800 hover:bg-gray-700 rounded-lg text-xs transition flex items-center gap-1">
                                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
                                重置视图
                            </button>
                        `}
                    </div>
                </div>

                <div class="pc-body flex-1 flex min-h-0">
                    <div class="pc-main flex-1 min-w-0 p-3"></div>
                    <div class="pc-sidebar w-80 flex-shrink-0 border-l border-gray-800 bg-gray-900/50 overflow-y-auto p-4 space-y-5">
                        <section>
                            <h4 class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path></svg>
                                RGB 直方图
                            </h4>
                            <canvas class="pc-histogram-canvas w-full bg-gray-950 rounded-lg border border-gray-800" height="200"></canvas>
                        </section>
                        <section>
                            <h4 class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"></path></svg>
                                EXIF 差异对比
                            </h4>
                            <div class="pc-exif-diff"></div>
                        </section>
                    </div>
                </div>
            </div>
        `;

        document.body.style.overflow = 'hidden';

        this.bindViewerEvents();
        this.switchMode(this.currentMode);
        this.renderSidebar();
    }

    bindViewerEvents() {
        const vm = this.viewerMount;

        vm.querySelector('.pc-close-btn').addEventListener('click', () => this.closeViewer());

        vm.querySelectorAll('.pc-mode-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                if (btn.disabled) return;
                this.switchMode(btn.dataset.mode);
            });
        });

        const diffToggle = vm.querySelector('.pc-show-diff');
        if (diffToggle) {
            diffToggle.addEventListener('change', (e) => {
                const thresholdWrap = vm.querySelector('.pc-threshold-wrap');
                thresholdWrap.classList.toggle('hidden', !e.target.checked);
                thresholdWrap.classList.toggle('flex', e.target.checked);
                this.activeComparator?.toggleDiff(e.target.checked);
            });
        }

        const thresholdInput = vm.querySelector('.pc-threshold');
        if (thresholdInput) {
            thresholdInput.addEventListener('input', (e) => {
                vm.querySelector('.pc-threshold-val').textContent = e.target.value;
                this.activeComparator?.setDiffThreshold(parseInt(e.target.value));
            });
        }

        const syncToggle = vm.querySelector('.pc-sync-enabled');
        if (syncToggle) {
            syncToggle.addEventListener('change', (e) => {
                this.activeMultiSync?.setSyncEnabled(e.target.checked);
            });
        }

        const resetBtn = vm.querySelector('.pc-reset-view');
        if (resetBtn) {
            resetBtn.addEventListener('click', () => this.activeMultiSync?.resetView());
        }

        document.addEventListener('keydown', this._escHandler = (e) => {
            if (e.key === 'Escape') this.closeViewer();
        });
    }

    switchMode(mode) {
        this.currentMode = mode;
        const vm = this.viewerMount;
        const main = vm.querySelector('.pc-main');

        vm.querySelectorAll('.pc-mode-btn').forEach(btn => {
            btn.classList.toggle('bg-primary', btn.dataset.mode === mode);
            btn.classList.toggle('text-white', btn.dataset.mode === mode);
            btn.classList.toggle('text-gray-400', btn.dataset.mode !== mode);
        });

        if (this.activeComparator) { this.activeComparator.destroy(); this.activeComparator = null; }
        if (this.activeMultiSync) { this.activeMultiSync.destroy(); this.activeMultiSync = null; }

        if (mode === 'before-after' && this.selectedPhotos.length === 2) {
            this.activeComparator = new BeforeAfterComparator(main, this.selectedPhotos[0], this.selectedPhotos[1]);
        } else {
            this.activeMultiSync = new MultiImageSync(main, this.selectedPhotos);
        }
    }

    renderSidebar() {
        const vm = this.viewerMount;
        const histCanvas = vm.querySelector('.pc-histogram-canvas');
        const exifDiffEl = vm.querySelector('.pc-exif-diff');

        const dpr = window.devicePixelRatio || 1;
        const displayWidth = histCanvas.clientWidth || 300;
        histCanvas.width = displayWidth * dpr;
        histCanvas.height = 200 * dpr;
        histCanvas.getContext('2d').scale(dpr, dpr);
        histCanvas.style.width = displayWidth + 'px';
        histCanvas.style.height = '200px';

        const labels = this.selectedPhotos.map(p => p.originalFilename.substring(0, 12));
        const histograms = this.selectedPhotos.map(p => this.histogramAnalyzer.computeHistogram(p));
        const renderCanvas = document.createElement('canvas');
        renderCanvas.width = displayWidth;
        renderCanvas.height = 200;
        this.histogramAnalyzer.renderMultiToCanvas(histograms, renderCanvas, labels);
        histCanvas.getContext('2d').drawImage(renderCanvas, 0, 0);

        this.exifDiffAnalyzer.renderDiffList(this.selectedPhotos, exifDiffEl);
    }

    closeViewer() {
        if (this.viewerMount) {
            this.viewerMount.remove();
            this.viewerMount = null;
        }
        if (this.activeComparator) { this.activeComparator.destroy(); this.activeComparator = null; }
        if (this.activeMultiSync) { this.activeMultiSync.destroy(); this.activeMultiSync = null; }
        document.removeEventListener('keydown', this._escHandler);
        document.body.style.overflow = '';
    }

    injectEntryButton(container, albumPhotos) {
        if (!this.isAdmin) return;
        this.setAlbumPhotos(albumPhotos);
        const existingBtn = container.querySelector('#pc-entry-btn');
        if (existingBtn) existingBtn.remove();

        const btn = document.createElement('button');
        btn.id = 'pc-entry-btn';
        btn.className = 'bg-white hover:bg-gray-50 text-gray-700 border border-gray-200 px-5 py-2.5 rounded-lg shadow-sm transition flex items-center justify-center';
        btn.innerHTML = `
            <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z"></path></svg>
            对比模式
        `;
        btn.addEventListener('click', () => this.openSelector());
        container.appendChild(btn);
    }
}

if (typeof window !== 'undefined') {
    window.ComparisonController = ComparisonController;
}
