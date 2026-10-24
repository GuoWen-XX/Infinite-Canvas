(function(){
    const VERSION = '2026.09.23.1015';
    const scripts = [
        '/static/js/i18n-core.js',
        '/static/js/i18n/common.js',
        '/static/js/i18n/studio.js',
        '/static/js/i18n/api-settings.js',
        '/static/js/i18n/canvas.js',
        '/static/js/i18n/smart-canvas.js',
        '/static/js/i18n/comfyui-settings.js',
    ];
    let loadedCount = 0;
    const total = scripts.length;

    scripts.forEach(src => {
        const script = document.createElement('script');
        script.src = src + '?v=' + VERSION;
        script.async = false;
        script.onload = () => {
            loadedCount++;
            if(loadedCount === total){
                window.StudioI18n?.apply?.();
            }
        };
        script.onerror = (err) => console.error('Failed to load i18n module:', src, err);
        document.head.appendChild(script);
    });
})();
