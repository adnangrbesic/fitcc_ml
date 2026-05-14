/**
 * BuyGuardian Service Worker (Background Script)
 */

const DEFAULT_API = 'http://127.0.0.1:5000';
const ANALYSIS_POLL_INTERVAL_MS = 3000;
const ANALYSIS_MAX_ATTEMPTS = 100;

async function getApiUrl(): Promise<string> {
  return new Promise((resolve) => {
    chrome.storage.local.get('api_base_url', (res: Record<string, any>) => {
      let url = res['api_base_url'] || DEFAULT_API;
      url = url.replace(/\/$/, ''); 
      resolve(url);
    });
  });
}

const tabItemCache = new Map<number, { itemId: string; url: string }>();
const activePolls = new Map<number, ReturnType<typeof setInterval>>();
const currentPollingItem = new Map<number, string>();

function stopActivePoll(tabId: number) {
  const existing = activePolls.get(tabId);
  if (existing) {
    clearInterval(existing);
    activePolls.delete(tabId);
  }
  currentPollingItem.delete(tabId);
}

async function triggerEnrichment(url: string) {
  const baseUrl = await getApiUrl();
  try {
    await fetch(`${baseUrl}/api/Scrape/queue`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(url)
    });
  } catch (err) {
    console.error('[BG] Scrape trigger failed:', err);
  }
}

function startBackgroundPolling(tabId: number, itemId: string) {
  if (currentPollingItem.get(tabId) === itemId) return;
  
  currentPollingItem.set(tabId, itemId);
  stopActivePoll(tabId);
  
  let attempts = 0;
  const poll = setInterval(async () => {
    attempts++;
    try {
      const baseUrl = await getApiUrl();
      
      const enrichRes = await fetch(`${baseUrl}/api/Listings/${itemId}/needs-enrichment`);
      if (enrichRes.ok) {
        const enrichData = await enrichRes.json();
        const needsEnrichment = enrichData.NeedsEnrichment ?? enrichData.needsEnrichment;
        
        if (needsEnrichment === false) {
          const analyzeRes = await fetch(`${baseUrl}/api/Analyze/${itemId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: '{}'
          });
          
          if (analyzeRes.ok) {
            const data = await analyzeRes.json();
            const cacheKey = `analysis_${itemId}`;
            await chrome.storage.local.set({ [cacheKey]: { data, timestamp: Date.now() } });
            
            chrome.tabs.sendMessage(tabId, { type: 'ANALYSIS_READY', itemId, data }).catch(() => {});
            stopActivePoll(tabId);
            return;
          }
        }
      }
    } catch (err) {
      console.warn(`[BG] Poll error for ${itemId}:`, err);
    }

    if (attempts >= ANALYSIS_MAX_ATTEMPTS) {
      stopActivePoll(tabId);
    }
  }, ANALYSIS_POLL_INTERVAL_MS);

  activePolls.set(tabId, poll);
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (tab.url?.includes('olx.ba/artikal/')) {
    const match = tab.url.match(/\/artikal\/(\d+)/);
    if (match) {
      const itemId = match[1];
      const last = tabItemCache.get(tabId);
      if (last?.itemId !== itemId) {
        tabItemCache.set(tabId, { itemId, url: tab.url });
        triggerEnrichment(tab.url);
        startBackgroundPolling(tabId, itemId);
      }
    }
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'ITEM_DETECTED' && sender.tab?.id) {
    tabItemCache.set(sender.tab.id, { itemId: message.itemId, url: message.url });
    triggerEnrichment(message.url);
    startBackgroundPolling(sender.tab.id, message.itemId);
  }
  
  if (message.type === 'GET_CURRENT_ITEM') {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const activeTab = tabs[0];
      if (activeTab?.id) {
        const cached = tabItemCache.get(activeTab.id);
        if (cached) {
          sendResponse({ itemId: cached.itemId, url: cached.url });
        } else if (activeTab.url?.includes('olx.ba/artikal/')) {
          const match = activeTab.url.match(/\/artikal\/(\d+)/);
          if (match) {
            sendResponse({ itemId: match[1], url: activeTab.url });
          } else {
            sendResponse(null);
          }
        } else {
          sendResponse(null);
        }
      } else {
        sendResponse(null);
      }
    });
    return true; // Keep channel open for async sendResponse
  }

  if (message.type === 'OPEN_POPUP') {
    if ((chrome.action as any).openPopup) {
      (chrome.action as any).openPopup();
    }
  }

  return true; 
});
