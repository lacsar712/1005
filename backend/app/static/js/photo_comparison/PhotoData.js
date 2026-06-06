class PhotoData {
    constructor(id, url, originalFilename, exif = {}) {
        this.id = id;
        this.url = url;
        this.originalFilename = originalFilename;
        this.exif = exif;
        this.image = null;
        this.canvas = null;
        this.imageData = null;
        this.loaded = false;
    }

    async load() {
        if (this.loaded) return this;
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.crossOrigin = 'anonymous';
            img.onload = () => {
                this.image = img;
                this.canvas = document.createElement('canvas');
                this.canvas.width = img.naturalWidth;
                this.canvas.height = img.naturalHeight;
                const ctx = this.canvas.getContext('2d');
                ctx.drawImage(img, 0, 0);
                try {
                    this.imageData = ctx.getImageData(0, 0, this.canvas.width, this.canvas.height);
                } catch (e) {
                    console.warn('无法获取 ImageData（可能是跨域问题）:', e);
                    this.imageData = null;
                }
                this.loaded = true;
                resolve(this);
            };
            img.onerror = (e) => reject(e);
            img.src = this.url;
        });
    }

    get width() {
        return this.image ? this.image.naturalWidth : 0;
    }

    get height() {
        return this.image ? this.image.naturalHeight : 0;
    }

    getPixel(x, y) {
        if (!this.imageData) return null;
        const idx = (y * this.width + x) * 4;
        return {
            r: this.imageData.data[idx],
            g: this.imageData.data[idx + 1],
            b: this.imageData.data[idx + 2],
            a: this.imageData.data[idx + 3]
        };
    }

    getExifDisplay() {
        const labels = {
            camera_model: '相机型号',
            taken_at: '拍摄时间',
            gps_latitude: 'GPS 纬度',
            gps_longitude: 'GPS 经度',
            image_format: '图片格式',
            uploaded_at: '上传时间'
        };
        const result = {};
        for (const key in this.exif) {
            if (this.exif[key] != null && this.exif[key] !== '') {
                result[labels[key] || key] = this.exif[key];
            }
        }
        return result;
    }
}

if (typeof window !== 'undefined') {
    window.PhotoData = PhotoData;
}
