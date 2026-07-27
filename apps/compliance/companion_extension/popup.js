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
    const result = await chrome.tabs.sendMessage(tab.id, {type: 'APLUS_FILL', payload});
    show(result?.message || 'Form scan completed. Review highlighted answers and save the page.', true);
  } catch (error) {
    show(error.message || String(error), false);
  }
});
