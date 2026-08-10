# The single definition of an element's accessible text, shared by DISCOVER (which
# writes it into the snapshot an LLM reads) and RESOLVE (which recomputes it live
# to verify click()/type()/select() are still touching the element the snapshot
# described). Two independent formulas here would be exactly the bug this file's
# top comment describes for candidate rules — computed once, drift becomes
# unrepresentable.
#
# Precedence follows the browser's own accessible-name algorithm rather than an
# invented order: aria-labelledby, then aria-label, both before any native
# association, because an author who set either ARIA attribute is overriding the
# visible label on purpose — a mismatched sibling <label> must not win over it.
# Only below that does a native <label for="id">/wrapping <label> apply, and
# only to form controls (input/select/textarea) — that association does not
# exist for a button or link, whose own text was already the right answer.
_ACCESSIBLE_TEXT_JS = """
  const _GRIP_FORM_TAGS = new Set(['input', 'select', 'textarea']);
  // A checkbox/radio/file/submit/button's `.value` is markup boilerplate ("on",
  // a filename, a caption already covered by innerText), not user content —
  // folding it into a label would only add noise and bytes to every snapshot.
  const _GRIP_NO_VALUE_TYPES = new Set([
    'checkbox', 'radio', 'file', 'submit', 'button', 'reset', 'image', 'hidden'
  ]);

  function gripLabelledByText(el) {
    const ids = (el.getAttribute('aria-labelledby') || '').trim();
    if (!ids) return '';
    const root = el.getRootNode();
    if (typeof root.getElementById !== 'function') return '';
    return ids.split(/\\s+/).map(function (id) {
      const ref = root.getElementById(id);
      return ref ? (ref.innerText || ref.textContent || '').trim() : '';
    }).filter(Boolean).join(' ');
  }

  // el.labels covers both `<label for="id">` and a wrapping `<label>` in one
  // browser-computed call — a querySelector/getElementById walk would need
  // redoing per shadow root (they do not cross the boundary), which this file
  // exists to support, so the built-in is both simpler and actually correct here.
  function gripNativeLabelText(el) {
    if (!_GRIP_FORM_TAGS.has(el.tagName.toLowerCase())) return '';
    const labels = el.labels;
    if (!labels || !labels.length) return '';
    return Array.prototype.map.call(labels, function (l) {
      return (l.innerText || '').trim();
    }).filter(Boolean).join(' ');
  }

  function gripOwnText(el) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'input' && _GRIP_NO_VALUE_TYPES.has(type)) {
      return (el.innerText || '').trim();
    }
    return (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
  }

  // A label and the element's own text frequently overlap (a wrapping <label>
  // whose innerText already includes the checkbox's own text). Emitting both
  // verbatim would duplicate that text in every payload it appears in.
  function gripCombine(label, own) {
    if (!own) return label;
    const l = label.toLowerCase(), o = own.toLowerCase();
    if (o.includes(l) || l.includes(o)) return own.length >= label.length ? own : label;
    return label + ': ' + own;
  }

  function gripAccessibleText(el) {
    const own = gripOwnText(el);
    const label = gripLabelledByText(el) ||
      (el.getAttribute('aria-label') || '').trim() ||
      gripNativeLabelText(el);
    if (!label) return own;
    // A <select>'s own text is its full option dump (every <option> label
    // concatenated) — useful when nothing else identifies the control, but
    // redundant bloat once a real label exists: the options remain
    // discoverable through select()'s own no_such_option error, so they do
    // not need to live in every snapshot payload too.
    if (el.tagName.toLowerCase() === 'select') return label;
    return gripCombine(label, own);
  }
"""

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
_COLLECT_CANDIDATES_JS = _ACCESSIBLE_TEXT_JS + """
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
    // checkVisibility accounts for the element AND its ancestors — a child of an
    // opacity:0 parent used to pass as visible here, because
    // getComputedStyle().opacity does not inherit. That let an off-screen decoy
    // sharing a visible control's label absorb clicks meant for the real one.
    if (typeof el.checkVisibility === 'function') {
      if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return true;
    } else {
      const s = window.getComputedStyle(el);
      if (s.display === 'none' || s.visibility === 'hidden' ||
          parseFloat(s.opacity) === 0) return true;
    }
    if (el.getAttribute('aria-hidden') === 'true') return true;
    if (el.offsetWidth === 0 || el.offsetHeight === 0) return true;

    // checkVisibility does no geometry and no text-colour work, so the classic
    // off-screen and invisible-text decoys survive it with a normal-sized box.
    const style = window.getComputedStyle(el);
    if (parseFloat(style.textIndent) < -500) return true;
    if (parseFloat(style.fontSize) === 0) return true;
    // transparent + background-clip:text is the gradient-text idiom and it is
    // used on primary CTAs — reading that as hidden would delete the main button.
    // ponytail: a transparent container whose child re-sets colour still reads as
    // hidden. Candidates are interactive elements, where that is rare.
    if (style.color === 'rgba(0, 0, 0, 0)' &&
        style.getPropertyValue('-webkit-background-clip') !== 'text' &&
        style.backgroundClip !== 'text') return true;

    // Document-space, not viewport: comparing against innerHeight would mark
    // every below-the-fold element hidden and gut snapshots of long pages. Only
    // fully off-canvas left/top counts.
    const r = el.getBoundingClientRect();
    if (r.right + window.scrollX <= 0 || r.bottom + window.scrollY <= 0) return true;

    return false;
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
      text: gripAccessibleText(el).slice(0, 120),
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
#
# Prepends _ACCESSIBLE_TEXT_JS so `actual` is computed by the exact same
# gripAccessibleText DISCOVER used to produce the `expectedText` callers pass
# in (el.text off the snapshot). Before this shared, RESOLVE recomputed
# identity with the old innerText/value/aria-label-only formula, so any
# control whose accessible name comes only from a <label> (a checkbox wrapped
# in one, with no own text or aria-label) mismatched on every click()/type()
# call — DISCOVER said "Accept terms", RESOLVE said "on" or "".
_RESOLVE_JS = _ACCESSIBLE_TEXT_JS + """
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
      const actual = gripAccessibleText(el).slice(0, 120);
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
  // Built rather than written as a literal: a regex literal cannot wrap, and the
  // one-line version ran past every sane line width.
  const BAD_WORDS = [
    'nav', 'menu', 'sidebar', 'footer', 'header', 'banner', 'cookie', 'consent',
    'promo', 'advert', 'subscribe', 'newsletter', 'related', 'comment', 'share',
    'social', 'breadcrumb',
  ];
  const BAD = new RegExp('(^|[-_ ])(' + BAD_WORDS.join('|') + ')([-_ ]|$)', 'i');
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
