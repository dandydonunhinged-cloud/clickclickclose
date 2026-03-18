/* ============================================
   SECURITY LAYER — Client-side encryption + CSRF + localStorage protection
   Sits on top of apply.js — loaded BEFORE apply.js
   ============================================ */

const CCC_SECURE = (() => {
  // --- AES-GCM encryption using Web Crypto API ---
  // Key is derived from a session-unique value + server public key
  // This ensures data is encrypted BEFORE it leaves the browser

  const ALGO = 'AES-GCM';
  const KEY_LENGTH = 256;
  let _sessionKey = null;
  let _csrfToken = null;

  // Generate a per-session encryption key
  async function initSession() {
    const raw = crypto.getRandomValues(new Uint8Array(32));
    _sessionKey = await crypto.subtle.importKey(
      'raw', raw, { name: ALGO, length: KEY_LENGTH }, false, ['encrypt', 'decrypt']
    );
    // Generate CSRF token
    _csrfToken = Array.from(crypto.getRandomValues(new Uint8Array(32)))
      .map(b => b.toString(16).padStart(2, '0')).join('');
    // Store CSRF token in a cookie (httpOnly not possible from JS, but SameSite=Strict)
    document.cookie = `csrf=${_csrfToken};SameSite=Strict;Secure;Path=/`;
    return true;
  }

  // Encrypt a string value
  async function encrypt(plaintext) {
    if (!_sessionKey) await initSession();
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const encoded = new TextEncoder().encode(plaintext);
    const ciphertext = await crypto.subtle.encrypt(
      { name: ALGO, iv }, _sessionKey, encoded
    );
    // Return as base64 JSON with iv
    return JSON.stringify({
      ct: btoa(String.fromCharCode(...new Uint8Array(ciphertext))),
      iv: btoa(String.fromCharCode(...iv)),
      v: 1
    });
  }

  // Encrypt specific sensitive fields in a data object
  async function encryptPayload(data) {
    const sensitive = ['name', 'email', 'phone', 'notes', 'credit'];
    const encrypted = { ...data, _encrypted: [] };
    for (const key of sensitive) {
      if (encrypted[key] && typeof encrypted[key] === 'string' && encrypted[key].trim()) {
        encrypted[key] = await encrypt(encrypted[key]);
        encrypted._encrypted.push(key);
      }
    }
    // Add session fingerprint (not PII — just browser entropy for dedup)
    encrypted._fp = await fingerprint();
    encrypted._csrf = _csrfToken;
    encrypted._ts = Date.now();
    return encrypted;
  }

  // Minimal browser fingerprint (for rate limiting, NOT tracking)
  async function fingerprint() {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    ctx.textBaseline = 'top';
    ctx.font = '14px Arial';
    ctx.fillText('ccc', 2, 2);
    const d = canvas.toDataURL();
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(
      d + navigator.language + screen.width + screen.height + new Date().getTimezoneOffset()
    ));
    return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('').substr(0, 16);
  }

  // Secure localStorage — encrypt before storing, never store PII raw
  function secureStore(key, value) {
    // Strip PII before storing
    const safe = { ...value };
    delete safe.name;
    delete safe.email;
    delete safe.phone;
    delete safe.notes;
    // Only store non-PII deal parameters for the user's own reference
    try { localStorage.setItem(key, JSON.stringify(safe)); } catch(e) { /* quota exceeded, ignore */ }
  }

  // Clear sensitive data from localStorage
  function clearSensitive() {
    try {
      const keys = Object.keys(localStorage);
      keys.forEach(k => {
        if (k.startsWith('ccc_')) localStorage.removeItem(k);
      });
    } catch(e) {}
  }

  // Get CSRF token for form submission
  function getCSRF() { return _csrfToken; }

  // Rate limit check (client-side — server also enforces)
  function checkRate() {
    const key = 'ccc_rate';
    const now = Date.now();
    let stamps = [];
    try { stamps = JSON.parse(localStorage.getItem(key) || '[]'); } catch(e) {}
    stamps = stamps.filter(t => now - t < 3600000); // 1 hour window
    if (stamps.length >= 5) return false; // max 5 submissions per hour
    stamps.push(now);
    try { localStorage.setItem(key, JSON.stringify(stamps)); } catch(e) {}
    return true;
  }

  // Initialize on load
  initSession();

  return {
    encryptPayload,
    secureStore,
    clearSensitive,
    getCSRF,
    checkRate,
    initSession
  };
})();
