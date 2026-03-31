// CCC Dynamic Stats — reads from lenders.json, updates all counts site-wide
// No more hardcoded numbers. Ever.

(function() {
  'use strict';

  const DATA_URL = '/data/lenders.json';

  async function loadStats() {
    try {
      const resp = await fetch(DATA_URL);
      if (!resp.ok) return;
      const data = await resp.json();

      const lenderCount = data.lenders.length;
      let productCount = 0;
      const productTypes = new Set();

      data.lenders.forEach(lender => {
        productCount += lender.products.length;
        lender.products.forEach(p => productTypes.add(p.type));
      });

      // Update all elements with data-stat attribute
      document.querySelectorAll('[data-stat="products"]').forEach(el => {
        el.textContent = productCount + '+';
      });
      document.querySelectorAll('[data-stat="lenders"]').forEach(el => {
        el.textContent = lenderCount + '+';
      });
      document.querySelectorAll('[data-stat="program-types"]').forEach(el => {
        el.textContent = productTypes.size + '+';
      });

      // Update any element with class 'dynamic-product-count'
      document.querySelectorAll('.dynamic-product-count').forEach(el => {
        el.textContent = productCount + '+';
      });
      document.querySelectorAll('.dynamic-lender-count').forEach(el => {
        el.textContent = lenderCount + '+';
      });

      // Update meta description if needed
      const meta = document.querySelector('meta[name="description"]');
      if (meta) {
        meta.content = meta.content.replace(/\d+\+?\s*(lending programs|loan products|programs)/gi,
          productCount + '+ loan products');
      }

      console.log(`[CCC] Loaded: ${lenderCount} lenders, ${productCount} products, ${productTypes.size} types`);
    } catch(e) {
      console.warn('[CCC] Could not load dynamic stats:', e);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadStats);
  } else {
    loadStats();
  }
})();
