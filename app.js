/* ============================================
   INVESTOR LOAN SORTING — APPLICATION JS
   Multi-step form, DSCR calc, FAQ, UI logic
   ============================================ */

document.addEventListener('DOMContentLoaded', () => {

  // --- Mobile Menu ---
  const mobileToggle = document.querySelector('.mobile-toggle');
  const mobileMenu = document.querySelector('.mobile-menu');
  if (mobileToggle && mobileMenu) {
    mobileToggle.addEventListener('click', () => {
      mobileToggle.classList.toggle('active');
      mobileMenu.classList.toggle('active');
      document.body.style.overflow = mobileMenu.classList.contains('active') ? 'hidden' : '';
    });
    mobileMenu.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', () => {
        mobileToggle.classList.remove('active');
        mobileMenu.classList.remove('active');
        document.body.style.overflow = '';
      });
    });
  }

  // --- Header scroll effect ---
  const header = document.querySelector('.header');
  if (header) {
    window.addEventListener('scroll', () => {
      header.classList.toggle('scrolled', window.scrollY > 20);
    });
  }

  // --- Smooth scroll for anchor links ---
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', (e) => {
      const target = document.querySelector(anchor.getAttribute('href'));
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });

  // --- Scroll Reveal ---
  const revealElements = document.querySelectorAll('.reveal');
  if (revealElements.length) {
    const revealObserver = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          revealObserver.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -50px 0px' });
    revealElements.forEach(el => revealObserver.observe(el));
  }

  // --- FAQ Accordion ---
  document.querySelectorAll('.faq-question').forEach(btn => {
    btn.addEventListener('click', () => {
      const item = btn.closest('.faq-item');
      const answer = item.querySelector('.faq-answer');
      const isActive = item.classList.contains('active');

      // Close all
      item.closest('.faq-list').querySelectorAll('.faq-item').forEach(fi => {
        fi.classList.remove('active');
        fi.querySelector('.faq-answer').style.maxHeight = '0';
      });

      // Open clicked if wasn't already open
      if (!isActive) {
        item.classList.add('active');
        answer.style.maxHeight = answer.scrollHeight + 'px';
      }
    });
  });

  // ============================================
  //  MULTI-STEP FORM LOGIC
  // ============================================
  const form = document.getElementById('deal-form');
  if (!form) return;

  const steps = form.querySelectorAll('.form-step');
  const progressSteps = document.querySelectorAll('.form-progress-step');
  let currentStep = 0;
  let selectedLoanType = '';
  let uploadedFiles = {};

  function showStep(index) {
    steps.forEach((s, i) => {
      s.classList.toggle('active', i === index);
    });
    progressSteps.forEach((ps, i) => {
      ps.classList.remove('active', 'completed');
      if (i < index) ps.classList.add('completed');
      if (i === index) ps.classList.add('active');
    });
    currentStep = index;
    form.querySelector('.form-body').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // Next / Back buttons
  form.querySelectorAll('[data-action="next"]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (validateCurrentStep()) {
        showStep(currentStep + 1);
      }
    });
  });
  form.querySelectorAll('[data-action="back"]').forEach(btn => {
    btn.addEventListener('click', () => {
      showStep(currentStep - 1);
    });
  });

  // --- Loan Type Selection ---
  const loanTypeOptions = form.querySelectorAll('.loan-type-option');
  loanTypeOptions.forEach(opt => {
    opt.addEventListener('click', () => {
      loanTypeOptions.forEach(o => o.classList.remove('selected'));
      opt.classList.add('selected');
      opt.querySelector('input').checked = true;
      selectedLoanType = opt.querySelector('input').value;
      adaptFormFields(selectedLoanType);
    });
  });

  // --- Adapt form fields based on loan type ---
  function adaptFormFields(loanType) {
    // Hide all conditional sections
    form.querySelectorAll('[data-loan-type]').forEach(el => {
      el.style.display = 'none';
    });

    // Show sections matching selected type
    form.querySelectorAll(`[data-loan-type~="${loanType}"]`).forEach(el => {
      el.style.display = '';
    });

    // Show sections that should always be visible
    form.querySelectorAll('[data-loan-type="all"]').forEach(el => {
      el.style.display = '';
    });

    // Toggle DSCR calculator visibility
    const dscrCalc = form.querySelector('.dscr-calculator');
    if (dscrCalc) {
      dscrCalc.style.display = (loanType === 'dscr' || loanType === 'str') ? '' : 'none';
    }
  }

  // --- Radio / Checkbox styled options ---
  form.querySelectorAll('.radio-option').forEach(opt => {
    opt.addEventListener('click', () => {
      const group = opt.closest('.radio-group');
      group.querySelectorAll('.radio-option').forEach(o => o.classList.remove('selected'));
      opt.classList.add('selected');
      opt.querySelector('input').checked = true;
    });
  });
  form.querySelectorAll('.checkbox-option').forEach(opt => {
    opt.addEventListener('click', () => {
      opt.classList.toggle('selected');
      const cb = opt.querySelector('input');
      cb.checked = !cb.checked;
    });
  });

  // --- DSCR Calculator ---
  const rentalIncomeInput = form.querySelector('#rental-income');
  const loanAmountInput = form.querySelector('#purchase-price');
  const dscrDisplay = form.querySelector('.dscr-value');

  function calculateDSCR() {
    if (!dscrDisplay) return;
    const rent = parseFloat((rentalIncomeInput || {}).value) || 0;
    const purchasePrice = parseFloat((loanAmountInput || {}).value) || 0;
    const downPaymentPct = parseFloat((form.querySelector('#down-payment') || {}).value) || 20;

    if (rent <= 0 || purchasePrice <= 0) {
      dscrDisplay.textContent = '--';
      dscrDisplay.className = 'dscr-value';
      return;
    }

    // Estimate monthly payment: assume 7.5% rate, 30yr, (price * (1 - dp%))
    const loanAmt = purchasePrice * (1 - downPaymentPct / 100);
    const monthlyRate = 0.075 / 12;
    const n = 360;
    const monthlyPayment = loanAmt * (monthlyRate * Math.pow(1 + monthlyRate, n)) / (Math.pow(1 + monthlyRate, n) - 1);

    // Add estimated taxes + insurance (~1.5% of price / 12)
    const monthlyTI = purchasePrice * 0.015 / 12;
    const totalMonthly = monthlyPayment + monthlyTI;

    const dscr = rent / totalMonthly;
    dscrDisplay.textContent = dscr.toFixed(2);

    dscrDisplay.className = 'dscr-value';
    if (dscr >= 1.25) dscrDisplay.classList.add('good');
    else if (dscr >= 1.0) dscrDisplay.classList.add('ok');
    else dscrDisplay.classList.add('low');

    // Update label
    const label = form.querySelector('.dscr-label');
    if (label) {
      if (dscr >= 1.25) label.textContent = 'Strong — qualifies with most lenders';
      else if (dscr >= 1.0) label.textContent = 'Acceptable — options available';
      else if (dscr >= 0.75) label.textContent = 'Below 1.0 — limited lender options, higher rates likely';
      else label.textContent = 'Low — may need more down payment or higher rent';
    }
  }

  if (rentalIncomeInput) rentalIncomeInput.addEventListener('input', calculateDSCR);
  if (loanAmountInput) loanAmountInput.addEventListener('input', calculateDSCR);
  const dpInput = form.querySelector('#down-payment');
  if (dpInput) dpInput.addEventListener('input', calculateDSCR);

  // --- File Upload with Drag & Drop ---
  form.querySelectorAll('.upload-zone').forEach(zone => {
    const input = zone.querySelector('input[type="file"]');
    const fileList = zone.parentElement.querySelector('.file-list');
    const category = zone.dataset.category || 'general';

    if (!uploadedFiles[category]) uploadedFiles[category] = [];

    zone.addEventListener('click', () => input.click());

    zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      zone.classList.add('dragover');
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('dragover');
      handleFiles(e.dataTransfer.files, category, fileList);
    });

    input.addEventListener('change', () => {
      handleFiles(input.files, category, fileList);
      input.value = '';
    });
  });

  function handleFiles(files, category, fileList) {
    if (!uploadedFiles[category]) uploadedFiles[category] = [];
    Array.from(files).forEach(file => {
      if (file.size > 25 * 1024 * 1024) {
        alert('File size must be under 25MB: ' + file.name);
        return;
      }
      uploadedFiles[category].push(file);
      renderFileList(category, fileList);
    });
  }

  function renderFileList(category, container) {
    if (!container) return;
    container.innerHTML = '';
    uploadedFiles[category].forEach((file, idx) => {
      const div = document.createElement('div');
      div.className = 'file-item';
      div.innerHTML = `
        <span class="file-name">${file.name}</span>
        <span class="file-size">${(file.size / 1024).toFixed(0)} KB</span>
        <button type="button" class="file-remove" data-cat="${category}" data-idx="${idx}">&times;</button>
      `;
      container.appendChild(div);
    });

    container.querySelectorAll('.file-remove').forEach(btn => {
      btn.addEventListener('click', () => {
        const cat = btn.dataset.cat;
        const idx = parseInt(btn.dataset.idx);
        uploadedFiles[cat].splice(idx, 1);
        renderFileList(cat, container);
      });
    });
  }

  // --- Form Validation ---
  function validateCurrentStep() {
    const step = steps[currentStep];
    let valid = true;

    // Step 0: Loan type required
    if (currentStep === 0 && !selectedLoanType) {
      alert('Please select a loan type to continue.');
      return false;
    }

    // Validate required fields in current step
    step.querySelectorAll('[required]').forEach(field => {
      // Skip hidden fields
      if (field.closest('[data-loan-type]') && field.closest('[data-loan-type]').style.display === 'none') {
        return;
      }
      field.classList.remove('error');
      const errorEl = field.parentElement.querySelector('.form-error');

      if (!field.value.trim()) {
        field.classList.add('error');
        if (errorEl) errorEl.style.display = 'block';
        valid = false;
      } else {
        if (errorEl) errorEl.style.display = 'none';
      }
    });

    // Email validation
    const emailField = step.querySelector('input[type="email"]');
    if (emailField && emailField.value) {
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      if (!emailRegex.test(emailField.value)) {
        emailField.classList.add('error');
        valid = false;
      }
    }

    // Phone validation
    const phoneField = step.querySelector('input[type="tel"]');
    if (phoneField && phoneField.value) {
      const digits = phoneField.value.replace(/\D/g, '');
      if (digits.length < 10) {
        phoneField.classList.add('error');
        valid = false;
      }
    }

    if (!valid) {
      const firstError = step.querySelector('.form-control.error');
      if (firstError) firstError.focus();
    }

    return valid;
  }

  // --- Form Submission ---
  form.addEventListener('submit', (e) => {
    e.preventDefault();

    if (!validateCurrentStep()) return;

    // Collect all form data
    const formData = {
      loanType: selectedLoanType,
      timestamp: new Date().toISOString(),
      property: {},
      borrower: {},
      loanDetails: {},
      contact: {},
      files: {}
    };

    // Gather all inputs
    form.querySelectorAll('input, select, textarea').forEach(field => {
      if (!field.name || field.type === 'file') return;
      // Skip hidden conditional fields
      const wrapper = field.closest('[data-loan-type]');
      if (wrapper && wrapper.style.display === 'none') return;

      if (field.type === 'radio') {
        if (field.checked) formData[field.name] = field.value;
      } else if (field.type === 'checkbox') {
        if (!formData[field.name]) formData[field.name] = [];
        if (field.checked) formData[field.name].push(field.value);
      } else {
        formData[field.name] = field.value;
      }
    });

    // Track uploaded files
    Object.keys(uploadedFiles).forEach(cat => {
      formData.files[cat] = uploadedFiles[cat].map(f => ({ name: f.name, size: f.size, type: f.type }));
    });

    // Store locally as backup
    const submissions = JSON.parse(localStorage.getItem('deal_submissions') || '[]');
    submissions.push(formData);
    localStorage.setItem('deal_submissions', JSON.stringify(submissions));

    // Submit to API
    const API_URL = window.location.hostname === 'localhost'
      ? 'http://localhost:8081/api/submit-deal'
      : 'https://ccc-investor-api.onrender.com/api/submit-deal';

    const submitBtn = form.querySelector('[type="submit"]');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = 'Analyzing your deal...';
    }

    fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(formData),
    })
    .then(res => res.json())
    .then(data => {
      if (data.report) {
        showSuccessWithReport(data.report);
      } else {
        showSuccess();
      }
    })
    .catch(err => {
      console.error('API error:', err);
      // Fallback — still show success since we saved locally
      showSuccess();
    });
  });

  function showSuccessWithReport(report) {
    const body = form.querySelector('.form-body');
    body.innerHTML = `
      <div style="text-align: center; padding: 3rem 1rem;">
        <div style="font-size: 4rem; margin-bottom: 1rem;">&#10003;</div>
        <h2 style="margin-bottom: 1rem; color: #1a2332;">Your Deal Analysis</h2>
        <div style="background: #f8f9fa; border-radius: 12px; padding: 2rem; max-width: 700px; margin: 0 auto 2rem; text-align: left; white-space: pre-wrap; font-size: 0.95rem; line-height: 1.7; color: #374151;">
          ${report}
        </div>
        <p style="color: #6b7280; font-size: 0.9rem; max-width: 500px; margin: 0 auto 2rem;">
          A loan specialist will reach out within <strong style="color: #d4a843;">15 minutes</strong> during business hours to discuss your options and next steps.
        </p>
        <a href="index.html" class="btn btn-primary" style="margin-right: 0.5rem;">Back to Home</a>
        <a href="submit.html" class="btn btn-outline">Submit Another Deal</a>
      </div>
    `;
    const progressBar = document.querySelector('.form-progress');
    if (progressBar) {
      progressBar.querySelectorAll('.form-progress-step').forEach(s => s.classList.add('completed'));
    }
  }

  function showSuccess() {
    const body = form.querySelector('.form-body');
    body.innerHTML = `
      <div style="text-align: center; padding: 3rem 1rem;">
        <div style="font-size: 4rem; margin-bottom: 1rem;">&#10003;</div>
        <h2 style="margin-bottom: 1rem; color: #1a2332;">Deal Submitted Successfully</h2>
        <p style="color: #4b5563; max-width: 500px; margin: 0 auto 2rem; font-size: 1.05rem;">
          We've received your scenario inquiry. A loan specialist will review your deal and reach out within
          <strong style="color: #d4a843;">15 minutes</strong> during business hours (M-F, 8am-6pm ET).
        </p>
        <div style="background: #f0f2f5; border-radius: 10px; padding: 1.5rem; max-width: 400px; margin: 0 auto 2rem;">
          <p style="font-size: 0.9rem; color: #6b7280; margin-bottom: 0.5rem;">What happens next?</p>
          <ol style="text-align: left; padding-left: 1.25rem; list-style: decimal; color: #4b5563; font-size: 0.9rem;">
            <li style="margin-bottom: 0.5rem;">Our AI matches your deal to the best lenders</li>
            <li style="margin-bottom: 0.5rem;">A specialist reviews and optimizes the match</li>
            <li style="margin-bottom: 0.5rem;">You receive term sheets to compare</li>
            <li>Choose your lender and close</li>
          </ol>
        </div>
        <a href="index.html" class="btn btn-primary" style="margin-right: 0.5rem;">Back to Home</a>
        <a href="submit.html" class="btn btn-outline" onclick="localStorage.removeItem('current_form');">Submit Another Deal</a>
      </div>
    `;
    // Hide progress
    const progressBar = document.querySelector('.form-progress');
    if (progressBar) {
      progressBar.querySelectorAll('.form-progress-step').forEach(s => s.classList.add('completed'));
    }
  }

  // --- Phone number formatting ---
  form.querySelectorAll('input[type="tel"]').forEach(input => {
    input.addEventListener('input', (e) => {
      let val = e.target.value.replace(/\D/g, '');
      if (val.length > 10) val = val.substr(0, 10);
      if (val.length >= 7) {
        val = `(${val.substr(0,3)}) ${val.substr(3,3)}-${val.substr(6)}`;
      } else if (val.length >= 4) {
        val = `(${val.substr(0,3)}) ${val.substr(3)}`;
      }
      e.target.value = val;
    });
  });

  // --- Currency formatting helper ---
  form.querySelectorAll('.currency-input').forEach(input => {
    input.addEventListener('blur', (e) => {
      let val = e.target.value.replace(/[^0-9.]/g, '');
      if (val) {
        const num = parseFloat(val);
        if (!isNaN(num)) {
          e.target.value = num.toLocaleString('en-US');
        }
      }
    });
    input.addEventListener('focus', (e) => {
      e.target.value = e.target.value.replace(/,/g, '');
    });
  });

  // Initialize first step
  showStep(0);
  adaptFormFields('');
});
