const urlInput = document.getElementById('payloadUrl');
const statusBox = document.getElementById('status');

function show(message, ok = true) {
  statusBox.style.display = 'block';
  statusBox.style.color = ok ? '#176b5b' : '#b42318';
  statusBox.textContent = message;
}

chrome.storage.local.get(['aplusPayloadUrl'], (data) => {
  if (data.aplusPayloadUrl) urlInput.value = data.aplusPayloadUrl;
});

document.getElementById('clear').addEventListener('click', () => {
  chrome.storage.local.remove(['aplusPayloadUrl']);
  urlInput.value = '';
  show('Companion session cleared.');
});

async function sendFillMessage(tabId, payload) {
  try {
    return await chrome.tabs.sendMessage(tabId, {type: 'APLUS_FILL', payload});
  } catch (error) {
    const message = String(error?.message || error || '').toLowerCase();
    const missingReceiver = message.includes('receiving end does not exist') ||
      message.includes('could not establish connection') ||
      message.includes('message port closed');
    if (!missingReceiver) throw error;

    // Reloading/updating an unpacked extension disconnects content scripts that
    // were injected into already-open Play Console tabs. Recover automatically
    // instead of forcing the user to remember a refresh/reload order.
    await chrome.scripting.executeScript({
      target: {tabId},
      files: ['content.js'],
    });
    await new Promise((resolve) => setTimeout(resolve, 120));
    return await chrome.tabs.sendMessage(tabId, {type: 'APLUS_FILL', payload});
  }
}

document.getElementById('fill').addEventListener('click', async () => {
  const payloadUrl = urlInput.value.trim();
  if (!payloadUrl.startsWith('https://publisher.smarbiz.sbs/compliance/companion/')) {
    show('Paste a valid A+ Publisher Companion payload URL.', false);
    return;
  }
  try {
    await chrome.storage.local.set({aplusPayloadUrl: payloadUrl});
    const response = await fetch(payloadUrl, {cache: 'no-store'});
    if (!response.ok) throw new Error(`Publisher returned HTTP ${response.status}`);
    const payload = await response.json();
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    if (!tab || !tab.url || !tab.url.startsWith('https://play.google.com/console/')) {
      throw new Error('Open the relevant Google Play Console form first.');
    }
    const result = await sendFillMessage(tab.id, payload);
    show(result?.message || 'Form scan completed. Review highlighted answers and save the page.', true);
  } catch (error) {
    show(error.message || String(error), false);
  }
});
