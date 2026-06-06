class HistogramAnalyzer {
    constructor() {
        this.bins = 256;
    }

    computeHistogram(photoData) {
        if (!photoData.imageData) {
            return { r: new Array(this.bins).fill(0), g: new Array(this.bins).fill(0), b: new Array(this.bins).fill(0) };
        }
        const r = new Array(this.bins).fill(0);
        const g = new Array(this.bins).fill(0);
        const b = new Array(this.bins).fill(0);
        const data = photoData.imageData.data;
        const total = data.length / 4;
        for (let i = 0; i < total; i++) {
            const idx = i * 4;
            r[data[idx]]++;
            g[data[idx + 1]]++;
            b[data[idx + 2]]++;
        }
        return { r, g, b, totalPixels: total };
    }

    renderToCanvas(histogram, canvas, colors = { r: '#ef4444', g: '#22c55e', b: '#3b82f6' }) {
        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;
        ctx.clearRect(0, 0, w, h);

        const maxVal = Math.max(
            Math.max.apply(null, histogram.r),
            Math.max.apply(null, histogram.g),
            Math.max.apply(null, histogram.b)
        ) || 1;

        const barWidth = w / this.bins;

        ctx.fillStyle = colors.b + '40';
        this._drawChannel(ctx, histogram.b, barWidth, h, maxVal, colors.b);

        ctx.fillStyle = colors.g + '40';
        this._drawChannel(ctx, histogram.g, barWidth, h, maxVal, colors.g);

        ctx.fillStyle = colors.r + '40';
        this._drawChannel(ctx, histogram.r, barWidth, h, maxVal, colors.r);
    }

    _drawChannel(ctx, data, barWidth, h, maxVal, color) {
        ctx.fillStyle = color;
        for (let i = 0; i < data.length; i++) {
            const barH = (data[i] / maxVal) * h;
            ctx.globalAlpha = 0.6;
            ctx.fillRect(i * barWidth, h - barH, barWidth + 0.5, barH);
        }
        ctx.globalAlpha = 1;
    }

    renderMultiToCanvas(histograms, canvas, labels) {
        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;
        ctx.clearRect(0, 0, w, h);

        const colors = [
            { r: '#ef4444', g: '#22c55e', b: '#3b82f6' },
            { r: '#f59e0b', g: '#06b6d4', b: '#a855f7' },
            { r: '#ec4899', g: '#84cc16', b: '#6366f1' },
            { r: '#14b8a6', g: '#f97316', b: '#8b5cf6' }
        ];

        const numPhotos = histograms.length;
        const panelH = h / numPhotos;

        for (let p = 0; p < numPhotos; p++) {
            const hist = histograms[p];
            const panelY = p * panelH;
            const c = colors[p % colors.length];

            ctx.fillStyle = '#f8fafc';
            ctx.fillRect(0, panelY, w, panelH - 1);

            if (labels && labels[p]) {
                ctx.fillStyle = '#64748b';
                ctx.font = '10px sans-serif';
                ctx.fillText(labels[p], 4, panelY + 12);
            }

            const maxVal = Math.max(
                Math.max.apply(null, hist.r),
                Math.max.apply(null, hist.g),
                Math.max.apply(null, hist.b)
            ) || 1;

            const barWidth = w / this.bins;
            const drawPanelH = panelH - 16;
            const drawPanelY = panelY + 16;

            this._drawChannelInPanel(ctx, hist.b, barWidth, drawPanelH, drawPanelY, maxVal, c.b);
            this._drawChannelInPanel(ctx, hist.g, barWidth, drawPanelH, drawPanelY, maxVal, c.g);
            this._drawChannelInPanel(ctx, hist.r, barWidth, drawPanelH, drawPanelY, maxVal, c.r);
        }
    }

    _drawChannelInPanel(ctx, data, barWidth, panelH, panelY, maxVal, color) {
        ctx.fillStyle = color;
        for (let i = 0; i < data.length; i++) {
            const barH = (data[i] / maxVal) * panelH;
            ctx.globalAlpha = 0.5;
            ctx.fillRect(i * barWidth, panelY + panelH - barH, barWidth + 0.5, barH);
        }
        ctx.globalAlpha = 1;
    }
}

if (typeof window !== 'undefined') {
    window.HistogramAnalyzer = HistogramAnalyzer;
}
