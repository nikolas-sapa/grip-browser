"""Generates the 30 self-hosted interaction-heavy fixture pages used by
bench_llm_loop.py.

Why generated, not hand-written: 30 files sharing three templates is more likely
to stay consistent (same event wiring, same __bench_verify() contract) if it comes
from one function per template than from 30 hand-edited copies. Regenerate after
editing a template:

    .venv/bin/python benchmarks/corpus/generate_fixtures.py

Every page is a single self-contained HTML file: inline CSS, inline JS, no
external requests, no backend. They are served by `python -m http.server` (stdlib,
already used elsewhere in this repo's tooling) from benchmarks/corpus/fixtures/,
so the corpus does not rot — there is no live site on the other end to change
its markup or vanish.

Contract every fixture honors, because bench_llm_loop.py's verify step depends
on it: each page exposes `window.__bench_verify()` returning a plain bool (the
harness evaluates this expression via CDP after the agent's last action, so it
must be readable with no arguments and no async) and `window.__bench_state()`
returning a JSON-serialisable object with the raw field values, so a passing or
failing verify shows its evidence rather than a bare true/false.
"""
from __future__ import annotations

import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_BASE_CSS = """
  body { font-family: -apple-system, sans-serif; max-width: 640px; margin: 40px auto;
    padding: 0 16px; }
  fieldset { border: 1px solid #ccc; border-radius: 8px; margin-bottom: 16px; padding: 16px; }
  label { display: block; margin: 8px 0 4px; font-size: 14px; }
  input, select, textarea { width: 100%; padding: 8px; box-sizing: border-box; font-size: 14px; }
  button { padding: 10px 18px; font-size: 14px; cursor: pointer; margin-top: 8px; }
  .hidden { display: none; }
  .item { border: 1px solid #ddd; border-radius: 6px; padding: 10px; margin: 6px 0; }
  .item.selected { border-color: #006bff; background: #eef5ff; }
  table { width: 100%; border-collapse: collapse; }
  td, th { text-align: left; padding: 6px; border-bottom: 1px solid #eee; }
"""


def _page(title: str, body: str, script: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>{_BASE_CSS}</style></head>
<body>
<h2>{title}</h2>
{body}
<script>{script}</script>
</body></html>
"""


# ---------------------------------------------------------------------------
# Category 1: multi-step FORMS. Single document, no navigation. 6 fields is
# the "4+ same-document actions" floor with margin for a fumbled first click.
# ---------------------------------------------------------------------------

FORM_FIELD_SETS = [
    # (form_id, fields: list of (name, kind, label, options|None), target values)
    ["full_name", "email", "phone", "role", "newsletter", "notes"],
]


def make_form_task(n: int, target: dict) -> str:
    body = """
<form id="f">
  <label for="full_name">Full name</label>
  <input id="full_name" name="full_name" type="text">
  <label for="email">Email</label>
  <input id="email" name="email" type="email">
  <label for="phone">Phone</label>
  <input id="phone" name="phone" type="tel">
  <label for="role">Role</label>
  <select id="role" name="role">
    <option value="">Select...</option>
    <option value="engineer">Engineer</option>
    <option value="designer">Designer</option>
    <option value="manager">Manager</option>
    <option value="other">Other</option>
  </select>
  <label><input id="newsletter" name="newsletter" type="checkbox"> Subscribe to newsletter</label>
  <label for="notes">Notes</label>
  <textarea id="notes" name="notes" rows="3"></textarea>
  <button type="button" id="submit_btn">Review &amp; Submit</button>
</form>
<div id="result" class="hidden">Submitted.</div>
"""
    script = f"""
document.getElementById('submit_btn').addEventListener('click', function() {{
  document.getElementById('result').classList.remove('hidden');
}});
window.__bench_state = function() {{
  return {{
    full_name: document.getElementById('full_name').value,
    email: document.getElementById('email').value,
    phone: document.getElementById('phone').value,
    role: document.getElementById('role').value,
    newsletter: document.getElementById('newsletter').checked,
    notes: document.getElementById('notes').value,
    submitted: !document.getElementById('result').classList.contains('hidden')
  }};
}};
window.__bench_verify = function() {{
  var s = window.__bench_state();
  var t = {json.dumps(target)};
  return s.full_name === t.full_name && s.email === t.email &&
         s.phone === t.phone && s.role === t.role &&
         s.newsletter === t.newsletter && s.submitted === true;
}};
"""
    return _page(f"Form task {n}", body, script)


# ---------------------------------------------------------------------------
# Category 2: SPA state-dependent flows (filter / sort / paginate). Client-
# side only, no reload; state lives in a JS object.
# ---------------------------------------------------------------------------

CATEGORIES_POOL = ["Electronics", "Books", "Home", "Sports", "Toys"]


def make_spa_task(n: int, items: list[dict], target: dict) -> str:
    body = f"""
<label for="filter">Category</label>
<select id="filter">
  <option value="all">All</option>
  {"".join(f'<option value="{c}">{c}</option>' for c in CATEGORIES_POOL)}
</select>
<label for="sort">Sort by price</label>
<select id="sort">
  <option value="none">Default</option>
  <option value="asc">Price: low to high</option>
  <option value="desc">Price: high to low</option>
</select>
<div id="list"></div>
<button type="button" id="prev">Previous page</button>
<span id="pageno">Page 1</span>
<button type="button" id="next">Next page</button>
"""
    script = f"""
var ITEMS = {json.dumps(items)};
var PAGE_SIZE = 3;
var state = {{ filter: 'all', sort: 'none', page: 1, selected: null }};
function render() {{
  var rows = ITEMS.filter(function(i) {{
    return state.filter === 'all' || i.category === state.filter;
  }});
  if (state.sort === 'asc') rows.sort(function(a,b) {{ return a.price - b.price; }});
  if (state.sort === 'desc') rows.sort(function(a,b) {{ return b.price - a.price; }});
  var maxPage = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  if (state.page > maxPage) state.page = maxPage;
  var start = (state.page - 1) * PAGE_SIZE;
  var pageRows = rows.slice(start, start + PAGE_SIZE);
  var el = document.getElementById('list');
  el.innerHTML = '';
  pageRows.forEach(function(it) {{
    var d = document.createElement('div');
    d.className = 'item' + (state.selected === it.id ? ' selected' : '');
    d.dataset.id = it.id;
    d.textContent = it.name + ' — ' + it.category + ' — $' + it.price;
    d.addEventListener('click', function() {{ state.selected = it.id; render(); }});
    el.appendChild(d);
  }});
  document.getElementById('pageno').textContent = 'Page ' + state.page + ' of ' + maxPage;
}}
document.getElementById('filter').addEventListener('change', function(e) {{
  state.filter = e.target.value; state.page = 1; render();
}});
document.getElementById('sort').addEventListener('change', function(e) {{
  state.sort = e.target.value; render();
}});
document.getElementById('next').addEventListener('click', function() {{
  state.page += 1; render();
}});
document.getElementById('prev').addEventListener('click', function() {{
  state.page = Math.max(1, state.page - 1); render();
}});
render();
window.__bench_state = function() {{ return state; }};
window.__bench_verify = function() {{
  var t = {json.dumps(target)};
  return state.filter === t.filter && state.sort === t.sort &&
         state.page === t.page && state.selected === t.selected;
}};
"""
    return _page(f"Catalog task {n}", body, script)


# ---------------------------------------------------------------------------
# Category 3: checkout-style wizards. Single document, step-gated by JS
# show/hide, each step requires filling fields before "Next" is enabled.
# ---------------------------------------------------------------------------

def make_wizard_task(n: int, target: dict) -> str:
    body = """
<div id="step1" class="step">
  <fieldset><legend>1. Shipping</legend>
    <label for="addr">Street address</label>
    <input id="addr" type="text">
    <label for="city">City</label>
    <input id="city" type="text">
    <label for="zip">ZIP</label>
    <input id="zip" type="text">
    <button type="button" id="to2">Next: Payment</button>
  </fieldset>
</div>
<div id="step2" class="step hidden">
  <fieldset><legend>2. Payment</legend>
    <label for="card">Card number</label>
    <input id="card" type="text">
    <label for="method">Shipping method</label>
    <select id="method">
      <option value="standard">Standard (5-7 days)</option>
      <option value="express">Express (2 days)</option>
    </select>
    <button type="button" id="to3">Next: Review</button>
  </fieldset>
</div>
<div id="step3" class="step hidden">
  <fieldset><legend>3. Review &amp; confirm</legend>
    <p id="summary"></p>
    <button type="button" id="confirm">Confirm order</button>
  </fieldset>
</div>
<div id="done" class="hidden">Order confirmed.</div>
"""
    script = """
var state = { step: 1, addr: '', city: '', zip: '', card: '', method: '', confirmed: false };
function show(n) {
  [1,2,3].forEach(function(i) {
    document.getElementById('step' + i).classList.toggle('hidden', i !== n);
  });
  state.step = n;
}
document.getElementById('to2').addEventListener('click', function() {
  state.addr = document.getElementById('addr').value;
  state.city = document.getElementById('city').value;
  state.zip = document.getElementById('zip').value;
  show(2);
});
document.getElementById('to3').addEventListener('click', function() {
  state.card = document.getElementById('card').value;
  state.method = document.getElementById('method').value;
  document.getElementById('summary').textContent =
    state.addr + ', ' + state.city + ' ' + state.zip + ' — ' + state.method;
  show(3);
});
document.getElementById('confirm').addEventListener('click', function() {
  state.confirmed = true;
  document.getElementById('done').classList.remove('hidden');
});
window.__bench_state = function() { return state; };
window.__bench_verify = function() {
  var t = %s;
  return state.addr === t.addr && state.city === t.city && state.zip === t.zip &&
         state.card === t.card && state.method === t.method && state.confirmed === true;
};
""" % json.dumps(target)
    return _page(f"Checkout task {n}", body, script)


# ---------------------------------------------------------------------------
# Task inventory: 10 forms, 10 SPA, 10 wizards. Values are per-task so no two
# tasks are solvable by copy-pasting another task's answer.
# ---------------------------------------------------------------------------

def build() -> list[dict]:
    tasks = []

    form_people = [
        ("Ada Lovelace", "ada@example.com", "5550101", "engineer"),
        ("Grace Hopper", "grace@example.com", "5550102", "engineer"),
        ("Margaret Hamilton", "margaret@example.com", "5550103", "manager"),
        ("Katherine Johnson", "katherine@example.com", "5550104", "engineer"),
        ("Radia Perlman", "radia@example.com", "5550105", "engineer"),
        ("Barbara Liskov", "barbara@example.com", "5550106", "designer"),
        ("Shafi Goldwasser", "shafi@example.com", "5550107", "manager"),
        ("Frances Allen", "frances@example.com", "5550108", "engineer"),
        ("Adele Goldberg", "adele@example.com", "5550109", "designer"),
        ("Jean Bartik", "jean@example.com", "5550110", "other"),
    ]
    for i, (name, email, phone, role) in enumerate(form_people, start=1):
        target = {
            "full_name": name, "email": email, "phone": phone,
            "role": role, "newsletter": True,
        }
        fname = f"form_{i:02d}.html"
        (FIXTURES_DIR / fname).write_text(make_form_task(i, target))
        tasks.append({
            "id": f"form-{i:02d}",
            "category": "form",
            "file": fname,
            "goal": (
                f"Fill in the form: full name '{name}', email '{email}', "
                f"phone '{phone}', role '{role.capitalize()}', and check the "
                "newsletter subscription box. Then click Review & Submit."
            ),
            "verify": "window.__bench_verify()",
            "min_actions": 6,
        })

    import random
    rng = random.Random(20260810)
    for i in range(1, 11):
        items = []
        for j in range(9):
            items.append({
                "id": j + 1,
                "name": f"Item {i}-{j + 1}",
                "category": rng.choice(CATEGORIES_POOL),
                "price": rng.randint(10, 200),
            })
        cat = rng.choice(CATEGORIES_POOL)
        sort = rng.choice(["asc", "desc"])
        matching = [it for it in items if it["category"] == cat]
        if sort == "asc":
            matching.sort(key=lambda it: it["price"])
        else:
            matching.sort(key=lambda it: -it["price"])
        page = 2 if len(matching) > 3 else 1
        start = (page - 1) * 3
        page_items = matching[start:start + 3]
        selected = page_items[0]["id"] if page_items else (matching[0]["id"] if matching else None)
        target = {"filter": cat, "sort": sort, "page": page, "selected": selected}
        fname = f"spa_{i:02d}.html"
        (FIXTURES_DIR / fname).write_text(make_spa_task(i, items, target))
        order = "low to high" if sort == "asc" else "high to low"
        tasks.append({
            "id": f"spa-{i:02d}",
            "category": "spa",
            "file": fname,
            "goal": (
                f"Filter the catalog to category '{cat}', sort by price {order}, "
                f"go to page {page}, then click the first item shown on that page "
                "to select it."
            ),
            "verify": "window.__bench_verify()",
            "min_actions": 4,
        })

    wiz_data = [
        ("100 Main St", "Springfield", "62701", "4111111111111111", "standard"),
        ("22 Baker St", "London", "NW16XE", "4111111111111112", "express"),
        ("5 Rue de Paris", "Paris", "75001", "4111111111111113", "standard"),
        ("9 Elm St", "Boston", "02108", "4111111111111114", "express"),
        ("3 Oak Ave", "Austin", "73301", "4111111111111115", "standard"),
        ("77 King Rd", "Toronto", "M5H2N2", "4111111111111116", "express"),
        ("15 Park Ln", "Seattle", "98101", "4111111111111117", "standard"),
        ("42 Hill St", "Denver", "80201", "4111111111111118", "express"),
        ("8 River Rd", "Miami", "33101", "4111111111111119", "standard"),
        ("61 Lake Ave", "Chicago", "60601", "4111111111111120", "express"),
    ]
    for i, (addr, city, zipc, card, method) in enumerate(wiz_data, start=1):
        target = {"addr": addr, "city": city, "zip": zipc, "card": card, "method": method}
        fname = f"wizard_{i:02d}.html"
        (FIXTURES_DIR / fname).write_text(make_wizard_task(i, target))
        method_label = "Standard (5-7 days)" if method == "standard" else "Express (2 days)"
        tasks.append({
            "id": f"wizard-{i:02d}",
            "category": "wizard",
            "file": fname,
            "goal": (
                f"Complete checkout: shipping address '{addr}', city '{city}', "
                f"ZIP '{zipc}'. On payment, card number '{card}', shipping "
                f"method '{method_label}'. Review and confirm the order."
            ),
            "verify": "window.__bench_verify()",
            "min_actions": 7,
        })

    return tasks


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    tasks = build()
    out = Path(__file__).parent / "tasks.json"
    out.write_text(json.dumps(tasks, indent=2))
    print(f"wrote {len(tasks)} fixture pages to {FIXTURES_DIR}")
    print(f"wrote task inventory to {out}")


if __name__ == "__main__":
    main()
