/**
 * BuyGuardian Service Worker (Background Script)
 * Manages state between content scripts and popup.
 * 
 * Proactive behaviour:
 *   1. Detects OLX listing pages via URL pattern
 *   2. Triggers enrichment (scraping pipeline)
 *   3. Polls /api/analyze/{itemId} until data is ready
 *   4. Caches the result in chrome.storage.local
 *   5. Notifies the content script to inject a floating badge
 */

const DEFAULT_API = 'http://localhost:5000';

async function getApiUrl(): Promise<string> {
  return new Promise((resolve) => {
    chrome.storage.local.get('api_base_url', (res: Record<string, any>) => {
      resolve(res['api_base_url'] || DEFAULT_API);
    });
  });
}

// Cache last detected item per tab
const tabItemCache = new Map<number, { itemId: string; url: string }>();

// Track active polling intervals per tab
const activePolls = new Map<number, ReturnType<typeof setInterval>>();

// 1. Monitor tab updates to detect OLX listings automatically
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.url?.includes('olx.ba/artikal/')) {
    console.log('OLX Listing detected via URL:', tab.url);
    
    // Extract ID from URL for cache
    const match = tab.url.match(/\/artikal\/(\d+)/);
    if (match) {
      const itemId = match[1];
      tabItemCache.set(tabId, { itemId, url: tab.url });

      triggerEnrichment(tab.url);
      startBackgroundPolling(tabId, itemId);
    }
  }
});

// 2. Fallback: Listen for messages from content script
chrome.runtime.onMessage.addListener((message, sender) => {
  if (message.type === 'ITEM_DETECTED' && sender.tab?.id) {
    tabItemCache.set(sender.tab.id, {
      itemId: message.itemId,
      url: message.url
    });
    triggerEnrichment(message.url);
    startBackgroundPolling(sender.tab.id, message.itemId);
  }
});

async function triggerEnrichment(url: string) {
  const baseUrl = await getApiUrl();
  console.log('Triggering enrichment for:', url);
  fetch(`${baseUrl}/api/scrape/queue`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(url)
  })
  .then(res => console.log('Enrichment response status:', res.status))
  .catch(err => console.error('Enrichment trigger failed:', err));
}

/**
 * Poll /api/analyze/{itemId} every 3s, up to 10 times.
 * On success, cache in chrome.storage.local and notify the tab.
 */
function startBackgroundPolling(tabId: number, itemId: string) {
  // Stop any existing poll for this tab
  const existing = activePolls.get(tabId);
  if (existing) clearInterval(existing);

  let attempts = 0;
  const maxAttempts = 10;

  const poll = setInterval(async () => {
    attempts++;
    console.log(`[BG] Poll attempt ${attempts}/${maxAttempts} for item ${itemId}`);

    try {
      const baseUrl = await getApiUrl();
      const res = await fetch(`${baseUrl}/api/analyze/${itemId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}'
      });

      if (res.ok) {
        const data = await res.json();
        console.log(`[BG] Analysis ready for ${itemId}:`, data);

        // Cache in chrome.storage.local
        const cacheKey = `analysis_${itemId}`;
        await chrome.storage.local.set({ [cacheKey]: { data, timestamp: Date.now() } });

        // Also fetch recommendations
        try {
          const recRes = await fetch(`${baseUrl}/api/listings/${itemId}/recommendations`);
          if (recRes.ok) {
            const recommendations = await recRes.json();
            const recKey = `recs_${itemId}`;
            await chrome.storage.local.set({ [recKey]: { data: recommendations, timestamp: Date.now() } });
          }
        } catch (recErr) {
          console.warn('[BG] Recommendations fetch failed:', recErr);
        }

        // Notify content script
        try {
          chrome.tabs.sendMessage(tabId, {
            type: 'ANALYSIS_READY',
            itemId,
            data
          });
        } catch (e) {
          // Tab may not have content script
        }

        clearInterval(poll);
        activePolls.delete(tabId);
      } else if (res.status === 404) {
        console.log(`[BG] Item ${itemId} not ready yet (404). Retrying...`);
      } else {
        console.warn(`[BG] Unexpected status ${res.status} for ${itemId}`);
      }
    } catch (err) {
      console.warn(`[BG] Poll failed for ${itemId}:`, err);
    }

    if (attempts >= maxAttempts) {
      console.log(`[BG] Max poll attempts reached for ${itemId}. Stopping.`);
      clearInterval(poll);
      activePolls.delete(tabId);
    }
  }, 3000);

  activePolls.set(tabId, poll);
}

// When popup requests the current tab's item
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === 'GET_CURRENT_ITEM') {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const tab = tabs[0];
      if (!tab?.id) {
        sendResponse({ itemId: null });
        return;
      }

      // Check cache first
      const cached = tabItemCache.get(tab.id);
      if (cached) {
        sendResponse(cached);
        return;
      }

      // Ask content script directly
      chrome.tabs.sendMessage(tab.id, { type: 'GET_ITEM_ID' }, (response) => {
        if (chrome.runtime.lastError) {
          sendResponse({ itemId: null });
          return;
        }
        sendResponse(response || { itemId: null });
      });
    });
  }
  return true; // Always return true to keep channel open
});

// Clean up cache when tab closes
chrome.tabs.onRemoved.addListener((tabId) => {
  tabItemCache.delete(tabId);
  const poll = activePolls.get(tabId);
  if (poll) {
    clearInterval(poll);
    activePolls.delete(tabId);
  }
});
