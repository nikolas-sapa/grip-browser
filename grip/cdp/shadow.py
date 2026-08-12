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
  // 'password' here is a security boundary, not a style choice: gripOwnText
  // below falls back to el.value whenever a type is not in this set, and
  // el.value on a password field is exactly what the user typed. Without
  // this, a typed password lands in every snapshot's element text, gets sent
  // to the LLM, and is written to trace output (trace's `type` redaction
  // does not cover this path — it only ever sees the *action* input, not
  // the DOM value discovery re-reads). This is also the set gripCollect's
  // element-state capture (below) reuses to decide which inputs' current
  // value is safe to surface at all — one list, so a type added for one
  // purpose is automatically excluded from the other.
  const _GRIP_NO_VALUE_TYPES = new Set([
    'checkbox', 'radio', 'file', 'submit', 'button', 'reset', 'image', 'hidden',
    'password'
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

  // SVGElement has neither .innerText nor .value — an icon built from
  // <svg><title>Close</title>...</svg> names itself only through that
  // <title> child (the SVG spec's own accessible-name mechanism), which
  // gripIsSvgCandidate above treats as candidacy-worthy but the plain
  // innerText/value/aria-label chain below has no way to read.
  function gripSvgTitleText(el) {
    if (typeof SVGElement === 'undefined' || !(el instanceof SVGElement)) return '';
    const t = el.querySelector && el.querySelector(':scope > title');
    return t ? (t.textContent || '').trim() : '';
  }

  function gripOwnText(el) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'input' && _GRIP_NO_VALUE_TYPES.has(type)) {
      return (el.innerText || '').trim();
    }
    return (
      el.innerText || el.value || el.getAttribute('aria-label') ||
      gripSvgTitleText(el) || ''
    ).trim();
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

  // preceding-sibling/parent direct text, e.g. httpbin's `Email: <input>`
  // where the "label" is a bare text node, not a <label> element at all — no
  // ARIA attribute, no `for`, nothing el.labels or aria-labelledby can see.
  // Bounded to immediate siblings and the parent's own direct text nodes, not
  // a document walk, so this stays cheap per candidate.
  function gripSiblingText(el) {
    let n = el.previousSibling;
    while (n) {
      if (n.nodeType === 3 && n.textContent.trim()) return n.textContent.trim().slice(0, 60);
      if (n.nodeType === 1 && (n.innerText || '').trim()) return n.innerText.trim().slice(0, 60);
      n = n.previousSibling;
    }
    const parent = el.parentElement;
    if (parent) {
      for (const child of parent.childNodes) {
        if (child.nodeType === 3 && child.textContent.trim()) {
          return child.textContent.trim().slice(0, 60);
        }
      }
    }
    return '';
  }

  function gripHumanize(s) {
    return (s || '').replace(/[-_]+/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').trim();
  }

  // Last-resort fallback chain for an <input>/<textarea> with no
  // aria-labelledby, aria-label or native <label> — without this, such a
  // control's snapshot text is empty and the semantic matcher (page.py's
  // _find_input) can never address it by description, forcing an agent onto
  // raw refs for what is often the most common real-world case: a label that
  // is plain text next to the input rather than a properly associated
  // <label> (httpbin's forms, e.g.).
  //
  // Deliberately NOT applied to <select>: gripAccessibleText already falls
  // back to its own text (the full option dump) when no real label exists,
  // which is a far more reliable signal than nearby prose — a <select> sitting
  // between unrelated paragraphs/links in a dense page (a filter bar, e.g.)
  // would otherwise adopt whatever text happens to precede it in the DOM.
  const _GRIP_INFER_LABEL_TAGS = new Set(['input', 'textarea']);

  function gripInferredLabel(el) {
    const placeholder = (el.getAttribute('placeholder') || '').trim();
    if (placeholder) return placeholder;
    const title = (el.getAttribute('title') || '').trim();
    if (title) return title;
    const sibling = gripSiblingText(el);
    if (sibling) return sibling;
    return gripHumanize(el.getAttribute('name') || el.id || '');
  }

  function gripAccessibleText(el) {
    const own = gripOwnText(el);
    let label = gripLabelledByText(el) ||
      (el.getAttribute('aria-label') || '').trim() ||
      gripNativeLabelText(el);
    if (!label && _GRIP_INFER_LABEL_TAGS.has(el.tagName.toLowerCase())) {
      label = gripInferredLabel(el);
    }
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
    'a','button','input','select','textarea','details','summary','canvas'
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

  // role/aria-label/tabindex-style attributes already make an SVG element a
  // candidate through the INTERACTIVE_ROLES check above regardless of tag —
  // this only covers the remaining gap: an icon-only SVG shape (a chart
  // segment, a map region, a bare icon button built from <svg>/<path>/<g>
  // with no role at all) that names itself only via aria-label or a direct
  // <title> child, which is the SVG spec's own accessible-name mechanism and
  // has no HTML equivalent gripIsCandidate already looks for.
  function gripIsSvgCandidate(el) {
    if (typeof SVGElement === 'undefined' || !(el instanceof SVGElement)) return false;
    if (el.hasAttribute('aria-label')) return true;
    return !!(el.querySelector && el.querySelector(':scope > title'));
  }

  function gripIsCandidate(el, tag, role) {
    return INTERACTIVE_TAGS.has(tag) || INTERACTIVE_ROLES.has(role) || gripIsSvgCandidate(el);
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

  // A combobox-shaped trigger reports itself (with whatever options are
  // already in the DOM) so page.py's click-and-re-snapshot loop can drive it
  // without re-deriving this detection itself. Gated on the element already
  // being a candidate (role=combobox/listbox, or a plain <button>/[role=button]
  // carrying aria-haspopup/aria-expanded, both already candidates via
  // INTERACTIVE_TAGS/INTERACTIVE_ROLES above) rather than admitting a whole
  // new class of element: a bare `<div aria-haspopup>` with no other
  // interactive signal is rare in practice and adding it would grow
  // DISCOVER's row set for a case the flag on an already-listed row already
  // covers.
  function gripComboboxInfo(el, role) {
    const hasPopup = el.hasAttribute('aria-haspopup');
    const hasExpanded = el.hasAttribute('aria-expanded');
    if (role !== 'combobox' && role !== 'listbox' && !hasPopup && !hasExpanded) return null;
    const expanded = el.getAttribute('aria-expanded') === 'true';
    // aria-controls/aria-owns is how a trigger points at its (possibly
    // detached-looking, position:absolute) popup listbox — the options only
    // exist to report when that popup is already in the DOM, which is the
    // scope this JS half owns; page.py drives opening it first if it isn't.
    const ownedId = (el.getAttribute('aria-controls') || el.getAttribute('aria-owns') || '')
      .trim().split(/\\s+/)[0];
    const optionsRoot = ownedId ? document.getElementById(ownedId) : null;
    let options = null;
    if (optionsRoot) {
      options = Array.prototype.slice
        .call(optionsRoot.querySelectorAll('[role="option"], option'))
        .slice(0, 50)
        .map(function (o) { return (o.innerText || o.textContent || '').trim().slice(0, 80); })
        .filter(Boolean);
    }
    return { expanded: expanded, options: options };
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
          // Cross-frame traversal is out of scope here — the walker cannot see
          // inside the iframe's own document — so a stub row is emitted instead
          // of silently dropping whatever content lives there.
          out.push({ el: el, tag: tag, role: 'iframe', inShadow: inShadow, isIframe: true });
          node = walker.nextNode();
          continue;
        }
        const role = gripRole(el);
        let addedAsCandidate = false;
        if (gripIsCandidate(el, tag, role) && !gripIsHidden(el)) {
          out.push({
            el: el, tag: tag, role: role, inShadow: inShadow,
            combobox: gripComboboxInfo(el, role),
          });
          addedAsCandidate = true;
        }
        if (el.shadowRoot) {
          walk(el.shadowRoot, true);
        } else if (window.__gripClosedRoots && window.__gripClosedRoots.has(el)) {
          // Captured by CLOSED_SHADOW_PATCH_JS (see its own comment for why
          // that early patch is the only way to ever see a closed root at
          // all). Walked exactly like an open root once captured — the point
          // of stashing the reference is that its content stays as fully
          // addressable as anything else on the page, not merely detectable.
          try {
            walk(window.__gripClosedRoots.get(el), true);
          } catch (e) {
            // Reachable only if the captured root itself stopped being
            // walkable between capture and this pass (the host was removed
            // and its root detached from the live tree, e.g.) — a real,
            // if rare, failure, unlike "we never saw this host's
            // attachShadow call at all", which leaves no WeakMap entry and
            // is not detectable from page JS at all. A stub row says content
            // exists here but couldn't be read, instead of the element
            // silently vanishing from the snapshot.
            if (!addedAsCandidate) {
              out.push({
                el: el, tag: tag, role: role, inShadow: inShadow,
                closedShadowUnreadable: true,
              });
            }
          }
        }
        node = walker.nextNode();
      }
    }
    walk(document.body, false);
    return out;
  }

  // Per-element interaction state for DISCOVER's payload — cheap attribute/
  // property reads only, no layout. `value` is capped well below the 120-char
  // text cap: a snapshot line exists to say "this field has something in it",
  // not to carry its full contents, and a password field's value is withheld
  // outright rather than handed to whatever reads the snapshot. Reuses
  // _GRIP_NO_VALUE_TYPES (defined above, in _ACCESSIBLE_TEXT_JS) rather than a
  // second list: a type excluded from the label formula for the same "not
  // user content" reason must not silently reappear here through a copy that
  // drifted out of sync with it.
  function gripElementState(el) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    const disabled = el.disabled === true || el.getAttribute('aria-disabled') === 'true';
    const required = el.required === true || el.getAttribute('aria-required') === 'true';

    let checked = null;
    if (tag === 'input' && (type === 'checkbox' || type === 'radio')) {
      checked = !!el.checked;
    } else if (['checkbox', 'switch'].includes(el.getAttribute('role') || '')) {
      checked = el.getAttribute('aria-checked') === 'true';
    }

    let selected = null;
    if (tag === 'option') {
      selected = !!el.selected;
    } else if (el.hasAttribute('aria-selected')) {
      selected = el.getAttribute('aria-selected') === 'true';
    }

    let value = null;
    if ((tag === 'input' || tag === 'textarea') && !_GRIP_NO_VALUE_TYPES.has(type)) {
      value = (el.value || '').slice(0, 80) || null;
    } else if (tag === 'select') {
      const opt = el.options && el.options[el.selectedIndex];
      value = opt ? (opt.text || opt.value || '').slice(0, 80) || null : null;
    }

    return { disabled: disabled, required: required, checked: checked,
             selected: selected, value: value };
  }

  // Compact stand-in for an iframe row: enough to tell the agent content is
  // hidden there and where, without attempting to read across the boundary.
  function gripIframeSummary(el) {
    const parts = [];
    const src = el.getAttribute('src') || el.getAttribute('data-src') || '';
    if (src) parts.push('src=' + src);
    const title = el.getAttribute('title') || '';
    if (title) parts.push('title=' + title);
    const name = el.getAttribute('name') || '';
    if (name) parts.push('name=' + name);
    return parts.join(' ');
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
    const seen = (window.__gripStamped = window.__gripStamped || new WeakSet());
    const h = el.getAttribute('data-grip-h');
    // Only ever trust a data-grip-h value this session itself set. A page can
    // pre-author the attribute to any string — including one crafted to break
    // the '[data-grip-h="..."]' selector RESOLVE builds from it (handled by
    // CSS.escape there), or, more dangerously, a numeric-looking value ("h3")
    // that collides with a handle already minted for a different live
    // element. Format-checking alone cannot rule that second case out, so
    // membership in this session's own WeakSet is the only thing trusted;
    // anything else is treated as unstamped and reassigned from the counter.
    if (h && seen.has(el)) return h;
    window.__gripHandleSeq = (window.__gripHandleSeq || 0) + 1;
    const fresh = 'h' + window.__gripHandleSeq;
    el.setAttribute('data-grip-h', fresh);
    seen.add(el);
    return fresh;
  }
"""

# Second pass over the DOM for elements that are clickable only via a JS
# addEventListener('click') — no role, no tabindex, no native semantics — e.g.
# `<div class="item" data-id="4">` built by client-side JS. Page script cannot
# see its own listeners, so this only *narrows the field*: it is cheap,
# no-layout ranking of "plausibly interactive" nodes. The actual listener check
# happens in Python (grip/page.py) via CDP DOMDebugger.getEventListeners, which
# is per-node and therefore the part that must stay bounded.
#
# Kept as a wholly separate eval from DISCOVER_ELEMENTS_JS/gripCollect rather
# than merged into it: DISCOVER_ELEMENTS_JS's output is pinned byte-for-byte
# against a frozen baseline (tests/integration/test_discover_elements_perf_parity.py),
# and its shape (the tag/role candidate set) is unrelated to this heuristic
# working or not. Extending it would either break that pin or force it to also
# encode CDP-listener knowledge it has no way to verify client-side.
_PROBE_CANDIDATES_JS = _COLLECT_CANDIDATES_JS + """
  // Two bounds, not one. PRE_RANK_LIMIT caps how many elements get a cheap,
  // no-layout score (attribute/text checks only — safe to run over a large
  // set). MAX_LISTENER_PROBE_NODES caps how many of the top-scored survivors
  // go on to the expensive, layout-forcing gripIsHidden() + cursor check
  // before being handed to Python for the actual (per-node CDP) listener
  // probe. Ranking on cheap signals first, THEN paying for layout only on the
  // pre-ranked shortlist, is what keeps a large page from being walked with
  // getComputedStyle on every leaf-text node it contains.
  const PRE_RANK_LIMIT = __GRIP_PRE_RANK_LIMIT__;
  const MAX_LISTENER_PROBE_NODES = __GRIP_MAX_LISTENER_PROBE_NODES__;

  // Prose/text-flow tags are almost never themselves a delegated click target
  // (the click target is a card/row/item wrapping them) and are by far the
  // most numerous own-text leaves on a real content page. Excluding them is
  // what keeps PRE_RANK_LIMIT from being spent entirely on paragraph runs.
  const _PROBE_DENY_TAGS = new Set([
    'html','head','body','script','style','template','noscript','meta','link',
    'title','p','pre','blockquote','code','b','i','strong','em','small','sup',
    'sub','br','hr','option','style'
  ]);

  // "Not a pure container": true only when the element has its own direct
  // text node, not text that lives entirely inside child elements. A wrapper
  // div built purely to lay out children (e.g. `<div id="list">`) never has
  // one and is excluded before anything layout-forcing runs.
  function gripHasOwnText(el) {
    for (const n of el.childNodes) {
      if (n.nodeType === 3 && n.textContent && n.textContent.trim().length > 0) return true;
    }
    return false;
  }

  // Cheap (no getComputedStyle/getBoundingClientRect) score used only to
  // shortlist candidates down to PRE_RANK_LIMIT before any layout is forced.
  function gripCheapScore(el) {
    let s = 0;
    if (el.hasAttribute('onclick')) s += 3;
    if (el.tabIndex >= 0) s += 2;
    for (const a of el.attributes) { if (a.name.startsWith('data-')) { s += 2; break; } }
    if ((el.className || '').length > 0) s += 1;
    const ownLen = (el.textContent || '').trim().length;
    if (ownLen > 0 && ownLen <= 60) s += 1;
    return s;
  }

  function gripCollectProbeCandidates() {
    const shortlist = [];
    function walk(root, inShadow) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, null);
      let node = walker.currentNode;
      while (node) {
        const el = node;
        if (el.tagName) {
          const tag = el.tagName.toLowerCase();
          if (!_PROBE_DENY_TAGS.has(tag)) {
            const role = gripRole(el);
            if (!gripIsCandidate(el, tag, role) && gripHasOwnText(el)) {
              shortlist.push({ el: el, tag: tag, role: role, inShadow: inShadow,
                                score: gripCheapScore(el) });
            }
          }
          if (el.shadowRoot) walk(el.shadowRoot, true);
        }
        node = walker.nextNode();
      }
    }
    walk(document.body, false);

    // Stable sort (Array#sort is stable per spec): ties keep DOM order, so a
    // page with nothing but zero-score candidates degrades to the old
    // DOM-order behaviour rather than an arbitrary one.
    shortlist.sort(function (a, b) { return b.score - a.score; });
    const ranked = shortlist.slice(0, PRE_RANK_LIMIT);

    // Only now — on a shortlist bounded by PRE_RANK_LIMIT, not the whole page
    // — do the layout-forcing calls gripIsHidden() needs. cursor:pointer is
    // read off the same getComputedStyle call gripIsHidden already makes, so
    // it is a free extra signal here, not an extra layout pass (this is the
    // one place cursor:pointer is used: as one ranking signal among several,
    // never as the sole admission gate).
    const out = [];
    for (const c of ranked) {
      const el = c.el;
      if (gripIsHidden(el)) continue;
      const style = window.getComputedStyle(el);
      let score = c.score;
      if (style.cursor === 'pointer') score += 2;
      out.push({ el: el, tag: c.tag, role: c.role, inShadow: c.inShadow, score: score });
    }
    out.sort(function (a, b) { return b.score - a.score; });
    return out.slice(0, MAX_LISTENER_PROBE_NODES).map(function (c) {
      const el = c.el;
      const rect = el.getBoundingClientRect();
      return {
        handle: gripStamp(el),
        tag: c.tag,
        role: c.role || c.tag,
        text: gripAccessibleText(el).slice(0, 120),
        inShadowDom: c.inShadow,
        cx: Math.round(rect.left + rect.width / 2),
        cy: Math.round(rect.top + rect.height / 2)
      };
    });
  }
"""

# Named, not magic: PRE_RANK_LIMIT bounds the cheap (no-layout) scoring pass,
# MAX_LISTENER_PROBE_NODES bounds the expensive per-node CDP
# DOMDebugger.getEventListeners calls grip/page.py makes against the result of
# this JS. Both are interpolated into the JS text (see below) so there is one
# Python-level source of truth a test can assert against, rather than a number
# duplicated by hand between the .py and .js text.
GRIP_PRE_RANK_LIMIT = 150
GRIP_MAX_LISTENER_PROBE_NODES = 40

_PROBE_CANDIDATES_JS = (
    _PROBE_CANDIDATES_JS
    .replace("__GRIP_PRE_RANK_LIMIT__", str(GRIP_PRE_RANK_LIMIT))
    .replace("__GRIP_MAX_LISTENER_PROBE_NODES__", str(GRIP_MAX_LISTENER_PROBE_NODES))
)

# Standalone eval: returns the ranked, bounded shortlist as JSON. Page.py sends
# this after DISCOVER_ELEMENTS_JS and only pays for the CDP listener probe on
# whatever comes back (at most MAX_LISTENER_PROBE_NODES elements).
PROBE_CLICKABLE_JS = """
(function() {
""" + _PROBE_CANDIDATES_JS + """
  return JSON.stringify(gripCollectProbeCandidates());
})();
"""


DISCOVER_ELEMENTS_JS = """
(function() {
""" + _COLLECT_CANDIDATES_JS + """
  return JSON.stringify(gripCollect().map(function (c, i) {
    const el = c.el;
    const rect = el.getBoundingClientRect();
    const state = gripElementState(el);
    return {
      index: i,
      handle: gripStamp(el),
      tag: c.tag,
      role: c.role || c.tag,
      text: c.isIframe ? gripIframeSummary(el) : gripAccessibleText(el).slice(0, 120),
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
      cy: Math.round(rect.top + rect.height / 2),
      // Canvas has no DOM structure to click into — a chart, a map, a
      // canvas-based editor is one opaque box — so its own rect (not just
      // the centre point every row already gets) is what lets a caller
      // choose a deliberate offset inside it rather than always hitting dead
      // centre. null for every other tag, same null-when-not-applicable
      // pattern `href` above already uses. Named canvasWidth/canvasHeight,
      // not width/height: RawElement (grip/security/sanitizer.py) already
      // reads a dead `width`/`height` JSON key here (`d.get("width", 1)`,
      // left over from a deleted filter — see that file's comment) that
      // DISCOVER never used to populate; colliding with it would have
      // turned every row's RawElement.width from its documented "always 1"
      // default into this field's null on every non-canvas row.
      canvasWidth: c.tag === 'canvas' ? Math.round(rect.width) : null,
      canvasHeight: c.tag === 'canvas' ? Math.round(rect.height) : null,
      isCombobox: !!c.combobox,
      comboboxExpanded: c.combobox ? c.combobox.expanded : null,
      comboboxOptions: c.combobox ? c.combobox.options : null,
      // See gripCollect's walk(): true only for the rare case a closed
      // shadow root was captured but its content could not be walked.
      closedShadowUnreadable: !!c.closedShadowUnreadable,
      disabled: state.disabled,
      required: state.required,
      checked: state.checked,
      selected: state.selected,
      value: state.value
    };
  }));
})();
"""


# Standalone, not part of the collector pipeline above: must be installed via
# CDP Page.addScriptToEvaluateOnNewDocument (page.py's call — see the module
# note below), not Runtime.evaluate at snapshot time. `mode: 'closed'` is
# built precisely so that a page's own author-mode script gets no reference
# back to the root once attachShadow() returns; the only way anything outside
# that call site can ever see one is to already be watching when the call
# happens. Page.addScriptToEvaluateOnNewDocument is the one CDP mechanism
# that runs before ANY other script on a document, including a component
# library's own top-of-bundle code that calls attachShadow({mode: 'closed'})
# during its very first render — patching from inside DISCOVER_ELEMENTS_JS
# (a Runtime.evaluate that only ever runs long after load) is too late for
# every closed root a page created before that eval fired.
#
# What page.py must call, and where:
#   - Send `{"expression": CLOSED_SHADOW_PATCH_JS}` via
#     `Page.addScriptToEvaluateOnNewDocument` — grip/page.py:798's
#     `asyncio.gather(...)` inside goto() is the existing "armed once per
#     navigation, before Page.navigate is sent" call site (it already sends
#     Page.enable/Network.enable/Runtime.enable/_ensure_fetch_interception/
#     _ensure_popup_blocking there, for the same "must exist before the
#     document's own scripts run" reason). This survives navigations on the
#     same target automatically (CDP re-applies it on every new document), so
#     it only needs to be registered once per Page lifetime, not per goto().
#   - _ensure_initialized() (grip/page.py:502) is the matching hook for a
#     Page reached without goto() (a remote CDP attach, an adopted target) —
#     same reasoning _ensure_fetch_interception already gets there. A Page
#     already showing a document by the time this runs has already missed
#     any closed root created before attach; nothing can recover that one
#     retroactively, same limitation _ensure_fetch_interception has for
#     requests already in flight.
#
# Idempotent (`if (window.__gripClosedRoots) return`) so re-registering it
# (a second goto() on the same Page, e.g.) is harmless rather than wrapping
# attachShadow twice and chaining two patched implementations.
#
# WeakMap, not Map, and keyed by the *host* element rather than tagging it
# with a data- attribute (a page's own code could read, clear, or collide
# with that) or keying by the root itself (nothing downstream ever needs to
# look a root up by itself — every consumer already holds the host from its
# own DOM walk). An unmounted/GC'd host must not keep its closed root
# artificially alive, or a long-lived agent session leaks one entry per
# closed-shadow component the page ever created and destroyed.
#
# Limitation this cannot close: a page whose closed root was created before
# this script had a chance to run (patch registered too late, or a target
# grip never controlled early enough) leaves no signal in page JS at all —
# not even "something is hidden here" — because the only fact a closed root
# is required to hide is its own existence from anything that wasn't
# watching attachShadow() at the moment it was called. gripCollect's
# closedShadowUnreadable marker (grip/cdp/shadow.py's gripCollect) only
# fires for a root THIS patch did capture but could not later walk (the host
# was removed and its root detached in between) — a different, narrower
# failure than "never captured at all", which has no marker because it has
# no detectable trace.
CLOSED_SHADOW_PATCH_JS = """
(function () {
  if (window.__gripClosedRoots) return;
  window.__gripClosedRoots = new WeakMap();
  const nativeAttachShadow = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function (init) {
    const root = nativeAttachShadow.call(this, init);
    if (init && init.mode === 'closed') {
      window.__gripClosedRoots.set(this, root);
    }
    return root;
  };
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
  //
  // CSS.escape(handle) rather than string concat: gripStamp only ever mints
  // handles matching /^h\\d+$/, but a page can still pre-author its own
  // data-grip-h attribute containing e.g. `"]` before we ever stamp anything
  // — unescaped, that breaks out of the attribute selector and throws inside
  // querySelector, which resolve()/click()/type() would otherwise surface as
  // an unhandled CDP exception rather than a clean not_found.
  function gripQuery(root, handle) {
    const sel = '[data-grip-h="' + CSS.escape(handle) + '"]';
    const hit = root.querySelector(sel);
    if (hit) return hit;
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) {
        const deep = gripQuery(el.shadowRoot, handle);
        if (deep) return deep;
      }
    }
    return null;
  }

  function gripResolve(handle, expectedTag, expectedText) {
    const el = gripQuery(document, handle);
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
  const el = r.el;

  if (el.disabled === true || el.getAttribute('aria-disabled') === 'true') {
    return { ok: false, reason: 'disabled' };
  }

  // elementFromPoint only sees what is actually painted, so an off-screen rect
  // can never pass the hit test below — bring it on-screen and re-read the
  // rect first, rather than reporting "off-screen" as "obscured".
  let rect = el.getBoundingClientRect();
  const offscreen = rect.width === 0 || rect.height === 0 ||
    rect.bottom <= 0 || rect.right <= 0 ||
    rect.top >= window.innerHeight || rect.left >= window.innerWidth;
  if (offscreen) {
    el.scrollIntoView({ block: 'center', inline: 'center' });
    rect = el.getBoundingClientRect();
  }

  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  // A shadow-DOM element's own root does the hit test, not `document` —
  // document.elementFromPoint stops at the shadow host and would report every
  // shadow control as obscured by its own host.
  const hitRoot = el.getRootNode();
  const hitFn = (hitRoot && typeof hitRoot.elementFromPoint === 'function')
    ? hitRoot.elementFromPoint.bind(hitRoot)
    : document.elementFromPoint.bind(document);
  const hit = hitFn(cx, cy);
  // null means the point could not be hit-tested (still off-canvas, zero
  // size) — that is "couldn't check", not "obscured". An ancestor hit (a
  // wrapping <label>/<a>) or a descendant hit (an icon inside the button)
  // still clicks through the real element and must not report obscured.
  if (hit && !(el.contains(hit) || hit.contains(el))) {
    const cls = hit.getAttribute('class');
    return {
      ok: false, reason: 'obscured',
      occluder: hit.tagName.toLowerCase() + (cls ? '.' + cls.trim().split(/\\s+/).join('.') : '')
    };
  }

  el.click();
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

  if (el.isContentEditable) {
    el.textContent = '';
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.textContent = text;
    el.dispatchEvent(new Event('input', { bubbles: true }));
  } else {
    // React/Vue install their own `value` setter on the instance so their
    // change-detection can see writes `el.value = x` makes — but that means
    // it never sees ours, since we are not going through their setter. Calling
    // the native prototype's setter directly bypasses the instance override
    // the same way a real keystroke would, so the framework's own onChange
    // still fires.
    const proto = tag === 'textarea'
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype;
    const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    function setValue(v) {
      if (nativeSetter) { nativeSetter.call(el, v); } else { el.value = v; }
    }
    setValue('');
    el.dispatchEvent(new Event('input', { bubbles: true }));
    // keydown/keyup bracket the value change so typeahead/autocomplete widgets
    // that listen for real keystrokes (not just 'input') still fire.
    el.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true }));
    setValue(text);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
  }
  el.dispatchEvent(new Event('change', { bubbles: true }));

  const actual = el.isContentEditable ? (el.textContent || '') : el.value;
  if (actual !== text) {
    // A controlled input legitimately rewriting what it was given (masking,
    // case transform, maxlength) looks identical to typing simply not taking
    // — the observed value is returned so the caller can tell the two apart
    // instead of getting a bare false.
    return { ok: false, reason: 'value_mismatch:' + String(actual).slice(0, 80) };
  }
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
  // Window-only scrolling misses inner scrollable panes — virtual lists,
  // infinite-scroll feeds, chat panels — built as their own overflow:auto/
  // scroll container inside a fixed-height ancestor, which never grows past
  // its own clientHeight no matter how far the window scrolls. Re-picked on
  // every call rather than cached: the DOM this runs against is exactly the
  // one page.py's _interact_to_reveal/_await_block_growth is trying to grow,
  // so a container that qualified on the last call may have plateaued or
  // been replaced by the time this one runs.
  function isScrollable(el) {
    if (!el || el === document.documentElement || el === document.body) return false;
    if (el.scrollHeight - el.clientHeight < 40) return false;
    const style = window.getComputedStyle(el);
    return /(auto|scroll)/.test(style.overflowY);
  }

  // Largest-area visible scrollable pane wins — no anchor element to walk up
  // from here (this JS takes no argument; callers just want "reveal more"),
  // so the pane most likely to be the page's actual content list, rather
  // than a small nested widget that happens to also overflow, is the best
  // guess without one.
  let target = null;
  let bestArea = 0;
  for (const el of document.querySelectorAll('*')) {
    if (!isScrollable(el)) continue;
    const r = el.getBoundingClientRect();
    const area = r.width * r.height;
    if (area > bestArea) { bestArea = area; target = el; }
  }

  if (target) {
    // Stepwise, not a jump straight to scrollHeight: a virtual list only
    // renders/loads the rows its own IntersectionObserver/scroll listener
    // actually sees pass by, so jumping straight to the end can leave the
    // middle of the list unrendered even though scrollTop reports the max.
    // page.py's _interact_to_reveal already re-calls this JS and checks
    // block-count growth after each call (its own plateau/growth-detection
    // loop) — one clientHeight step per call is what that loop expects to
    // drive, not a second growth-detection loop invented here.
    target.scrollTop = Math.min(target.scrollTop + target.clientHeight, target.scrollHeight);
  } else {
    window.scrollTo(0, document.body.scrollHeight);
  }
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
