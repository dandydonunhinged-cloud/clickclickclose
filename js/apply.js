/* ============================================
   UNIVERSAL DEAL FORM — LOGIC
   Conditional fields, validation, DSCR calc, submission
   ============================================ */
document.addEventListener('DOMContentLoaded', () => {
  const F = document.getElementById('deal-form');
  if (!F) return;

  const steps = F.querySelectorAll('.step');
  const pSteps = document.querySelectorAll('.progress-step');
  let cur = 0;
  let loanType = '';

  // --- Step navigation ---
  function go(i) {
    steps.forEach((s, idx) => { s.classList.toggle('active', idx === i); });
    pSteps.forEach((p, idx) => {
      p.classList.remove('active', 'done');
      if (idx < i) p.classList.add('done');
      if (idx === i) p.classList.add('active');
    });
    cur = i;
    F.closest('.form-card').scrollIntoView({ behavior:'smooth', block:'start' });
  }

  F.querySelectorAll('[data-go="next"]').forEach(b => b.addEventListener('click', () => { if (validate(cur)) go(cur + 1); }));
  F.querySelectorAll('[data-go="back"]').forEach(b => b.addEventListener('click', () => go(cur - 1)));

  // --- Loan type selection ---
  F.querySelectorAll('.type-card').forEach(card => {
    card.addEventListener('click', () => {
      F.querySelectorAll('.type-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      card.querySelector('input').checked = true;
      loanType = card.querySelector('input').value;
      morph(loanType);
    });
  });

  // --- Morph: show/hide conditional sections ---
  function morph(type) {
    // Hide all conditional
    F.querySelectorAll('.cond').forEach(el => el.classList.remove('show'));
    // Show matching
    F.querySelectorAll(`[data-show~="${type}"]`).forEach(el => el.classList.add('show'));
    // Show "all" conditionals
    F.querySelectorAll('[data-show~="all"]').forEach(el => el.classList.add('show'));
    // DSCR calc
    const dc = F.querySelector('.dscr-calc');
    if (dc) dc.classList.toggle('show', type === 'dscr' || type === 'str' || type === 'portfolio');
  }

  // --- Radio/checkbox options ---
  F.querySelectorAll('.opt').forEach(opt => {
    opt.addEventListener('click', () => {
      const inp = opt.querySelector('input');
      if (inp.type === 'radio') {
        opt.closest('.opt-group').querySelectorAll('.opt').forEach(o => o.classList.remove('selected'));
        opt.classList.add('selected');
        inp.checked = true;
      } else {
        opt.classList.toggle('selected');
        inp.checked = !inp.checked;
      }
    });
  });

  // --- DSCR Calculator ---
  function calcDSCR() {
    const rent = parseFloat(F.querySelector('#rent')?.value) || 0;
    const price = parseFloat(F.querySelector('#value')?.value?.replace(/,/g,'')) || 0;
    const dp = parseFloat(F.querySelector('#down')?.value) || 20;
    const dv = F.querySelector('.dscr-val');
    const vd = F.querySelector('.dscr-verdict');
    if (!dv) return;
    if (rent <= 0 || price <= 0) { dv.textContent = '--'; dv.className = 'dscr-val'; if(vd) vd.textContent=''; return; }
    const loan = price * (1 - dp / 100);
    const mr = 0.075 / 12, n = 360;
    const pmt = loan * (mr * Math.pow(1+mr,n)) / (Math.pow(1+mr,n)-1);
    const ti = price * 0.015 / 12;
    const dscr = rent / (pmt + ti);
    dv.textContent = dscr.toFixed(2);
    dv.className = 'dscr-val ' + (dscr >= 1.25 ? 'good' : dscr >= 1.0 ? 'ok' : 'low');
    if(vd) vd.textContent = dscr >= 1.25 ? 'Strong — qualifies with most lenders' : dscr >= 1.0 ? 'Acceptable — options available' : dscr >= 0.75 ? 'Below 1.0 — limited options, higher rate' : 'Low — may need more down payment';
  }
  ['#rent','#value','#down'].forEach(sel => { const el = F.querySelector(sel); if(el) el.addEventListener('input', calcDSCR); });

  // --- Currency formatting ---
  F.querySelectorAll('.money').forEach(inp => {
    inp.addEventListener('blur', () => {
      let v = inp.value.replace(/[^0-9.]/g,'');
      if (v) { const n = parseFloat(v); if(!isNaN(n)) inp.value = n.toLocaleString('en-US'); }
    });
    inp.addEventListener('focus', () => { inp.value = inp.value.replace(/,/g,''); });
  });

  // --- Phone formatting ---
  F.querySelectorAll('input[type="tel"]').forEach(inp => {
    inp.addEventListener('input', () => {
      let v = inp.value.replace(/\D/g,'');
      if (v.length > 10) v = v.substr(0,10);
      if (v.length >= 7) v = `(${v.substr(0,3)}) ${v.substr(3,3)}-${v.substr(6)}`;
      else if (v.length >= 4) v = `(${v.substr(0,3)}) ${v.substr(3)}`;
      inp.value = v;
    });
  });

  // --- Validation ---
  function validate(step) {
    const s = steps[step];
    let ok = true;
    // Step 0: must pick loan type
    if (step === 0 && !loanType) { alert('Select a loan type.'); return false; }
    // Required fields in visible sections only
    s.querySelectorAll('.fc[required]').forEach(f => {
      const wrap = f.closest('.cond');
      if (wrap && !wrap.classList.contains('show')) return; // skip hidden conditional
      f.classList.remove('err');
      const em = f.parentElement.querySelector('.err-msg');
      if (!f.value.trim()) { f.classList.add('err'); if(em) em.style.display='block'; ok = false; }
      else { if(em) em.style.display='none'; }
    });
    // Email check
    const em = s.querySelector('input[type="email"]');
    if (em && em.value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(em.value)) { em.classList.add('err'); ok = false; }
    // Phone check
    const ph = s.querySelector('input[type="tel"]');
    if (ph && ph.value && ph.value.replace(/\D/g,'').length < 10) { ph.classList.add('err'); ok = false; }
    if (!ok) { const first = s.querySelector('.fc.err'); if(first) first.focus(); }
    return ok;
  }

  // --- Submission ---
  F.addEventListener('submit', e => {
    e.preventDefault();
    if (!validate(cur)) return;
    const data = { loanType, timestamp: new Date().toISOString() };
    F.querySelectorAll('.fc, input[type="radio"]:checked, input[type="checkbox"]:checked').forEach(f => {
      if (!f.name) return;
      const wrap = f.closest('.cond');
      if (wrap && !wrap.classList.contains('show')) return;
      if (f.type === 'radio' || f.type === 'checkbox') { if(f.checked) data[f.name] = f.value; }
      else data[f.name] = f.value;
    });
    // Save locally
    const subs = JSON.parse(localStorage.getItem('ccc_deals') || '[]');
    subs.push(data);
    localStorage.setItem('ccc_deals', JSON.stringify(subs));

    // Submit to API
    const API = location.hostname === 'localhost'
      ? 'http://localhost:8081/api/submit-deal'
      : 'https://ccc-investor-api.onrender.com/api/submit-deal';
    const btn = F.querySelector('.btn-submit');
    if (btn) { btn.disabled = true; btn.textContent = 'Analyzing your deal...'; }

    fetch(API, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) })
      .then(r => r.json())
      .then(res => { showResult(res.report || null); })
      .catch(() => { showResult(null); });
  });

  function showResult(report) {
    const card = F.closest('.form-card');
    if (report) {
      card.innerHTML = `<div class="success">
        <div class="success-icon">✓</div>
        <h2>Your Deal Analysis</h2>
        <div class="report-box">${report}</div>
        <p>A loan specialist will reach out within <strong style="color:var(--gold)">15 minutes</strong> during business hours.</p>
        <a href="index.html" class="btn-next" style="margin-right:0.5rem">Home</a>
        <a href="apply.html" class="btn-back">Submit Another</a>
      </div>`;
    } else {
      card.innerHTML = `<div class="success">
        <div class="success-icon">✓</div>
        <h2>Deal Submitted</h2>
        <p>We've received your deal. A loan specialist will review it and reach out within <strong style="color:var(--gold)">15 minutes</strong> during business hours.</p>
        <a href="index.html" class="btn-next" style="margin-right:0.5rem">Home</a>
        <a href="apply.html" class="btn-back">Submit Another</a>
      </div>`;
    }
    // Mark all progress done
    pSteps.forEach(p => { p.classList.remove('active'); p.classList.add('done'); });
  }

  // Init
  go(0);
});
