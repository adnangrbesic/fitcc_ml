/**
 * BuyGuardian Content Script
 * Runs on OLX.ba pages, extracts the listing itemId and notifies the extension.
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

// Listen for popup requests
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === 'GET_ITEM_ID') {
    const itemId = extractItemId();
    sendResponse({ itemId, url: window.location.href });
  }
  return true; // Keep channel open for async
});

// Also push detected ID proactively when page loads
const detectedId = extractItemId();
if (detectedId) {
  chrome.runtime.sendMessage({
    type: 'ITEM_DETECTED',
    itemId: detectedId,
    url: window.location.href
  }).catch(() => {}); // Ignore if popup isn't open
}
