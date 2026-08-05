DISCOVER_ELEMENTS_JS = """
(function() {
  const results = [];
  let idx = 0;

  const INTERACTIVE_TAGS = new Set([
    'a','button','input','select','textarea','details','summary'
  ]);
  const INTERACTIVE_ROLES = new Set([
    'button','link','checkbox','radio','menuitem','tab','textbox',
    'combobox','listbox','option','switch','treeitem','slider'
  ]);

  function collectElements(root, inShadow) {
    const walker = document.createTreeWalker(
      root,
      NodeFilter.SHOW_ELEMENT,
      null
    );
    let node = walker.currentNode;
    while (node) {
      const el = node;
      if (!el.tagName) { node = walker.nextNode(); continue; }
      const tag = el.tagName.toLowerCase();
      if (tag === 'iframe') {
        const src = el.getAttribute('src') || el.getAttribute('data-src') || '';
        let _iframeHost = '';
        try { _iframeHost = new URL(src, location.href).hostname; } catch(e) {}
        const isTracking = [
          'googletagmanager.com', 'google-analytics.com', 'facebook.net',
          'hotjar.com', 'sentry.io', 'recaptcha.net', 'doubleclick.net',
          'analytics.google.com', 'pixel.facebook.com', 'tr.snapchat.com'
        ].some(p => _iframeHost.includes(p));
        if (isTracking) { node = walker.nextNode(); continue; }
      }
      const role = el.getAttribute('role') || el.getAttribute('aria-role') || '';
      const ariaHidden = el.getAttribute('aria-hidden') === 'true';
      const style = window.getComputedStyle(el);
      const hidden = (
        style.display === 'none' ||
        style.visibility === 'hidden' ||
        parseFloat(style.opacity) === 0 ||
        ariaHidden ||
        el.offsetWidth === 0 ||
        el.offsetHeight === 0
      );

      if (!hidden && (INTERACTIVE_TAGS.has(tag) || INTERACTIVE_ROLES.has(role))) {
        const rect = el.getBoundingClientRect();
        results.push({
          index: idx++,
          tag: tag,
          role: role || tag,
          text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 120),
          placeholder: el.getAttribute('placeholder') || null,
          // el.href resolves relative URLs against the document for us. Only
          // fetchable schemes: mailto:/javascript:/tel:/#fragment are not pages.
          href: (function () {
            if (tag !== 'a') return null;
            const raw = el.getAttribute('href');
            if (!raw || raw.startsWith('#')) return null;
            const abs = el.href;
            return /^https?:/i.test(abs) ? abs : null;
          })(),
          inShadowDom: inShadow,
          cx: Math.round(rect.left + rect.width / 2),
          cy: Math.round(rect.top + rect.height / 2),
        });
      }

      if (el.shadowRoot) {
        collectElements(el.shadowRoot, true);
      }
      node = walker.nextNode();
    }
  }

  collectElements(document.body, false);
  return results;
})();
"""

CLICK_ELEMENT_JS = """
function(index) {
  const elements = [];
  const INTERACTIVE_TAGS = new Set([
    'a','button','input','select','textarea','details','summary'
  ]);
  const INTERACTIVE_ROLES = new Set([
    'button','link','checkbox','radio','menuitem','tab','textbox',
    'combobox','listbox','option','switch','treeitem','slider'
  ]);

  function collect(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, null);
    let node = walker.currentNode;
    while (node) {
      const el = node;
      if (!el.tagName) { node = walker.nextNode(); continue; }
      const tag = el.tagName.toLowerCase();
      const role = el.getAttribute('role') || '';
      if (INTERACTIVE_TAGS.has(tag) || INTERACTIVE_ROLES.has(role)) {
        const style = window.getComputedStyle(el);
        const hidden = (style.display === 'none' || style.visibility === 'hidden');
        if (!hidden) elements.push(el);
      }
      if (el.shadowRoot) collect(el.shadowRoot);
      node = walker.nextNode();
    }
  }

  collect(document.body);
  if (index < elements.length) {
    elements[index].click();
    return true;
  }
  return false;
}
"""

TYPE_ELEMENT_JS = """
function(index, text) {
  const elements = [];
  const INPUT_TAGS = new Set(['input','textarea']);

  function collect(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, null);
    let node = walker.currentNode;
    while (node) {
      const el = node;
      if (!el.tagName) { node = walker.nextNode(); continue; }
      const tag = el.tagName.toLowerCase();
      if (INPUT_TAGS.has(tag) || el.isContentEditable) {
        const style = window.getComputedStyle(el);
        if (style.display !== 'none') elements.push(el);
      }
      if (el.shadowRoot) collect(el.shadowRoot);
      node = walker.nextNode();
    }
  }

  collect(document.body);
  if (index < elements.length) {
    const el = elements[index];
    el.focus();
    el.value = '';
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.value = text;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  }
  return false;
}
"""

PAGE_TEXT_JS = """
(function() {
  const main = document.querySelector('main, [role="main"]') || document.body;
  return (main.innerText || main.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 8000);
})();
"""


CLICK_REVEAL_JS = """
(function () {
  // Fixed heuristic, not an LLM call — one LLM round-trip per page would
  // roughly double unit economics. Text list and aria-expanded are the
  // two signals real "show more" / "load more" / expander controls use.
  const PHRASES = ['show more', 'load more', 'next', 'expand', 'read more', 'see more'];

  function visible(el) {
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
  }
  function textMatches(el) {
    const t = (el.innerText || el.getAttribute('aria-label') || '').trim().toLowerCase();
    return PHRASES.some(function (p) { return t.includes(p); });
  }
  // A "Next" link on a paginated site navigates away, which hands read() a
  // different document mid-loop and breaks citation stability. Only click
  // anchors that stay on this page (no href, "#...", or same path+query).
  function staysOnPage(el) {
    if (el.tagName.toLowerCase() !== 'a') return true;
    const href = el.getAttribute('href');
    if (!href || href.charAt(0) === '#') return true;
    let abs;
    try { abs = new URL(href, location.href); } catch (e) { return false; }
    return abs.origin === location.origin
      && abs.pathname === location.pathname
      && abs.search === location.search;
  }

  let target = null;
  for (const el of document.querySelectorAll('a, button, [role="button"]')) {
    if (visible(el) && textMatches(el) && staysOnPage(el)) { target = el; break; }
  }
  if (!target) {
    for (const el of document.querySelectorAll('[aria-expanded="false"]')) {
      if (visible(el)) { target = el; break; }
    }
  }
  if (!target) return false;
  target.click();
  return true;
})();
"""

SCROLL_BOTTOM_JS = """
(function () {
  window.scrollTo(0, document.body.scrollHeight);
  return true;
})();
"""


READ_CONTENT_JS = r"""
(function () {
  const BAD = /(^|[-_ ])(nav|menu|sidebar|footer|header|banner|cookie|consent|promo|advert|subscribe|newsletter|related|comment|share|social|breadcrumb)([-_ ]|$)/i;
  const CHROME_TAGS = ['nav','footer','header','aside','script','style','noscript','form'];
  const CHROME_ROLES = ['navigation','banner','contentinfo','complementary','search'];

  function isChrome(el) {
    if (!el || !el.tagName) return false;
    if (CHROME_TAGS.includes(el.tagName.toLowerCase())) return true;
    if (CHROME_ROLES.includes(el.getAttribute('role') || '')) return true;
    return BAD.test(el.className || '') || BAD.test(el.id || '');
  }

  // Score a container by how much text sits in its own prose blocks. Nav-heavy
  // wrappers score low because their text lives in links, not paragraphs.
  function score(el) {
    let n = 0;
    for (const p of el.querySelectorAll('p, li, pre, blockquote')) {
      if (isChrome(p) || isChrome(p.parentElement)) continue;
      n += (p.innerText || '').trim().length;
    }
    return n;
  }

  let best = document.querySelector('article, main, [role="main"]');
  if (!best) {
    let bestScore = 0;
    for (const el of document.querySelectorAll('div, section, article, main')) {
      const s = score(el);
      // 1.05 so the *smallest* container holding the text wins ties
      if (s > bestScore * 1.05) { bestScore = s; best = el; }
    }
  }
  best = best || document.body;

  const blocks = [];
  const trail = [];
  const walker = document.createTreeWalker(best, NodeFilter.SHOW_ELEMENT);
  let node = walker.currentNode;
  while (node) {
    const tag = node.tagName.toLowerCase();
    if (isChrome(node)) {
      let next = walker.nextSibling();
      while (!next && walker.parentNode()) next = walker.nextSibling();
      node = next;
      continue;
    }
    if (/^h[1-6]$/.test(tag)) {
      const level = +tag[1];
      const text = (node.innerText || '').replace(/\s+/g, ' ').trim();
      if (text) {
        while (trail.length && trail[trail.length - 1].level >= level) trail.pop();
        trail.push({ level: level, text: text });
        blocks.push({ kind: 'heading', level: level, text: text,
                      path: trail.map(function (t) { return t.text; }) });
      }
    } else if (['p','li','pre','blockquote','td'].includes(tag)) {
      // leaf-ish only, so a nested container does not repeat its children's text
      if (!node.querySelector('p, li, pre, blockquote')) {
        const text = (node.innerText || '').replace(/\s+/g, ' ').trim();
        if (text.length > 2) {
          blocks.push({ kind: tag === 'pre' ? 'code' : 'text', level: 0, text: text,
                        path: trail.map(function (t) { return t.text; }) });
        }
      }
    }
    node = walker.nextNode();
  }
  return JSON.stringify({ title: document.title, url: location.href, blocks: blocks });
})();
"""
