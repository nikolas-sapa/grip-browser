# The single definition of "which elements are addressable, and in what order".
#
# DISCOVER, CLICK and TYPE all index into this same list. They previously each
# had their own copy of the rules and had drifted apart: DISCOVER treated an
# element as hidden on six conditions, CLICK on two, and TYPE collected an
# entirely different (input-only) set. Since `page.click()`/`page.type()` pass an
# index taken from DISCOVER's snapshot, any disagreement meant acting on the
# wrong element — silently, and only on pages that happen to contain an
# aria-hidden or opacity:0 control. Sharing one collector makes that class of bug
# unrepresentable rather than merely fixed.
_COLLECT_CANDIDATES_JS = """
  const INTERACTIVE_TAGS = new Set([
    'a','button','input','select','textarea','details','summary'
  ]);
  const INTERACTIVE_ROLES = new Set([
    'button','link','checkbox','radio','menuitem','tab','textbox',
    'combobox','listbox','option','switch','treeitem','slider'
  ]);
  const _TRACKING_HOSTS = [
    'googletagmanager.com', 'google-analytics.com', 'facebook.net',
    'hotjar.com', 'sentry.io', 'recaptcha.net', 'doubleclick.net',
    'analytics.google.com', 'pixel.facebook.com', 'tr.snapchat.com'
  ];

  function gripRole(el) {
    return el.getAttribute('role') || el.getAttribute('aria-role') || '';
  }

  function gripIsCandidate(el, tag, role) {
    return INTERACTIVE_TAGS.has(tag) || INTERACTIVE_ROLES.has(role);
  }

  // Layout-forcing reads (getComputedStyle, offsetWidth/Height) are the
  // expensive part, so callers only reach this for elements already known to be
  // candidates.
  function gripIsHidden(el) {
    const style = window.getComputedStyle(el);
    return (
      style.display === 'none' ||
      style.visibility === 'hidden' ||
      parseFloat(style.opacity) === 0 ||
      el.getAttribute('aria-hidden') === 'true' ||
      el.offsetWidth === 0 ||
      el.offsetHeight === 0
    );
  }

  function gripCollect() {
    const out = [];
    function walk(root, inShadow) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, null);
      let node = walker.currentNode;
      while (node) {
        const el = node;
        if (!el.tagName) { node = walker.nextNode(); continue; }
        const tag = el.tagName.toLowerCase();
        if (tag === 'iframe') {
          const src = el.getAttribute('src') || el.getAttribute('data-src') || '';
          let host = '';
          try { host = new URL(src, location.href).hostname; } catch (e) {}
          if (_TRACKING_HOSTS.some(p => host.includes(p))) {
            node = walker.nextNode();
            continue;
          }
        }
        const role = gripRole(el);
        if (gripIsCandidate(el, tag, role) && !gripIsHidden(el)) {
          out.push({ el: el, tag: tag, role: role, inShadow: inShadow });
        }
        if (el.shadowRoot) walk(el.shadowRoot, true);
        node = walker.nextNode();
      }
    }
    walk(document.body, false);
    return out;
  }

  // A positional index is only valid against the tree that produced it. Stamping
  // the node itself means click/type can find the element the caller was actually
  // shown, even after the page has inserted or removed siblings above it.
  //
  // Allocated once per node from a document-scoped counter, never reused: a node
  // that drops out of the candidate set (goes opacity:0, loses its role) keeps
  // its stamp, so a positional 'h' + i would later hand that same stamp to a
  // different live element and querySelector would return the stale one — the
  // duplicate-label decoy this whole change exists to close.
  function gripStamp(el) {
    let h = el.getAttribute('data-grip-h');
    if (!h) {
      window.__gripHandleSeq = (window.__gripHandleSeq || 0) + 1;
      h = 'h' + window.__gripHandleSeq;
      el.setAttribute('data-grip-h', h);
    }
    return h;
  }
"""

DISCOVER_ELEMENTS_JS = """
(function() {
""" + _COLLECT_CANDIDATES_JS + """
  return JSON.stringify(gripCollect().map(function (c, i) {
    const el = c.el;
    const rect = el.getBoundingClientRect();
    return {
      index: i,
      handle: gripStamp(el),
      tag: c.tag,
      role: c.role || c.tag,
      text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 120),
      placeholder: el.getAttribute('placeholder') || null,
      // el.href resolves relative URLs against the document for us. Only
      // fetchable schemes: mailto:/javascript:/tel:/#fragment are not pages.
      href: (function () {
        if (c.tag !== 'a') return null;
        const raw = el.getAttribute('href');
        if (!raw || raw.startsWith('#')) return null;
        const abs = el.href;
        return /^https?:/i.test(abs) ? abs : null;
      })(),
      inShadowDom: c.inShadow,
      cx: Math.round(rect.left + rect.width / 2),
      cy: Math.round(rect.top + rect.height / 2)
    };
  }));
})();
"""


# Resolving by stamped handle rather than by position: the index that DISCOVER
# produced describes a tree that may no longer exist by the time the agent acts.
# The tag+text check catches the remaining case where a page reuses our attribute
# or swaps the node underneath it — a wrong click is worse than a failed one, so
# a mismatch is reported rather than performed.
_RESOLVE_JS = """
  // querySelector stops at shadow boundaries, but discovery walks into open
  // roots, so anything it stamped there would otherwise resolve to not_found.
  function gripQuery(root, sel) {
    const hit = root.querySelector(sel);
    if (hit) return hit;
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) {
        const deep = gripQuery(el.shadowRoot, sel);
        if (deep) return deep;
      }
    }
    return null;
  }

  function gripResolve(handle, expectedTag, expectedText) {
    const el = gripQuery(document, '[data-grip-h="' + handle + '"]');
    if (!el) return { el: null, reason: 'not_found' };
    const tag = el.tagName.toLowerCase();
    if (expectedTag && tag !== expectedTag) return { el: null, reason: 'identity_mismatch' };
    if (expectedText) {
      const actual = (el.innerText || el.value || el.getAttribute('aria-label') || '')
        .trim().slice(0, 120);
      if (actual !== expectedText) return { el: null, reason: 'identity_mismatch' };
    }
    return { el: el, reason: '' };
  }
"""

CLICK_ELEMENT_JS = """
function(handle, expectedTag, expectedText) {
""" + _RESOLVE_JS + """
  const r = gripResolve(handle, expectedTag, expectedText);
  if (!r.el) return { ok: false, reason: r.reason };
  r.el.click();
  return { ok: true, reason: '' };
}
"""


TYPE_ELEMENT_JS = """
function(handle, text, expectedTag, expectedText) {
""" + _RESOLVE_JS + """
  const r = gripResolve(handle, expectedTag, expectedText);
  if (!r.el) return { ok: false, reason: r.reason };
  const el = r.el;
  // A link resolving here means the caller matched the wrong thing, and silently
  // typing nowhere would hide that.
  const tag = el.tagName.toLowerCase();
  if (!(tag === 'input' || tag === 'textarea' || el.isContentEditable)) {
    return { ok: false, reason: 'not_typable' };
  }
  el.focus();
  el.value = '';
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.value = text;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return { ok: true, reason: '' };
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
