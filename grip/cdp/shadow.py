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
      const tag = el.tagName.toLowerCase();
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
