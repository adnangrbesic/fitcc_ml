/**
 * BuyGuardian Content Script
 */

function extractItemId(): string | null {
  const path = window.location.pathname;
  const urlMatch = path.match(/\/artikal\/(\d+)/);
  if (urlMatch) return urlMatch[1];
  const params = new URLSearchParams(window.location.search);
  const idParam = params.get('id');
  if (idParam) return idParam;
  return null;
}

interface ScoreParts {
  listing: number | null;
  seller: number | null;
  price: number | null;
}

interface ScoreLabelApi {
  getOverallScoreLabel: (scores: ScoreParts, isSuspicious?: boolean) => string;
  getTrustColorHex: (score: number | null | undefined, isSuspicious?: boolean) => string;
}

function getScoreLabelApi(): ScoreLabelApi | null {
  return (globalThis as any).BuyGuardianScoreLabels ?? null;
}

// ── Floating Badge Injection (Ultra-Premium Glass UI) ─────────────────────

async function injectFloatingBadge(data: any) {
  const existing = document.getElementById('buyguardian-badge');
  if (existing) existing.remove();

  // Load custom weights from storage
  const weights: any = await new Promise((resolve) => {
    chrome.storage.local.get(['weight_listing', 'weight_seller', 'weight_price'], (res) => {
      resolve({
        listing: res['weight_listing'] ?? 40,
        seller: res['weight_seller'] ?? 30,
        price: res['weight_price'] ?? 30
      });
    });
  });

  // Calculate Price Score (mirrors popup scoring logic)
  let priceScore = 0;
  let priceScoreForLabel: number | null = null;
  if (data.anomalyScore !== null && data.anomalyScore !== undefined) {
    if (data.isAnomaly) {
      const rawPenalty = Math.max(0.5, data.anomalyScore);
      priceScore = Math.max(0, Math.min(8, 10 - (rawPenalty * 5)));
    } else {
      priceScore = Math.max(0, Math.min(10, 10 - (data.anomalyScore * 5)));
    }
    priceScoreForLabel = priceScore;
  }

  // Calculate Seller Score
  const sellerScore = (data.sellerTrust ?? 0) * 10;
  const sellerScoreForLabel = data.sellerTrust === null || data.sellerTrust === undefined
    ? null
    : data.sellerTrust * 10;
  
  // Calculate Listing Score
  const listingScore = data.trustScore ?? 0;
  const listingScoreForLabel = data.trustScore === null || data.trustScore === undefined
    ? null
    : data.trustScore;

  // Final Weighted Score
  const totalWeight = weights.listing + weights.seller + weights.price;
  const trustScore = totalWeight > 0 
    ? (listingScore * weights.listing + sellerScore * weights.seller + priceScore * weights.price) / totalWeight
    : 0;

  const isSuspicious = data.isSuspicious === true;

  const labelApi = getScoreLabelApi();
  const color = labelApi ? labelApi.getTrustColorHex(trustScore, isSuspicious) : '#42a5f5';
  const label = labelApi
    ? labelApi.getOverallScoreLabel(
        {
          listing: listingScoreForLabel,
          seller: sellerScoreForLabel,
          price: priceScoreForLabel,
        },
        isSuspicious
      )
    : '';

  // Compute insights for hover card
  let priceComparisonText = '';
  if (data.marketPrice && data.listingPrice) {
    const diff = Math.round(((data.listingPrice - data.marketPrice) / data.marketPrice) * 100);
    if (diff < 0) {
      priceComparisonText = `${Math.abs(diff)}% ispod prosjeka cijene`;
    } else if (diff > 0) {
      priceComparisonText = `${diff}% iznad prosjeka cijene`;
    } else {
      priceComparisonText = `Prosječna tržišna cijena`;
    }
  } else {
    priceComparisonText = `Cijena u granicama prosjeka`;
  }

  const sellerTrust = data.sellerTrust ?? 0;

  let keyRiskHtml = '';
  if (data.isNewSeller) {
    keyRiskHtml = `<div class="bg-insight-row risk">Novi profil prodavača</div>`;
  } else if (data.isAnomaly) {
    keyRiskHtml = `<div class="bg-insight-row risk">Anomalija u cijeni</div>`;
  } else if (data.risks && data.risks.length > 0) {
    const rawRisk = data.risks[0];
    const riskTranslations: Record<string, string> = {
      low_trust: 'Nizak indeks povjerenja',
      new_listing: 'Nedavno postavljen oglas',
      new_account: 'Novi korisnički profil',
      high_volatility: 'Nestabilna cijena',
      empty_description: 'Nedostaje opis artikla',
      low_feedback: 'Malo povratnih informacija',
      price_too_low: 'Previše jeftino — moguća prevara',
      no_phone: 'Nema telefona',
      no_email: 'Email nije verifikovan',
      high_price: 'Skuplje od prosjeka',
    };
    const cleanRisk = riskTranslations[rawRisk] ?? rawRisk.replace(/_/g, ' ');
    keyRiskHtml = `<div class="bg-insight-row risk">${cleanRisk}</div>`;
  } else if (data.uiAlerts && data.uiAlerts.length > 0) {
    keyRiskHtml = `<div class="bg-insight-row risk">${data.uiAlerts[0]}</div>`;
  }

  const badge = document.createElement('div');
  badge.id = 'buyguardian-badge';
  
  badge.innerHTML = `
    <div class="bg-glass-badge">
      <div class="bg-main-content">
        <div class="bg-score-container" style="border-color: ${color}; background: ${color}22;">
          <span style="color: ${color}">${Math.round(trustScore * 10) / 10}</span>
        </div>
        <div class="bg-text-container">
          <span class="bg-brand">BuyGuardian</span>
          <span class="bg-label">${label}</span>
        </div>
      </div>
      <div class="bg-extra-info">
        <div class="bg-divider"></div>
        <div class="bg-insight-row">${priceComparisonText}</div>
        <div class="bg-insight-row">Prodavač: ${Math.round(sellerTrust * 100)}% pozitivni</div>
        ${keyRiskHtml}
      </div>
      <div class="bg-glow" style="background: ${color}"></div>
    </div>
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&display=swap');

      .bg-glass-badge {
        position: fixed !important;
        bottom: 35px;
        right: 35px;
        z-index: 2147483647 !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: flex-start !important;
        gap: 0px !important;
        padding: 12px 20px !important;
        background: rgba(255, 255, 255, 0.75) !important;
        backdrop-filter: blur(25px) saturate(200%) !important;
        -webkit-backdrop-filter: blur(25px) saturate(200%) !important;
        border: 1px solid rgba(255, 255, 255, 0.45) !important;
        border-radius: 100px !important;
        box-shadow: 0 12px 45px rgba(0,0,0,0.12), 0 0 0 1px rgba(0,0,0,0.03) !important;
        font-family: 'Outfit', system-ui, -apple-system, sans-serif !important;
        cursor: grab !important;
        transition: all 0.3s cubic-bezier(0.2, 1, 0.2, 1) !important;
        animation: bg-entrance 0.6s cubic-bezier(0.2, 1, 0.2, 1) backwards !important;
        user-select: none !important;
        overflow: hidden !important;
        max-width: 240px !important;
        max-height: 64px !important;
      }

      .bg-glass-badge.bg-dragging {
        cursor: grabbing !important;
        transition: none !important;
      }

      .bg-glass-badge:hover:not(.bg-dragging) {
        transform: translateY(-4px) !important;
        background: rgba(255, 255, 255, 0.9) !important;
        box-shadow: 0 18px 55px rgba(0,0,0,0.18) !important;
        border-radius: 16px !important;
        max-width: 320px !important;
        max-height: 240px !important;
      }

      .bg-main-content {
        display: flex !important;
        align-items: center !important;
        gap: 12px !important;
        width: 100% !important;
        height: 44px !important;
      }

      .bg-score-container {
        width: 40px !important;
        height: 40px !important;
        border-radius: 50% !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        font-size: 16px !important;
        font-weight: 800 !important;
        border: 2px solid !important;
        box-shadow: inset 0 0 10px rgba(255,255,255,0.5) !important;
        flex-shrink: 0 !important;
      }

      .bg-text-container {
        display: flex !important;
        flex-direction: column !important;
        gap: 0 !important;
      }

      .bg-brand {
        font-size: 10px !important;
        font-weight: 600 !important;
        color: #70757a !important;
        text-transform: uppercase !important;
        letter-spacing: 1.2px !important;
        line-height: 1 !important;
        margin-bottom: 2px !important;
      }

      .bg-label {
        font-size: 15px !important;
        font-weight: 700 !important;
        color: #1a1b1c !important;
        line-height: 1 !important;
      }

      .bg-extra-info {
        max-height: 0 !important;
        opacity: 0 !important;
        width: 100% !important;
        overflow: hidden !important;
        transition: max-height 0.3s ease, opacity 0.3s ease, margin-top 0.3s ease !important;
        display: flex !important;
        flex-direction: column !important;
        gap: 6px !important;
      }

      .bg-glass-badge:hover:not(.bg-dragging) .bg-extra-info {
        max-height: 120px !important;
        opacity: 1 !important;
        margin-top: 10px !important;
      }

      .bg-divider {
        height: 1px !important;
        background: rgba(0, 0, 0, 0.08) !important;
        width: 100% !important;
        margin-bottom: 2px !important;
      }

      .bg-insight-row {
        font-size: 12px !important;
        font-weight: 600 !important;
        color: #406367 !important;
        display: flex !important;
        align-items: center !important;
        gap: 6px !important;
        white-space: nowrap !important;
      }

      .bg-insight-row.risk {
        color: #d32f2f !important;
      }

      .bg-glow {
        position: absolute !important;
        top: 0; left: 0; right: 0; bottom: 0 !important;
        border-radius: 40px !important;
        opacity: 0.12 !important;
        filter: blur(20px) !important;
        z-index: -1 !important;
        animation: bg-pulse 3s infinite !important;
      }

      @keyframes bg-entrance {
        from { transform: translateY(60px) scale(0.8); opacity: 0; }
        to { transform: translateY(0) scale(1); opacity: 1; }
      }

      @keyframes bg-pulse {
        0% { opacity: 0.12; transform: scale(1); }
        50% { opacity: 0.25; transform: scale(1.1); }
        100% { opacity: 0.12; transform: scale(1); }
      }
    </style>
  `;

  document.body.appendChild(badge);

  // Position load from storage
  chrome.storage.local.get(['badgeBottom', 'badgeRight'], (pos) => {
    const bottom = pos['badgeBottom'];
    const right = pos['badgeRight'];
    const glassBadge = badge.querySelector('.bg-glass-badge') as HTMLElement;
    if (glassBadge) {
      if (typeof bottom === 'string') glassBadge.style.setProperty('bottom', bottom, 'important');
      if (typeof right === 'string') glassBadge.style.setProperty('right', right, 'important');
    }
  });

  // Draggable logic
  let isDragging = false;
  let hasMoved = false;
  let startX = 0;
  let startY = 0;
  let startBottom = 0;
  let startRight = 0;

  badge.addEventListener('mousedown', (e: MouseEvent) => {
    if (e.button !== 0) return; // only left click
    const glassBadge = badge.querySelector('.bg-glass-badge') as HTMLElement;
    if (!glassBadge) return;
    
    startX = e.clientX;
    startY = e.clientY;
    
    const computedStyle = window.getComputedStyle(glassBadge);
    startBottom = parseFloat(computedStyle.bottom) || 35;
    startRight = parseFloat(computedStyle.right) || 35;
    
    hasMoved = false;
    isDragging = false;

    const onMouseMove = (moveEvent: MouseEvent) => {
      const deltaX = moveEvent.clientX - startX;
      const deltaY = moveEvent.clientY - startY;

      if (Math.abs(deltaX) > 5 || Math.abs(deltaY) > 5) {
        hasMoved = true;
        isDragging = true;
        glassBadge.classList.add('bg-dragging');
      }

      if (isDragging) {
        const newBottom = startBottom - deltaY;
        const newRight = startRight - deltaX;
        glassBadge.style.setProperty('bottom', `${newBottom}px`, 'important');
        glassBadge.style.setProperty('right', `${newRight}px`, 'important');
      }
    };

    const onMouseUp = () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      
      if (isDragging) {
        chrome.storage.local.set({
          badgeBottom: glassBadge.style.bottom,
          badgeRight: glassBadge.style.right
        });
        glassBadge.classList.remove('bg-dragging');
      }
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  });

  badge.addEventListener('click', (e) => {
    if (hasMoved) {
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    chrome.runtime.sendMessage({ type: 'OPEN_POPUP' });
  });
}

// ── Navigation Tracking ────────────────────────────────────────────────

let lastProcessedUrl = '';

function monitorPageChanges() {
  const currentUrl = window.location.href;
  if (currentUrl === lastProcessedUrl) return;
  lastProcessedUrl = currentUrl;
  const itemId = extractItemId();

  if (itemId) {
    const cacheKey = `analysis_${itemId}`;
    chrome.storage.local.get(cacheKey, (result: Record<string, any>) => {
      const cached = result[cacheKey];
      if (cached?.data) {
        injectFloatingBadge(cached.data);
      }
    });

    chrome.runtime.sendMessage({ type: 'ITEM_DETECTED', itemId, url: currentUrl }).catch(() => {});
  } else {
    const existing = document.getElementById('buyguardian-badge');
    if (existing) existing.remove();
  }
}

// SPA Support
const originalPushState = history.pushState;
history.pushState = function() {
    originalPushState.apply(this, arguments as any);
    monitorPageChanges();
};

window.addEventListener('popstate', monitorPageChanges);
setInterval(monitorPageChanges, 1000);
monitorPageChanges();

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'ANALYSIS_READY' && message.data) {
    injectFloatingBadge(message.data);
  }
  return true;
});
