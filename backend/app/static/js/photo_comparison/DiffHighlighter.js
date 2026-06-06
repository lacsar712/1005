class DiffHighlighter {
    constructor(threshold = 30) {
        this.threshold = threshold;
        this.diffCanvas = null;
    }

    sameDimensions(photoA, photoB) {
        return photoA.width === photoB.width && photoA.height === photoB.height;
    }

    async computeDiff(photoA, photoB) {
        if (!photoA.imageData || !photoB.imageData) {
            throw new Error('照片未完全加载，无法计算差异');
        }
        if (!this.sameDimensions(photoA, photoB)) {
            throw new Error('两张照片尺寸不同，无法逐像素对比');
        }

        const w = photoA.width;
        const h = photoA.height;
        this.diffCanvas = document.createElement('canvas');
        this.diffCanvas.width = w;
        this.diffCanvas.height = h;
        const ctx = this.diffCanvas.getContext('2d');
        const outData = ctx.createImageData(w, h);

        const dataA = photoA.imageData.data;
        const dataB = photoB.imageData.data;
        let diffPixelCount = 0;
        const totalPixels = w * h;

        if (typeof OffscreenCanvas !== 'undefined' && typeof Worker !== 'undefined') {
            return this._computeDiffWorker(photoA, photoB);
        }

        for (let i = 0; i < totalPixels; i++) {
            const idx = i * 4;
            const rA = dataA[idx], gA = dataA[idx + 1], bA = dataA[idx + 2];
            const rB = dataB[idx], gB = dataB[idx + 1], bB = dataB[idx + 2];
            const delta = Math.abs(rA - rB) + Math.abs(gA - gB) + Math.abs(bA - bB);

            outData.data[idx] = 0;
            outData.data[idx + 1] = 0;
            outData.data[idx + 2] = 0;
            outData.data[idx + 3] = 0;

            if (delta > this.threshold) {
                outData.data[idx] = 239;
                outData.data[idx + 1] = 68;
                outData.data[idx + 2] = 68;
                outData.data[idx + 3] = 140;
                diffPixelCount++;
            }
        }

        ctx.putImageData(outData, 0, 0);
        return {
            canvas: this.diffCanvas,
            diffPixelCount,
            totalPixels,
            diffPercent: ((diffPixelCount / totalPixels) * 100).toFixed(2)
        };
    }

    _computeDiffWorker(photoA, photoB) {
        return new Promise((resolve) => {
            const w = photoA.width;
            const h = photoB.height;
            const totalPixels = w * h;

            const workerCode = `
                self.onmessage = function(e) {
                    const { dataA, dataB, width, height, threshold } = e.data;
                    const totalPixels = width * height;
                    const out = new Uint8ClampedArray(totalPixels * 4);
                    let diffCount = 0;
                    for (let i = 0; i < totalPixels; i++) {
                        const idx = i * 4;
                        const dR = Math.abs(dataA[idx] - dataB[idx]);
                        const dG = Math.abs(dataA[idx + 1] - dataB[idx + 1]);
                        const dB = Math.abs(dataA[idx + 2] - dataB[idx + 2]);
                        const delta = dR + dG + dB;
                        if (delta > threshold) {
                            out[idx] = 239;
                            out[idx + 1] = 68;
                            out[idx + 2] = 68;
                            out[idx + 3] = 140;
                            diffCount++;
                        }
                    }
                    self.postMessage({ out, diffCount }, [out.buffer]);
                };
            `;
            const blob = new Blob([workerCode], { type: 'application/javascript' });
            const workerUrl = URL.createObjectURL(blob);
            const worker = new Worker(workerUrl);

            worker.onmessage = (e) => {
                const { out, diffCount } = e.data;
                this.diffCanvas = document.createElement('canvas');
                this.diffCanvas.width = w;
                this.diffCanvas.height = h;
                const ctx = this.diffCanvas.getContext('2d');
                const imgData = new ImageData(new Uint8ClampedArray(out), w, h);
                ctx.putImageData(imgData, 0, 0);
                URL.revokeObjectURL(workerUrl);
                worker.terminate();
                resolve({
                    canvas: this.diffCanvas,
                    diffPixelCount: diffCount,
                    totalPixels,
                    diffPercent: ((diffCount / totalPixels) * 100).toFixed(2)
                });
            };

            worker.postMessage({
                dataA: new Uint8ClampedArray(photoA.imageData.data),
                dataB: new Uint8ClampedArray(photoB.imageData.data),
                width: w,
                height: h,
                threshold: this.threshold
            });
        });
    }

    setThreshold(threshold) {
        this.threshold = threshold;
    }
}

if (typeof window !== 'undefined') {
    window.DiffHighlighter = DiffHighlighter;
}
