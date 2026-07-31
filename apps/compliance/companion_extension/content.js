(() => {
  const normalize = (value) => String(value || '').toLowerCase().replace(/\s+/g, ' ').trim();
  const visible = (el) => !!(el && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
  const text = (el) => normalize(el?.innerText || el?.textContent || el?.getAttribute?.('aria-label'));
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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

  function clickYesNoForQuestion(questionPhrases, answer) {
    const wanted = questionPhrases.map(normalize);
    const containers = [...document.querySelectorAll('section, form, div, li')]
      .filter(visible)
      .filter((el) => {
        const value = text(el);
        return value && value.length < 2200 && wanted.some((phrase) => value.includes(phrase));
      })
      .sort((a, b) => text(a).length - text(b).length);

    const desired = answer ? 'yes' : 'no';
    for (const container of containers) {
      const options = [...container.querySelectorAll('label, button, [role="radio"], mat-radio-button')].filter(visible);
      const option = options.find((el) => {
        const value = text(el);
        return value === desired || value.startsWith(`${desired} `);
      });
      if (!option) continue;
      const target = option.closest('label,button,[role="radio"],mat-radio-button') || option;
      target.click();
      target.style.outline = '2px solid #1769e0';
      target.style.outlineOffset = '2px';
      return true;
    }
    return false;
  }

  function editableInputs(root = document) {
    return [...root.querySelectorAll('input:not([type="hidden"]):not([disabled]), textarea:not([disabled])')]
      .filter((el) => visible(el) && el.type !== 'checkbox' && el.type !== 'radio');
  }

  function inputMetadata(input) {
    return normalize([
      input.getAttribute('aria-label'),
      input.getAttribute('placeholder'),
      input.getAttribute('name'),
      input.getAttribute('id'),
      input.getAttribute('data-placeholder'),
    ].filter(Boolean).join(' '));
  }

  function nearestInput(label) {
    if (!label) return null;
    const forId = label.getAttribute?.('for');
    if (forId) {
      const linked = document.getElementById(forId);
      if (linked && visible(linked)) return linked;
    }

    const local = label.querySelector?.('input,textarea');
    if (local && visible(local)) return local;

    let node = label;
    for (let depth = 0; node && depth < 6; depth += 1, node = node.parentElement) {
      const input = node.querySelector?.('input:not([type="hidden"]),textarea');
      if (input && visible(input)) return input;
    }

    const sibling = label.nextElementSibling?.querySelector?.('input,textarea');
    if (sibling && visible(sibling)) return sibling;
    return null;
  }

  function setInputByLabel(labelPhrases, value, options = {}) {
    if (!value) return false;
    const phrases = labelPhrases.map(normalize);
    let input = null;

    input = editableInputs().find((candidate) => {
      const metadata = inputMetadata(candidate);
      return phrases.some((phrase) => metadata.includes(phrase));
    });

    if (!input) {
      const labelNodes = [...document.querySelectorAll(
        'label, mat-label, [aria-label], [data-placeholder], h1, h2, h3, h4, p, span, div'
      )]
        .filter(visible)
        .filter((el) => {
          const valueText = text(el);
          return valueText && valueText.length <= 220 && phrases.some((phrase) => valueText.includes(phrase));
        })
        .sort((a, b) => text(a).length - text(b).length);

      for (const label of labelNodes) {
        input = nearestInput(label);
        if (input) break;
      }
    }

    for (const selector of options.selectors || []) {
      if (input) break;
      const match = [...document.querySelectorAll(selector)].find(visible);
      if (match) input = match;
    }

    if (!input && options.singleFieldFallback) {
      const main = document.querySelector('main, [role="main"]') || document;
      const fields = editableInputs(main).filter((candidate) => {
        const type = normalize(candidate.getAttribute('type') || 'text');
        return !['search', 'button', 'submit'].includes(type);
      });
      if (fields.length === 1) input = fields[0];
    }

    if (!input || !visible(input)) return false;
    const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
    input.focus();
    setter ? setter.call(input, value) : (input.value = value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
    input.style.outline = '2px solid #1769e0';
    input.style.outlineOffset = '2px';
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
    const body = normalize(document.body.innerText);
    if (!body.includes('privacy policy')) return;
    const onPrivacyPage = location.pathname.includes('/app-content/privacy-policy');
    if (setInputByLabel(
      ['privacy policy url', 'privacy policy'],
      payload.privacy_policy?.url,
      {
        selectors: [
          'input[type="url"]',
          'input[aria-label*="privacy" i]',
          'input[placeholder*="privacy" i]',
          'input[name*="privacy" i]',
        ],
        singleFieldFallback: onPrivacyPage,
      }
    )) actions.push('Privacy policy URL');
  }

  async function fillAppAccess(payload, actions) {
    const body = normalize(document.body.innerText);
    const onSignInPage = location.pathname.includes('/app-content/testing-credentials');
    if (!body.includes('app access') && !body.includes('sign in details') && !onSignInPage) return;

    const access = payload.app_access || {};
    const restricted = access.mode !== 'unrestricted';

    const choseRestriction = clickYesNoForQuestion(
      ['is any part of your app restricted', 'any part of your app restricted'],
      restricted
    );

    if (choseRestriction) {
      actions.push(restricted ? 'Restricted sign-in access' : 'Unrestricted sign-in access');
      await sleep(450);
    } else if (restricted) {
      if (clickText(['all or some functionality in your app is restricted', 'some functionality is restricted'])) {
        actions.push('Restricted sign-in access');
        await sleep(450);
      }
    } else if (clickText(['all functionality in your app is available without any access restrictions', 'all functionality is available'])) {
      actions.push('Unrestricted sign-in access');
      await sleep(450);
    }

    if (!restricted) return;

    // Current Play Console may hide credential fields behind an Add instructions action.
    if (!editableInputs().length && clickText(['add instructions', 'add instruction', 'add sign-in instructions'])) {
      actions.push('Opened sign-in instructions');
      await sleep(500);
    }

    if (setInputByLabel(
      ['instructions', 'provide instructions', 'access instructions', 'any other information'],
      access.instructions
    )) actions.push('Reviewer instructions');

    if (setInputByLabel(
      ['username', 'email address', 'email', 'login'],
      access.username,
      {selectors: ['input[autocomplete="username"]', 'input[type="email"]']}
    )) actions.push('Reviewer username');

    if (setInputByLabel(
      ['password'],
      access.password,
      {selectors: ['input[type="password"]', 'input[autocomplete="current-password"]']}
    )) actions.push('Reviewer password');
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
    (async () => {
      const actions = [];
      try {
        fillPrivacy(message.payload, actions);
        await fillAppAccess(message.payload, actions);
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
    })();
    return true;
  });
})();
