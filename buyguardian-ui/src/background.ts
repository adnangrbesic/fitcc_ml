/**
 * BuyGuardian Service Worker (Background Script)
 * Manages state between content scripts and popup.
 */

// Cache last detected item per tab
const tabItemCache = new Map<number, { itemId: string; url: string }>();

// 1. Monitor tab updates to detect OLX listings automatically
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.url?.includes('olx.ba/artikal/')) {
    console.log('OLX Listing detected via URL:', tab.url);
    
    // Extract ID from URL for cache
    const match = tab.url.match(/\/artikal\/(\d+)/);
    if (match) {
      tabItemCache.set(tabId, { itemId: match[1], url: tab.url });
    }

    triggerEnrichment(tab.url);
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
  }
});

function triggerEnrichment(url: string) {
  console.log('Triggering enrichment for:', url);
  fetch('http://192.168.1.8:5000/api/scrape/queue', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(url)
  })
  .then(res => console.log('Enrichment response status:', res.status))
  .catch(err => console.error('Enrichment trigger failed:', err));
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
        // Re-trigger enrichment just in case it was missed
        triggerEnrichment(cached.url);
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
});
