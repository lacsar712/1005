class ExifDiffAnalyzer {
    constructor() {
        this.fieldLabels = {
            camera_model: '相机型号',
            taken_at: '拍摄时间',
            uploaded_at: '上传时间',
            gps_latitude: 'GPS 纬度',
            gps_longitude: 'GPS 经度',
            image_format: '图片格式',
            original_filename: '原始文件名'
        };
    }

    getFieldLabel(key) {
        return this.fieldLabels[key] || key;
    }

    normalizeValue(val) {
        if (val == null) return '';
        if (val instanceof Date) return val.toISOString();
        if (typeof val === 'number') {
            if (Number.isFinite(val)) {
                return val.toFixed(6);
            }
            return String(val);
        }
        return String(val).trim();
    }

    diffTwo(photoA, photoB) {
        const allKeys = new Set([
            ...Object.keys(photoA.exif || {}),
            ...Object.keys(photoB.exif || {}),
            'original_filename'
        ]);
        const diffs = [];

        allKeys.forEach(key => {
            const a = this.normalizeValue(key === 'original_filename' ? photoA.originalFilename : photoA.exif?.[key]);
            const b = this.normalizeValue(key === 'original_filename' ? photoB.originalFilename : photoB.exif?.[key]);
            if (a !== b) {
                diffs.push({
                    field: this.getFieldLabel(key),
                    key,
                    valueA: a || '—',
                    valueB: b || '—'
                });
            }
        });

        return diffs;
    }

    diffMultiple(photos) {
        if (photos.length < 2) return [];
        const allKeys = new Set();
        photos.forEach(p => {
            Object.keys(p.exif || {}).forEach(k => allKeys.add(k));
            allKeys.add('original_filename');
        });

        const diffs = [];
        allKeys.forEach(key => {
            const values = photos.map(p =>
                this.normalizeValue(key === 'original_filename' ? p.originalFilename : p.exif?.[key]) || '—'
            );
            const unique = [...new Set(values)];
            if (unique.length > 1) {
                diffs.push({
                    field: this.getFieldLabel(key),
                    key,
                    values: values
                });
            }
        });

        return diffs;
    }

    renderDiffList(photos, container) {
        container.innerHTML = '';
        const diffs = this.diffMultiple(photos);

        if (diffs.length === 0) {
            container.innerHTML = `
                <div class="text-center text-gray-400 text-sm py-6">
                    <svg class="w-8 h-8 mx-auto mb-2 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                    </svg>
                    所有 EXIF 字段均相同
                </div>
            `;
            return;
        }

        const headerRow = photos.map((p, i) => `
            <div class="font-medium text-gray-700 text-xs truncate px-2 py-1" title="${p.originalFilename}">
                图${i + 1}: ${p.originalFilename.substring(0, 15)}${p.originalFilename.length > 15 ? '...' : ''}
            </div>
        `).join('');

        const rows = diffs.map(d => {
            const valueCells = d.values.map(v => `
                <div class="text-xs text-gray-600 px-2 py-1 break-all">${v}</div>
            `).join('');
            return `
                <div class="border-t border-gray-100 grid gap-1 items-start" style="grid-template-columns: 100px repeat(${photos.length}, minmax(0, 1fr));">
                    <div class="font-medium text-primary text-xs px-2 py-1">${d.field}</div>
                    ${valueCells}
                </div>
            `;
        }).join('');

        container.innerHTML = `
            <div class="text-xs text-gray-500 mb-2 flex items-center">
                <svg class="w-3.5 h-3.5 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"></path>
                </svg>
                共 ${diffs.length} 项差异
            </div>
            <div class="border border-gray-200 rounded-lg overflow-hidden bg-white">
                <div class="bg-gray-50 grid gap-1 border-b border-gray-200" style="grid-template-columns: 100px repeat(${photos.length}, minmax(0, 1fr));">
                    <div class="font-semibold text-gray-600 text-xs px-2 py-2">字段</div>
                    ${headerRow}
                </div>
                ${rows}
            </div>
        `;
    }
}

if (typeof window !== 'undefined') {
    window.ExifDiffAnalyzer = ExifDiffAnalyzer;
}
