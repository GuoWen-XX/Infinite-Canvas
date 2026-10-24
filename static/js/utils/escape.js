/**
 * Infinite-Canvas Unified HTML & URL Sanitization Utilities
 */
(function (global) {
    'use strict';

    var HTML_ESCAPE_MAP = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    };

    /**
     * Escape HTML special characters to prevent DOM XSS.
     * @param {*} str - Input string or value
     * @returns {string} Safe escaped HTML string
     */
    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str).replace(/[&<>"']/g, function (s) {
            return HTML_ESCAPE_MAP[s] || s;
        });
    }

    /**
     * Escape attribute value for safe HTML insertion.
     * @param {*} str - Input string or value
     * @returns {string} Safe escaped attribute string
     */
    function escapeAttr(str) {
        return escapeHtml(str);
    }

    /**
     * Sanitize and validate image/media URLs for safe DOM attribute injection (e.g. img src).
     * Only allows http, https, data:image/, blob, or safe relative paths (/assets/, /output/, etc.).
     * Blocks javascript:, vbscript:, data:text/html, etc.
     * @param {*} url - Raw candidate URL
     * @param {string} fallback - Fallback URL if invalid
     * @returns {string} Safe URL or fallback
     */
    function safeMediaUrl(url, fallback) {
        if (!url || typeof url !== 'string') return fallback || '';
        var trimmed = url.trim();
        if (!trimmed) return fallback || '';
        // Relative safe paths
        if (trimmed.startsWith('/') && !trimmed.startsWith('//')) {
            return escapeHtml(trimmed);
        }
        // Safe data URLs (strictly images/media)
        if (/^data:image\/(png|jpe?g|webp|gif|svg\+xml);base64,/i.test(trimmed)) {
            return trimmed;
        }
        // Safe blob URLs
        if (/^blob:/i.test(trimmed)) {
            return escapeHtml(trimmed);
        }
        // HTTP/HTTPS URLs
        try {
            var origin = (typeof window !== 'undefined' && window.location) ? window.location.origin : 'http://localhost';
            var parsed = new URL(trimmed, origin);
            if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
                return escapeHtml(trimmed);
            }
        } catch (e) {}
        return fallback || '';
    }

    /**
     * Generate unique identifier.
     * @param {string} prefix - Optional prefix (defaults to 'n')
     * @returns {string} Unique ID
     */
    function uid(prefix) {
        return (prefix || 'n') + '_' + Math.random().toString(16).slice(2) + '_' + Date.now();
    }

    global.StudioEscape = { escapeHtml: escapeHtml, escapeAttr: escapeAttr, safeMediaUrl: safeMediaUrl, uid: uid };
    global.escapeHtml = global.escapeHtml || escapeHtml;
    global.escapeAttr = global.escapeAttr || escapeAttr;
    global.safeMediaUrl = global.safeMediaUrl || safeMediaUrl;
    global.uid = global.uid || uid;

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = { escapeHtml: escapeHtml, escapeAttr: escapeAttr, safeMediaUrl: safeMediaUrl, uid: uid };
    }
})(typeof window !== 'undefined' ? window : globalThis);

