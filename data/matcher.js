// CCC Underwriting Matcher — matches deal inputs to real lender products
// Queries lenders.json and returns qualifying products with lender details
(function() {
  'use strict';

  const DATA_URL = '/data/lenders.json';
  let lenderData = null;

  // Type mappings: form value -> lender product types
  const TYPE_MAP = {
    'dscr':         ['dscr', 'portfolio'],
    'str':          ['dscr'],  // STR is a DSCR subtype
    'flip':         ['bridge'],
    'bridge':       ['bridge', 'bridge-to-perm'],
    'construction': ['construction', 'construction-to-perm'],
    'portfolio':    ['portfolio', 'dscr'],
    'multifamily':  ['multifamily', 'commercial', 'dscr'],
    'commercial':   ['commercial', 'multifamily'],
    'sba':          ['sba', 'commercial'],
    'cashout':      ['dscr', 'equity', 'heloc'],
    'refinance':    ['dscr', 'agency', 'government'],
    'bankstatement':['bank-statement'],
    'foreign':      ['foreign-national'],
    'itin':         ['itin']
  };

  // Property type mappings: form value -> what lender products accept
  const PROP_MAP = {
    'sfr':       ['SFR', 'SFR, 1-4 unit', 'SFR, 2-4 unit', '1-4 unit'],
    '2-4':       ['2-4 unit', 'SFR, 2-4 unit', 'SFR, 1-4 unit', '1-4 unit'],
    'condo':     ['condo', 'SFR, 1-4 unit, condo', 'non-warrantable condo', 'condotel'],
    'townhome':  ['townhome', 'SFR, 1-4 unit', 'condo, townhome'],
    '5plus':     ['5+ unit', 'multifamily', '5-9 unit', 'apartments'],
    'mixed-use': ['Mixed-use', 'mixed residential/commercial'],
    'office':    ['office', 'commercial', 'Commercial'],
    'retail':    ['retail', 'commercial', 'Commercial'],
    'industrial':['industrial', 'commercial', 'Commercial']
  };

  async function loadLenderData() {
    if (lenderData) return lenderData;
    try {
      const resp = await fetch(DATA_URL);
      if (!resp.ok) throw new Error('Failed to load lender data');
      lenderData = await resp.json();
      return lenderData;
    } catch(e) {
      console.error('[CCC Matcher] Failed to load lender data:', e);
      return null;
    }
  }

  // Main matching function
  // Input: { loanType, propType, txn, credit, ltv, dscr, state }
  // Output: Array of { lender, product, score }
  async function matchDeal(deal) {
    const data = await loadLenderData();
    if (!data) return [];

    const targetTypes = TYPE_MAP[deal.loanType] || [deal.loanType];
    const matches = [];

    data.lenders.forEach(lender => {
      lender.products.forEach(product => {
        let score = 0;
        let qualifies = true;

        // 1. Product type must match
        if (!targetTypes.some(t => product.type.toLowerCase().includes(t))) {
          qualifies = false;
        }

        // 2. Property type should match (soft match — check if any property type overlaps)
        if (qualifies && deal.propType && product.property) {
          const targetProps = PROP_MAP[deal.propType] || [deal.propType];
          const propStr = product.property.join(' ').toLowerCase();
          const propMatch = targetProps.some(p => propStr.includes(p.toLowerCase()));
          if (propMatch) {
            score += 20;
          } else {
            // Not a hard disqualifier for all types, but reduces score
            score -= 10;
          }
        }

        // 3. Transaction type alignment
        if (deal.txn === 'cashout') {
          const nameL = product.name.toLowerCase();
          if (nameL.includes('cash-out') || nameL.includes('cash out') || nameL.includes('cashout')) {
            score += 15;
          }
        } else if (deal.txn === 'refinance') {
          const nameL = product.name.toLowerCase();
          if (nameL.includes('refinance') || nameL.includes('refi') || nameL.includes('rate/term')) {
            score += 15;
          }
        } else if (deal.txn === 'purchase') {
          const nameL = product.name.toLowerCase();
          if (nameL.includes('purchase') || !nameL.includes('refi')) {
            score += 10;
          }
        }

        // 4. STR-specific matching
        if (deal.loanType === 'str') {
          const nameL = product.name.toLowerCase();
          if (nameL.includes('str') || nameL.includes('short-term') || nameL.includes('airbnb') || nameL.includes('vrbo')) {
            score += 25;
          }
        }

        // 5. Base score for qualifying
        if (qualifies) {
          score += 50;
          matches.push({
            lender: {
              name: lender.name,
              website: lender.website,
              channel: lender.channel
            },
            product: product,
            score: score
          });
        }
      });
    });

    // Sort by score descending
    matches.sort((a, b) => b.score - a.score);
    return matches;
  }

  // Format results for display
  function formatResults(matches) {
    if (!matches.length) {
      return '<div class="no-matches"><h3>No matching programs found</h3><p>Call us directly and we\'ll find a solution: <strong>(409) 332-9313</strong></p></div>';
    }

    // Group by lender
    const byLender = {};
    matches.forEach(m => {
      if (!byLender[m.lender.name]) {
        byLender[m.lender.name] = { lender: m.lender, products: [] };
      }
      byLender[m.lender.name].products.push(m.product);
    });

    let html = `<div class="match-header"><h3>${matches.length} qualifying products from ${Object.keys(byLender).length} lenders</h3></div>`;

    Object.values(byLender).forEach(group => {
      html += `<div class="match-lender">`;
      html += `<div class="match-lender-name">${group.lender.name}</div>`;
      html += `<div class="match-lender-channel">${group.lender.channel}</div>`;
      html += `<div class="match-products">`;
      group.products.forEach(p => {
        html += `<div class="match-product">`;
        html += `<span class="match-product-name">${p.name}</span>`;
        html += `<span class="match-product-term">${p.term}</span>`;
        html += `</div>`;
      });
      html += `</div></div>`;
    });

    return html;
  }

  // Expose globally
  window.CCCMatcher = {
    matchDeal: matchDeal,
    formatResults: formatResults,
    loadLenderData: loadLenderData
  };

})();
