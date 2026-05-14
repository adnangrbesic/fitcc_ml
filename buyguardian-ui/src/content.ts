/**
 * BuyGuardian Content Script
 * Runs on OLX.ba pages, extracts the listing itemId and notifies the extension.
 * Also injects a floating trust badge when analysis data is ready.
 */

function extractItemId(): string | null {
  // 1. Try URL pattern: /artikal/12345678
  const urlMatch = window.location.pathname.match(/\/artikal\/(\d+)/);
  if (urlMatch) return urlMatch[1];

  // 2. Try URL pattern: ?id=12345678
  const params = new URLSearchParams(window.location.search);
  const idParam = params.get('id');
  if (idParam) return idParam;

  // 3. Try DOM: meta tag or data attribute
  const metaId = document.querySelector('meta[name="og:url"]') as HTMLMetaElement;
  if (metaId?.content) {
    const metaMatch = metaId.content.match(/(\d{6,})/);
    if (metaMatch) return metaMatch[1];
  }

  // 4. Try DOM: ID in listing element
  const listingEl = document.querySelector('[data-cy="ad-footer-bar-section"]');
  if (listingEl) {
    const idText = listingEl.textContent?.match(/ID:\s*(\d+)/);
    if (idText) return idText[1];
  }

  return null;
}

// ── Floating Badge Injection ────────────────────────────────────────────

function injectFloatingBadge(data: any) {
  // Remove existing badge if present
  const existing = document.getElementById('buyguardian-badge');
  if (existing) existing.remove();

  const trustScore = data.overallScore ?? data.trustScore;
  const listingScore = data.trustScore;
  const sellerScore = typeof data.sellerTrust === 'number' ? data.sellerTrust * 10 : null;
  const priceScore = typeof data.anomalyScore === 'number' ? data.anomalyScore : null;
  const listingWeightLabel = '70% · max 10';
  const sellerWeightLabel = '30% · max 10';
  const priceWeightLabel = 'penalty 0-2 (lower better)';
  const priceLabel = data.isAnomaly
    ? (data.anomalyType
      ? String(data.anomalyType).replace(/^anomaly_/, '').replace(/_/g, ' ')
      : 'anomaly')
    : (priceScore !== null ? 'normal' : 'n/a');

  const formatScore = (value: number | null | undefined) => {
    if (value === null || value === undefined || Number.isNaN(value)) return 'N/A';
    return value.toFixed(1);
  };

  const formatPrice = () => {
    if (priceScore === null || priceScore === undefined || Number.isNaN(priceScore)) {
      return 'N/A';
    }
    return `${priceScore.toFixed(2)} (${priceLabel})`;
  };
  const isSuspicious = data.isSuspicious;

  // Determine color & label
  let color: string, bgColor: string, label: string;
  if (isSuspicious && (trustScore === null || trustScore < 7.5)) {
    color = '#ff4444';
    bgColor = 'rgba(255, 68, 68, 0.15)';
    label = 'Sumnjiv oglas';
  } else if (trustScore >= 8) {
    color = '#00e676';
    bgColor = 'rgba(0, 230, 118, 0.12)';
    label = 'Visok trust';
  } else if (trustScore >= 5) {
    color = '#ffab40';
    bgColor = 'rgba(255, 171, 64, 0.12)';
    label = 'Srednji trust';
  } else {
    color = '#ff5252';
    bgColor = 'rgba(255, 82, 82, 0.12)';
    label = 'Nizak trust';
  }

  const badge = document.createElement('div');
  badge.id = 'buyguardian-badge';
  badge.innerHTML = `
    <div class="buyguardian-badge" style="
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 999999;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 12px 20px;
      background: ${bgColor};
      backdrop-filter: blur(20px) saturate(180%);
      -webkit-backdrop-filter: blur(20px) saturate(180%);
      border: 1px solid ${color}40;
      border-radius: 50px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.2), 0 0 0 1px rgba(255,255,255,0.05);
      font-family: 'Geomanist', -apple-system, BlinkMacSystemFont, sans-serif;
      cursor: pointer;
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      animation: buyguardian-slide-in 0.5s cubic-bezier(0.4, 0, 0.2, 1) forwards;
    "
    onmouseover="this.style.transform='scale(1.05) translateY(-2px)'; this.style.boxShadow='0 12px 40px rgba(0,0,0,0.3), 0 0 20px ${color}30'"
    onmouseout="this.style.transform='scale(1) translateY(0)'; this.style.boxShadow='0 8px 32px rgba(0,0,0,0.2), 0 0 0 1px rgba(255,255,255,0.05)'"
    >
      <div class="buyguardian-tooltip">
        <div class="buyguardian-tooltip-row">
          <span>Listing:</span>
          <strong>${formatScore(listingScore)}</strong>
          <span class="buyguardian-tooltip-meta">${listingWeightLabel}</span>
        </div>
        <div class="buyguardian-tooltip-row">
          <span>Seller:</span>
          <strong>${formatScore(sellerScore)}</strong>
          <span class="buyguardian-tooltip-meta">${sellerWeightLabel}</span>
        </div>
        <div class="buyguardian-tooltip-row">
          <span>Price:</span>
          <strong>${formatPrice()}</strong>
          <span class="buyguardian-tooltip-meta">${priceWeightLabel}</span>
        </div>
      </div>
      <div style="
        width: 40px; height: 40px;
        border-radius: 50%;
        background: linear-gradient(135deg, ${color}30, ${color}60);
        display: flex; align-items: center; justify-content: center;
        font-size: 16px; font-weight: 700; color: ${color};
        border: 2px solid ${color}80;
      ">${trustScore !== null && trustScore !== undefined ? trustScore.toFixed(1) : '...'}</div>
      <div>
        <div style="font-size: 11px; color: #888; letter-spacing: 0.5px; text-transform: uppercase;">BuyGuardian</div>
        <div style="font-size: 14px; font-weight: 600; color: ${color};">${label}</div>
      </div>
    </div>
    <style>
      @keyframes buyguardian-slide-in {
        from { opacity: 0; transform: translateY(20px) scale(0.95); }
        to { opacity: 1; transform: translateY(0) scale(1); }
      }

      .buyguardian-tooltip {
        position: absolute;
        bottom: calc(100% + 10px);
        right: 0;
        background: rgba(0, 0, 0, 0.85);
        color: #fff;
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 10px;
        padding: 8px 10px;
        font-size: 11px;
        line-height: 1.4;
        display: grid;
        gap: 4px;
        min-width: 160px;
        opacity: 0;
        transform: translateY(6px);
        transition: opacity 0.2s ease, transform 0.2s ease;
        pointer-events: none;
        box-shadow: 0 10px 24px rgba(0,0,0,0.25);
      }

      .buyguardian-tooltip-row {
        display: grid;
        grid-template-columns: auto auto 1fr;
        align-items: center;
        column-gap: 6px;
      }

      .buyguardian-tooltip span {
        color: rgba(255, 255, 255, 0.7);
        margin-right: 6px;
      }

      .buyguardian-tooltip strong {
        font-weight: 700;
        color: #fff;
      }

      .buyguardian-tooltip-meta {
        color: rgba(255, 255, 255, 0.55);
        font-size: 10px;
        text-align: right;
      }

      .buyguardian-badge:hover .buyguardian-tooltip {
        opacity: 1;
        transform: translateY(0);
      }
    </style>
  `;

  document.body.appendChild(badge);

  // Click to open extension popup (or focus on it)
  badge.addEventListener('click', () => {
    chrome.runtime.sendMessage({ type: 'OPEN_POPUP' });
  });
}

// ── Navigation and Soft-Update Tracking ─────────────────────────────────

let lastProcessedUrl = '';

function monitorPageChanges() {
  const currentUrl = window.location.href;
  if (currentUrl === lastProcessedUrl) return;
  
  lastProcessedUrl = currentUrl;
  const itemId = extractItemId();

  if (!itemId) {
    // User navigated away to non-listing page: REMOVE badge instantly!
    const existing = document.getElementById('buyguardian-badge');
    if (existing) {
      existing.style.opacity = '0';
      existing.style.transform = 'translateY(20px) scale(0.9)';
      setTimeout(() => existing.remove(), 300);
    }
    return;
  }

  // If we DO have an ID, treat it as a potential refresh/new page
  chrome.runtime.sendMessage({
    type: 'ITEM_DETECTED',
    itemId: itemId,
    url: currentUrl
  }).catch(() => {});

  // Check cache again in case it's a new article accessed via client routing
  const cacheKey = `analysis_${itemId}`;
  chrome.storage.local.get(cacheKey, (result: Record<string, any>) => {
    const cached = result[cacheKey];
    if (cached?.data) {
      const ageMinutes = (Date.now() - cached.timestamp) / 60000;
      if (ageMinutes < 60) {
        injectFloatingBadge(cached.data);
      }
    } else {
      // Cache missed, remove old stale badge from previous page
      const existing = document.getElementById('buyguardian-badge');
      if (existing) existing.remove();
    }
  });
}

// Start monitoring
setInterval(monitorPageChanges, 1000);
// Trigger immediately on script load
monitorPageChanges();

// ── Listen for incoming messages ────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === 'GET_ITEM_ID') {
    const itemId = extractItemId();
    sendResponse({ itemId, url: window.location.href });
  }

  if (message.type === 'ANALYSIS_READY' && message.data) {
    // Verify we are still on that item before rendering!
    const currentId = extractItemId();
    if (currentId && message.data.itemId && String(currentId) === String(message.data.itemId)) {
      injectFloatingBadge(message.data);
    }
  }

  return true;
});
