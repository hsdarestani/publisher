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

    await chrome.scripting.executeScript({
      target: {tabId},
      files: ['content.js'],
    });
    await new Promise((resolve) => setTimeout(resolve, 120));
    return await chrome.tabs.sendMessage(tabId, {type: 'APLUS_FILL', payload});
  }
}

async function fillRequiredSignInDetailsName(tabId, appName) {
  try {
    const [{result}] = await chrome.scripting.executeScript({
      target: {tabId},
      func: async (name) => {
        if (!location.pathname.includes('/app-content/testing-credentials')) return false;
        const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
        const visible = (el) => !!(el && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
        const normalized = (value) => String(value || '').toLowerCase().replace(/\s+/g, ' ').trim();
        const targetValue = `${name || 'App'} reviewer access`.slice(0, 60);

        for (let attempt = 0; attempt < 12; attempt += 1) {
          const dialogs = [...document.querySelectorAll('[role="dialog"], mat-dialog-container, .cdk-overlay-pane')].filter(visible);
          const dialog = dialogs.find((el) => normalized(el.innerText || el.textContent).includes('add sign in details'));
          const scope = dialog || document;
          if (!normalized(scope.innerText || scope.textContent).includes('add sign in details')) {
            await sleep(150);
            continue;
          }

          let input = null;
          const labels = [...scope.querySelectorAll('label, mat-label, [aria-label], span, div')]
            .filter(visible)
            .filter((el) => normalized(el.innerText || el.textContent || el.getAttribute?.('aria-label')).replace(/\s*\*\s*$/, '') === 'name')
            .sort((a, b) => normalized(a.innerText || a.textContent).length - normalized(b.innerText || b.textContent).length);

          for (const label of labels) {
            const forId = label.getAttribute?.('for');
            if (forId) {
              const linked = document.getElementById(forId);
              if (linked && visible(linked)) {
                input = linked;
                break;
              }
            }
            let node = label;
            for (let depth = 0; node && depth < 6 && !input; depth += 1, node = node.parentElement) {
              const candidate = node.querySelector?.('input:not([type="hidden"]):not([disabled]), textarea:not([disabled])');
              if (candidate && visible(candidate)) input = candidate;
            }
            if (input) break;
          }

          if (!input) {
            const fields = [...scope.querySelectorAll('input:not([type="hidden"]):not([disabled]), textarea:not([disabled])')]
              .filter((el) => visible(el) && !['checkbox', 'radio', 'password'].includes(el.type));
            input = fields.find((el) => {
              const metadata = normalized([
                el.getAttribute('aria-label'), el.getAttribute('placeholder'), el.getAttribute('name'), el.getAttribute('id')
              ].filter(Boolean).join(' '));
              return metadata === 'name' || metadata.startsWith('name ');
            }) || fields[0] || null;
          }

          if (input) {
            if (!String(input.value || '').trim()) {
              const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
              const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
              input.focus();
              setter ? setter.call(input, targetValue) : (input.value = targetValue);
              input.dispatchEvent(new Event('input', {bubbles: true}));
              input.dispatchEvent(new Event('change', {bubbles: true}));
            }
            input.style.outline = '2px solid #1769e0';
            input.style.outlineOffset = '2px';
            return true;
          }
          await sleep(150);
        }
        return false;
      },
      args: [appName || 'App'],
    });
    return !!result;
  } catch (_) {
    return false;
  }
}

async function fillCurrentIarcQuestionnaire(tabId, rating) {
  try {
    const [{result}] = await chrome.scripting.executeScript({
      target: {tabId},
      func: (answers) => {
        const normalize = (value) => String(value || '').toLowerCase().replace(/\s+/g, ' ').trim();
        const visible = (el) => !!(el && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
        const body = normalize(document.body.innerText || document.body.textContent);
        if (!body.includes('content ratings') && !body.includes('all other app types')) {
          return {handled: false, actions: []};
        }

        function answerExactQuestion(questionPhrases, answer, label) {
          const phrases = questionPhrases.map(normalize);
          const containers = [...document.querySelectorAll('section, form, div, li')]
            .filter(visible)
            .filter((el) => {
              const value = normalize(el.innerText || el.textContent);
              if (!value || value.length > 1800) return false;
              const hasQuestion = phrases.some((phrase) => value.includes(phrase));
              const hasYes = /(^|\s)yes(\s|$)/.test(value);
              const hasNo = /(^|\s)no(\s|$)/.test(value);
              return hasQuestion && hasYes && hasNo;
            })
            .sort((a, b) => normalize(a.innerText || a.textContent).length - normalize(b.innerText || b.textContent).length);

          const desired = answer ? 'yes' : 'no';
          for (const container of containers) {
            const options = [...container.querySelectorAll('label, button, [role="radio"], mat-radio-button')].filter(visible);
            const option = options.find((el) => {
              const value = normalize(el.innerText || el.textContent || el.getAttribute?.('aria-label'));
              return value === desired || value.startsWith(`${desired} `);
            });
            if (!option) continue;
            const target = option.closest('label,button,[role="radio"],mat-radio-button') || option;
            target.click();
            target.style.outline = '2px solid #1769e0';
            target.style.outlineOffset = '2px';
            return label;
          }
          return null;
        }

        const actions = [];
        const downloadedKeys = ['violence', 'sexual_content', 'language', 'controlled_substances', 'gambling'];
        const knownDownloadedKeys = downloadedKeys.filter((key) => Object.prototype.hasOwnProperty.call(answers || {}, key));
        if (knownDownloadedKeys.length) {
          const containsRatingsRelevantDownloadedContent = knownDownloadedKeys.some((key) => answers[key] === true);
          const action = answerExactQuestion(
            ['does the app contain any ratings-relevant content'],
            containsRatingsRelevantDownloadedContent,
            `Downloaded App: ${containsRatingsRelevantDownloadedContent ? 'Yes' : 'No'}`
          );
          if (action) actions.push(action);
        }

        return {
          handled: true,
          actions,
          message: actions.length
            ? `Filled/highlighted ${actions.length} safe IARC answer(s):\n${actions.join('\n')}\n\nOther IARC sections were intentionally left untouched because the current Publisher payload does not map to them exactly. Review them before Save/Next.`
            : 'Current IARC questionnaire detected, but no safe exact-match answer was available. Nothing was changed.'
        };
      },
      args: [rating || {}],
    });
    return result || {handled: false, actions: []};
  } catch (_) {
    return {handled: false, actions: []};
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

    let result;
    if (tab.url.includes('/app-content/content-rating-iarc-questionnaire')) {
      const iarc = await fillCurrentIarcQuestionnaire(tab.id, payload.content_rating || {});
      if (iarc.handled) {
        result = {message: iarc.message};
      } else {
        result = await sendFillMessage(tab.id, payload);
      }
    } else {
      result = await sendFillMessage(tab.id, payload);
    }

    const filledName = await fillRequiredSignInDetailsName(tab.id, payload.app?.name);
    let message = result?.message || 'Form scan completed. Review highlighted answers and save the page.';
    if (filledName && !message.includes('Sign-in details name')) {
      message += '\nSign-in details name';
    }
    show(message, true);
  } catch (error) {
    show(error.message || String(error), false);
  }
});
