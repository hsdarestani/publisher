(() => {
  const normalize = (value) => String(value || '').toLowerCase().replace(/\s+/g, ' ').trim();
  const visible = (el) => !!(el && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
  const text = (el) => normalize(el?.innerText || el?.textContent || el?.getAttribute?.('aria-label'));

  function candidates() {
    return [...document.querySelectorAll('label, button, [role="radio"], [role="checkbox"], mat-radio-button, mat-checkbox, [aria-label]')].filter(visible);
  }

  function clickText(phrases, exclude = []) {
    const wanted = phrases.map(normalize);
    const blocked = exclude.map(normalize);
    const match = candidates().find((el) => {
      const value = text(el);
      return wanted.some((phrase) => value.includes(phrase)) && !blocked.some((phrase) => value.includes(phrase));
    });
    if (!match) return false;
    const target = match.closest('label,button,[role="radio"],[role="checkbox"],mat-radio-button,mat-checkbox') || match;
    target.click();
    target.style.outline = '2px solid #1769e0';
    target.style.outlineOffset = '2px';
    return true;
  }

  function setInputByLabel(labelPhrases, value, options = {}) {
    if (!value) return false;
    const phrases = labelPhrases.map(normalize);
    const labels = [...document.querySelectorAll('label, [aria-label], h1, h2, h3, h4, p, span')].filter(visible);
    const label = labels.find((el) => phrases.some((phrase) => text(el).includes(phrase)));
    let input = null;
    if (label) {
      const forId = label.getAttribute?.('for');
      if (forId) input = document.getElementById(forId);
      input ||= label.querySelector?.('input,textarea');
      input ||= label.parentElement?.querySelector?.('input,textarea');
      input ||= label.closest?.('div')?.querySelector?.('input,textarea');
    }
    if (!input && options.type) input = document.querySelector(options.type);
    if (!input || !visible(input)) return false;
    const setter = Object.getOwnPropertyDescriptor(input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value')?.set;
    setter ? setter.call(input, value) : (input.value = value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
    input.style.outline = '2px solid #1769e0';
    return true;
  }

  function checked(el) {
    return el.getAttribute('aria-checked') === 'true' || el.querySelector?.('input')?.checked;
  }

  function ensureCheckbox(labelText, desired = true) {
    const el = candidates().find((item) => text(item).includes(normalize(labelText)));
    if (!el) return false;
    if (checked(el) !== desired) (el.closest('[role="checkbox"],mat-checkbox,label') || el).click();
    el.style.outline = '2px solid #1769e0';
    return true;
  }

  function yesNo(answer) {
    return answer
      ? clickText(['yes'], ['not sure', 'no'])
      : clickText(['no'], ['not sure']);
  }

  function fillPrivacy(payload, actions) {
    if (!document.body.innerText.toLowerCase().includes('privacy policy')) return;
    if (setInputByLabel(['privacy policy url', 'privacy policy'], payload.privacy_policy?.url, {type: 'input[type="url"]'})) actions.push('Privacy policy URL');
  }

  function fillAppAccess(payload, actions) {
    const body = normalize(document.body.innerText);
    if (!body.includes('app access')) return;
    const access = payload.app_access || {};
    if (access.mode === 'unrestricted') {
      if (clickText(['all functionality in your app is available without any access restrictions', 'all functionality is available'])) actions.push('Unrestricted access');
    } else {
      if (clickText(['all or some functionality in your app is restricted', 'some functionality is restricted'])) actions.push('Restricted access');
      if (setInputByLabel(['instructions', 'provide instructions', 'any other information'], access.instructions)) actions.push('Reviewer instructions');
      if (setInputByLabel(['username', 'email address', 'login'], access.username)) actions.push('Reviewer username');
      if (setInputByLabel(['password'], access.password, {type: 'input[type="password"]'})) actions.push('Reviewer password');
    }
  }

  function fillAds(payload, actions) {
    const body = normalize(document.body.innerText);
    if (!body.includes('ads') || !body.includes('contains')) return;
    if (yesNo(!!payload.ads?.contains_ads)) actions.push('Ads declaration');
  }

  function fillAudience(payload, actions) {
    const body = normalize(document.body.innerText);
    if (!body.includes('target audience')) return;
    for (const age of payload.target_audience?.age_groups || []) {
      if (ensureCheckbox(age, true)) actions.push(`Age ${age}`);
    }
  }

  const RATING_LABELS = {
    violence: ['violence'],
    sexual_content: ['sexual content', 'sexuality'],
    language: ['language', 'profanity'],
    controlled_substances: ['controlled substances', 'drugs'],
    gambling: ['gambling'],
    user_generated_content: ['user-generated content', 'users can interact', 'online interaction'],
    location_sharing: ['share location', 'location sharing']
  };

  function fillContentRating(payload, actions) {
    const body = normalize(document.body.innerText);
    if (!body.includes('content rating') && !body.includes('questionnaire')) return;
    for (const [key, value] of Object.entries(payload.content_rating || {})) {
      const labels = RATING_LABELS[key] || [key.replaceAll('_', ' ')];
      const question = [...document.querySelectorAll('section,div,li')].filter(visible).find((el) => labels.some((label) => text(el).includes(label)) && text(el).length < 1000);
      if (!question) continue;
      const options = [...question.querySelectorAll('label,button,[role="radio"],mat-radio-button')].filter(visible);
      const desired = value ? 'yes' : 'no';
      const option = options.find((el) => text(el) === desired || text(el).startsWith(`${desired} `));
      if (option) {
        option.click();
        option.style.outline = '2px solid #1769e0';
        actions.push(`Rating: ${key}`);
      }
    }
  }

  function fillDataSafety(payload, actions) {
    const body = normalize(document.body.innerText);
    if (!body.includes('data safety')) return;
    const safety = payload.data_safety || {};
    const types = safety.data_types || {};
    if (body.includes('collect or share')) {
      if (yesNo(Object.keys(types).length > 0)) actions.push('Data collection summary');
    }
    if (body.includes('encrypted in transit') && yesNo(safety.encrypted_in_transit !== false)) actions.push('Encryption in transit');
    if (body.includes('request that their data is deleted') && yesNo(!!safety.deletion_request)) actions.push('Deletion request');
    for (const item of Object.values(types)) {
      if (item.label && ensureCheckbox(item.label, !!(item.collected || item.shared))) actions.push(`Data type: ${item.label}`);
    }
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.type !== 'APLUS_FILL') return;
    const actions = [];
    try {
      fillPrivacy(message.payload, actions);
      fillAppAccess(message.payload, actions);
      fillAds(message.payload, actions);
      fillAudience(message.payload, actions);
      fillContentRating(message.payload, actions);
      fillDataSafety(message.payload, actions);
      sendResponse({
        ok: true,
        message: actions.length
          ? `Filled/highlighted ${actions.length} answers:\n${actions.join('\n')}\n\nReview the highlighted fields, then click Save/Next in Play Console.`
          : 'No supported fields were detected on this page. Open one App content declaration page and keep Play Console in English.'
      });
    } catch (error) {
      sendResponse({ok: false, message: error.message || String(error)});
    }
    return true;
  });
})();
