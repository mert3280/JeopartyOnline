/* JeoParty visual effects: loading overlay, get-ready flash, confetti.
   Exposes window.Effects with showLoading/hideLoading/flash/confetti. */
(() => {
  function getThemeColors() {
    const cs = getComputedStyle(document.documentElement);
    return [
      cs.getPropertyValue('--accent-a').trim(),
      cs.getPropertyValue('--accent-b').trim(),
      cs.getPropertyValue('--accent-c').trim(),
      cs.getPropertyValue('--accent-d').trim(),
      cs.getPropertyValue('--accent-e').trim(),
      cs.getPropertyValue('--accent-f').trim(),
      '#ffffff',
    ].filter(Boolean);
  }

  // ---------- Loading overlay ----------

  function ensureLoadingEl() {
    let el = document.getElementById('global-loading');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'global-loading';
    el.className = 'loading-screen';
    el.innerHTML = `
      <div class="brand">JeoParty</div>
      <div class="loading-dots"><span></span><span></span><span></span></div>
      <div class="message" id="global-loading-message">Loading…</div>
    `;
    el.hidden = true;
    document.body.appendChild(el);
    return el;
  }

  function showLoading(message) {
    const el = ensureLoadingEl();
    el.classList.remove('fade-out');
    const m = document.getElementById('global-loading-message');
    if (m) m.textContent = message || 'Loading…';
    el.hidden = false;
  }

  function hideLoading() {
    const el = document.getElementById('global-loading');
    if (!el || el.hidden) return;
    el.classList.add('fade-out');
    setTimeout(() => {
      el.hidden = true;
      el.classList.remove('fade-out');
    }, 300);
  }

  // ---------- Flash transition ("Get Ready!") ----------

  function flash(message, durationMs) {
    durationMs = durationMs || 1200;
    const el = document.createElement('div');
    el.className = 'flash-screen';
    el.innerHTML = `<div class="flash-message">${escapeHtml(message)}</div>`;
    document.body.appendChild(el);
    setTimeout(() => {
      el.classList.add('fade-out');
      setTimeout(() => el.remove(), 300);
    }, durationMs);
  }

  // ---------- Confetti ----------

  let confettiActive = false;

  function confetti(durationMs) {
    durationMs = durationMs || 5000;
    if (confettiActive) return;
    confettiActive = true;

    let canvas = document.querySelector('.confetti-canvas');
    if (!canvas) {
      canvas = document.createElement('canvas');
      canvas.className = 'confetti-canvas';
      document.body.appendChild(canvas);
    }
    const ctx = canvas.getContext('2d');

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    }
    resize();
    window.addEventListener('resize', resize);

    const colors = getThemeColors();
    const pieces = [];
    const pieceCount = 180;

    for (let i = 0; i < pieceCount; i++) {
      pieces.push({
        x: Math.random() * canvas.width,
        y: -20 - Math.random() * canvas.height * 0.5,
        w: 6 + Math.random() * 10,
        h: 10 + Math.random() * 14,
        vy: 2 + Math.random() * 3.5,
        vx: -1.5 + Math.random() * 3,
        rot: Math.random() * Math.PI * 2,
        vr: -0.15 + Math.random() * 0.3,
        color: colors[Math.floor(Math.random() * colors.length)],
        shape: Math.random() < 0.4 ? 'circle' : 'rect',
      });
    }

    const startTs = performance.now();
    let stopping = false;

    function tick(now) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const elapsed = now - startTs;
      if (!stopping && elapsed > durationMs) stopping = true;

      let alive = 0;
      for (const p of pieces) {
        p.x += p.vx;
        p.y += p.vy;
        p.rot += p.vr;
        p.vy += 0.04; // gravity

        if (p.y < canvas.height + 40) alive++;

        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.rotate(p.rot);
        ctx.fillStyle = p.color;
        if (p.shape === 'circle') {
          ctx.beginPath();
          ctx.arc(0, 0, p.w / 2, 0, Math.PI * 2);
          ctx.fill();
        } else {
          ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
        }
        ctx.restore();
      }

      if (stopping && alive === 0) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        confettiActive = false;
        window.removeEventListener('resize', resize);
        return;
      }
      requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  window.Effects = { showLoading, hideLoading, flash, confetti };
})();
