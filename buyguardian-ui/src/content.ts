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

  // Calculate Price Score (duplicated logic from app.ts)
  let priceScore = 0;
  if (data.anomalyScore !== null && data.anomalyScore !== undefined) {
    if (data.isAnomaly) {
      const rawPenalty = Math.max(0.5, data.anomalyScore);
      priceScore = Math.max(0, Math.min(8, 10 - (rawPenalty * 5)));
    } else {
      priceScore = Math.max(0, Math.min(10, 10 - (data.anomalyScore * 5)));
    }
  }

  // Calculate Seller Score
  const sellerScore = (data.sellerTrust ?? 0) * 10;
  
  // Calculate Listing Score
  const listingScore = data.trustScore ?? 0;

  // Final Weighted Score
  const totalWeight = weights.listing + weights.seller + weights.price;
  const trustScore = totalWeight > 0 
    ? (listingScore * weights.listing + sellerScore * weights.seller + priceScore * weights.price) / totalWeight
    : 0;

  const isSuspicious = data.isSuspicious === true;

  let color = '#42a5f5'; 
  let label = 'Trusted';
  if (isSuspicious) {
    color = '#ff1744';
    label = 'Prevara';
  } else if (trustScore >= 9) {
    color = '#2e7d32'; // Meadow Green
    label = 'Sigurno';
  } else if (trustScore >= 7) {
    color = '#66bb6a'; // Lighter Green
    label = 'Visoki trust';
  } else if (trustScore >= 5.1) {
    color = '#ffab40';
    label = 'Srednji trust';
  } else {
    color = '#ff1744';
    label = 'Prevara';
  }

  const badge = document.createElement('div');
  badge.id = 'buyguardian-badge';
  
  badge.innerHTML = `
    <div class="bg-glass-badge">
      <div class="bg-score-container" style="border-color: ${color}; background: ${color}22;">
        <span style="color: ${color}">${Math.round(trustScore * 10) / 10}</span>
      </div>
      <div class="bg-text-container">
        <span class="bg-brand">BuyGuardian</span>
        <span class="bg-label">${label}</span>
      </div>
      <div class="bg-glow" style="background: ${color}"></div>
    </div>
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&display=swap');

      .bg-glass-badge {
        position: fixed !important;
        bottom: 35px !important;
        right: 35px !important;
        z-index: 2147483647 !important;
        display: flex !important;
        align-items: center !important;
        gap: 16px !important;
        padding: 14px 26px !important;
        background: rgba(255, 255, 255, 0.75) !important;
        backdrop-filter: blur(25px) saturate(200%) !important;
        -webkit-backdrop-filter: blur(25px) saturate(200%) !important;
        border: 1px solid rgba(255, 255, 255, 0.45) !important;
        border-radius: 100px !important;
        box-shadow: 0 12px 45px rgba(0,0,0,0.12), 0 0 0 1px rgba(0,0,0,0.03) !important;
        font-family: 'Outfit', system-ui, -apple-system, sans-serif !important;
        cursor: pointer !important;
        transition: all 0.4s cubic-bezier(0.2, 1, 0.2, 1) !important;
        animation: bg-entrance 0.6s cubic-bezier(0.2, 1, 0.2, 1) backwards !important;
        user-select: none !important;
      }

      .bg-glass-badge:hover {
        transform: translateY(-6px) scale(1.03) !important;
        background: rgba(255, 255, 255, 0.85) !important;
        box-shadow: 0 18px 55px rgba(0,0,0,0.18) !important;
      }

      .bg-score-container {
        width: 44px !important;
        height: 44px !important;
        border-radius: 50% !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        font-size: 17px !important;
        font-weight: 800 !important;
        border: 2px solid !important;
        box-shadow: inset 0 0 10px rgba(255,255,255,0.5) !important;
      }

      .bg-text-container {
        display: flex !important;
        flex-direction: column !important;
        gap: 0 !important;
      }

      .bg-brand {
        font-size: 11px !important;
        font-weight: 600 !important;
        color: #70757a !important;
        text-transform: uppercase !important;
        letter-spacing: 1.2px !important;
        line-height: 1 !important;
        margin-bottom: 4px !important;
      }

      .bg-label {
        font-size: 17px !important;
        font-weight: 700 !important;
        color: #1a1b1c !important;
        line-height: 1 !important;
      }

      .bg-glow {
        position: absolute !important;
        top: 0; left: 0; right: 0; bottom: 0 !important;
        border-radius: 100px !important;
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
  badge.onclick = () => chrome.runtime.sendMessage({ type: 'OPEN_POPUP' });
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
