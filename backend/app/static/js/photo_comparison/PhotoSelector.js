class PhotoSelector {
    constructor(container, photos, options = {}) {
        this.container = typeof container === 'string' ? document.querySelector(container) : container;
        this.photos = photos;
        this.selected = new Set();
        this.minSelect = options.minSelect || 2;
        this.maxSelect = options.maxSelect || 4;
        this.onConfirm = options.onConfirm || (() => {});
        this.onCancel = options.onCancel || (() => {});
        this.render();
    }

    render() {
        this.container.innerHTML = `
            <div class="pc-modal-overlay fixed inset-0 bg-black/60 z-[100] flex items-center justify-center p-4">
                <div class="pc-modal bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col">
                    <div class="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
                        <div>
                            <h3 class="text-lg font-semibold text-gray-900">选择照片进行对比</h3>
                            <p class="text-sm text-gray-500 mt-1">请选择 ${this.minSelect}–${this.maxSelect} 张照片</p>
                        </div>
                        <button class="pc-cancel-btn text-gray-400 hover:text-gray-600 transition">
                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                        </button>
                    </div>
                    <div class="pc-photo-grid flex-1 overflow-y-auto p-4">
                        <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3"></div>
                    </div>
                    <div class="px-6 py-4 border-t border-gray-100 flex items-center justify-between bg-gray-50 rounded-b-2xl">
                        <div class="text-sm text-gray-600">
                            已选 <span class="pc-count font-semibold text-primary">0</span> / ${this.maxSelect} 张
                        </div>
                        <div class="flex gap-2">
                            <button class="pc-cancel-btn px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 transition">取消</button>
                            <button class="pc-confirm-btn px-4 py-2 bg-primary hover:bg-blue-600 text-white rounded-lg shadow-sm transition disabled:opacity-50 disabled:cursor-not-allowed" disabled>
                                开始对比
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        const grid = this.container.querySelector('.pc-photo-grid > div');
        this.photos.forEach(photo => {
            const item = document.createElement('div');
            item.className = 'pc-photo-item relative group rounded-lg overflow-hidden border-2 border-gray-200 hover:border-primary/50 cursor-pointer transition';
            item.dataset.photoId = photo.id;
            item.innerHTML = `
                <img src="${photo.url}" alt="${photo.originalFilename}" class="w-full h-32 object-cover">
                <div class="pc-check-overlay absolute inset-0 bg-primary/0 group-hover:bg-primary/10 transition flex items-center justify-center">
                    <div class="pc-check-icon w-7 h-7 rounded-full border-2 border-white/80 bg-white/20 opacity-0 group-hover:opacity-100 transition flex items-center justify-center">
                        <svg class="w-4 h-4 text-white opacity-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path></svg>
                    </div>
                </div>
                <div class="pc-badge absolute top-2 right-2 bg-primary text-white text-xs font-bold w-6 h-6 rounded-full flex items-center justify-center hidden shadow-lg"></div>
                <div class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent px-2 py-1.5 pointer-events-none">
                    <span class="text-white text-xs truncate block">${photo.originalFilename}</span>
                </div>
            `;
            item.addEventListener('click', () => this.toggleSelection(photo.id, item));
            grid.appendChild(item);
        });

        this.container.querySelectorAll('.pc-cancel-btn').forEach(btn => {
            btn.addEventListener('click', () => this.destroy());
        });
        this.container.querySelector('.pc-confirm-btn').addEventListener('click', () => {
            if (this.selected.size >= this.minSelect) {
                const selectedPhotos = this.photos.filter(p => this.selected.has(p.id));
                this.onConfirm(selectedPhotos);
                this.destroy();
            }
        });

        this.container.querySelector('.pc-modal-overlay').addEventListener('click', (e) => {
            if (e.target.classList.contains('pc-modal-overlay')) this.destroy();
        });

        document.body.style.overflow = 'hidden';
    }

    toggleSelection(id, element) {
        if (this.selected.has(id)) {
            this.selected.delete(id);
            element.classList.remove('border-primary', 'ring-2', 'ring-primary/30');
            element.classList.add('border-gray-200');
            element.querySelector('.pc-check-icon').classList.remove('bg-primary', 'border-primary');
            element.querySelector('.pc-check-icon svg').classList.add('opacity-0');
            element.querySelector('.pc-check-overlay').classList.remove('bg-primary/20');
            element.querySelector('.pc-badge').classList.add('hidden');
        } else {
            if (this.selected.size >= this.maxSelect) {
                this.showToast(`最多只能选择 ${this.maxSelect} 张照片`);
                return;
            }
            this.selected.add(id);
            element.classList.remove('border-gray-200');
            element.classList.add('border-primary', 'ring-2', 'ring-primary/30');
            element.querySelector('.pc-check-icon').classList.add('bg-primary', 'border-primary');
            element.querySelector('.pc-check-icon svg').classList.remove('opacity-0');
            element.querySelector('.pc-check-overlay').classList.add('bg-primary/20');
        }
        this.updateBadges();
        this.updateUI();
    }

    updateBadges() {
        let index = 1;
        this.selected.forEach(id => {
            const item = this.container.querySelector(`.pc-photo-item[data-photo-id="${id}"]`);
            if (item) {
                const badge = item.querySelector('.pc-badge');
                badge.textContent = index;
                badge.classList.remove('hidden');
                index++;
            }
        });
    }

    updateUI() {
        this.container.querySelector('.pc-count').textContent = this.selected.size;
        const confirmBtn = this.container.querySelector('.pc-confirm-btn');
        confirmBtn.disabled = this.selected.size < this.minSelect;
    }

    showToast(msg) {
        if (typeof Swal !== 'undefined') {
            const Toast = Swal.mixin({ toast: true, position: 'top', showConfirmButton: false, timer: 2000 });
            Toast.fire({ icon: 'warning', title: msg });
        } else {
            alert(msg);
        }
    }

    destroy() {
        this.container.innerHTML = '';
        document.body.style.overflow = '';
        this.onCancel();
    }
}

if (typeof window !== 'undefined') {
    window.PhotoSelector = PhotoSelector;
}
