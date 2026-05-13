"""Static leaderboard renderer.

Writes a self-contained ``index.html`` + ``leaderboard.json`` pair under the
configured output directory. The HTML has no build step or external JS
dependency — it ``fetch()``s the sibling JSON file and renders client-side,
with a sortable table, light/dark theme toggle, filter input, and a 2-model
comparison panel.

Called from :func:`src.benchmark.exporting.export_results`.
"""

import json
from pathlib import Path
from typing import List, Dict


def write_leaderboard_assets(rows: List[Dict], out_dir: str) -> None:
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    # JSON
    (Path(out_dir) / "leaderboard.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    # Static HTML (local) with comparison + responsive layout
    html = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>LLM Leaderboard</title>
  <style>
    :root{
      --bg: #0b1020;
      --panel: rgba(255,255,255,.06);
      --panel2: rgba(255,255,255,.08);
      --text: rgba(255,255,255,.92);
      --muted: rgba(255,255,255,.68);
      --border: rgba(255,255,255,.12);
      --chip: rgba(255,255,255,.08);
      --chip2: rgba(37,99,235,.18);
      --accent: #60a5fa;
      --good: #22c55e;
      --bad: #f87171;
      --warn: #fbbf24;
      --shadow: 0 14px 30px rgba(0,0,0,.28);
      --shadow2: 0 10px 22px rgba(0,0,0,.22);
      --radius: 16px;
    }
    /* Light theme override (default to system; user can toggle) */
    [data-theme="light"]{
      --bg:#f7f8fb;
      --panel:#ffffff;
      --panel2:#ffffff;
      --text:#0f172a;
      --muted:#556070;
      --border: rgba(15,23,42,.12);
      --chip:#f1f5f9;
      --chip2:#eef6ff;
      --accent:#2563eb;
      --good:#16a34a;
      --bad:#dc2626;
      --warn:#b45309;
      --shadow: 0 14px 30px rgba(15,23,42,.10);
      --shadow2: 0 10px 22px rgba(15,23,42,.08);
    }

    body{
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
      margin: 22px;
      background:
        radial-gradient(1200px 600px at 10% -10%, rgba(96,165,250,.28), transparent 60%),
        radial-gradient(900px 600px at 90% 0%, rgba(34,197,94,.18), transparent 55%),
        radial-gradient(900px 600px at 30% 110%, rgba(251,191,36,.14), transparent 55%),
        var(--bg);
      color:var(--text);
    }

    h1{margin: 0 0 8px 0; letter-spacing:-0.03em; font-weight:750;}
    .meta{color:var(--muted); margin-bottom: 14px; line-height:1.4;}

    .top{
      display:flex;
      align-items:flex-start;
      justify-content:space-between;
      gap:14px;
      margin-bottom: 8px;
    }

    .toolbar{
      position: sticky;
      top: 14px;
      z-index: 5;
      display:flex;
      gap:10px;
      flex-wrap:wrap;
      align-items:center;
      margin: 12px 0 14px 0;
      padding: 10px;
      border:1px solid var(--border);
      border-radius: var(--radius);
      background: color-mix(in oklab, var(--panel) 92%, transparent);
      backdrop-filter: blur(10px);
      box-shadow: var(--shadow2);
    }

    .field{
      display:flex;
      align-items:center;
      gap:10px;
      padding:10px 12px;
      border:1px solid var(--border);
      border-radius:14px;
      background: color-mix(in oklab, var(--panel2) 88%, transparent);
      box-shadow: 0 1px 0 rgba(255,255,255,.04) inset;
    }

    .field input{
      border:0;
      outline:0;
      width:min(420px, 56vw);
      font-size:14px;
      background:transparent;
      color:var(--text);
    }
    .field input::placeholder{color: color-mix(in oklab, var(--muted) 80%, transparent);}
    .field small{color:var(--muted);}
    .btn{
      border:1px solid var(--border);
      background: color-mix(in oklab, var(--panel2) 86%, transparent);
      padding:10px 12px;
      border-radius:14px;
      cursor:pointer;
      font-size:14px;
      color: var(--text);
      box-shadow: 0 1px 0 rgba(255,255,255,.04) inset;
      transition: transform .06s ease, border-color .12s ease, background .12s ease;
    }
    .btn:hover{border-color: color-mix(in oklab, var(--border) 70%, var(--accent) 30%);}
    .btn:active{transform: translateY(1px);}
    .btn.primary{
      border-color: color-mix(in oklab, var(--accent) 40%, var(--border) 60%);
      background: color-mix(in oklab, var(--chip2) 78%, transparent);
    }
    .chips{display:flex; gap:8px; flex-wrap:wrap; align-items:center;}
    .chip{display:inline-flex; align-items:center; gap:6px; padding:6px 10px; border-radius:999px; background:var(--chip); font-size:12px; color:#222;}
    .chip b{font-weight:600;}

    .grid{display:grid; grid-template-columns: 1.2fr .8fr; gap:14px; align-items:start;}
    @media (max-width: 980px){ .grid{grid-template-columns: 1fr;} }

    .card{border:1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding:12px; box-shadow: var(--shadow);}
    .card h2{font-size:14px; margin:0 0 10px 0; color:var(--text); letter-spacing:-0.01em;}
    .card .hint{color:var(--muted); font-size:13px; margin: 0 0 10px 0;}

    .compare{display:grid; grid-template-columns: 1fr 1fr; gap:10px;}
    @media (max-width: 640px){ .compare{grid-template-columns: 1fr;} }

    .cmpModel{border:1px solid var(--border); border-radius:14px; padding:10px; background: color-mix(in oklab, var(--panel2) 86%, transparent);}
    .cmpTitle{display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:8px;}
    .cmpTitle .name{font-weight:600; font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
    .cmpTitle .pill{font-size:12px; padding:2px 8px; border-radius:999px; background:var(--chip);}

    .metric{display:flex; align-items:center; justify-content:space-between; gap:10px; margin:6px 0;}
    .metric .k{color:var(--muted); font-size:12px;}
    .metric .v{font-variant-numeric: tabular-nums; font-size:12px;}
    .bar{height:8px; background: color-mix(in oklab, var(--panel2) 70%, transparent); border-radius:999px; overflow:hidden; flex:1; border:1px solid color-mix(in oklab, var(--border) 70%, transparent);}
    .bar > span{display:block; height:100%; background: linear-gradient(90deg, var(--accent), color-mix(in oklab, var(--accent) 40%, #a78bfa 60%)); width:0%;}

    .scoreTag{display:inline-flex; align-items:center; gap:8px; font-variant-numeric: tabular-nums;}
    .dot{width:8px; height:8px; border-radius:999px; background: var(--muted); display:inline-block;}
    .dot.good{background: var(--good);}
    .dot.bad{background: var(--bad);}
    .dot.warn{background: var(--warn);}

    .tableWrap{border:1px solid var(--border); border-radius: var(--radius); overflow:hidden; background: var(--panel); box-shadow: var(--shadow);}
    table{width:100%; border-collapse: collapse;}
    th,td{padding:10px 10px; border-bottom:1px solid var(--border); text-align:left; font-size:13px; vertical-align:middle;}
    th{
      cursor:pointer;
      user-select:none;
      position:sticky;
      top:0;
      background: color-mix(in oklab, var(--panel) 92%, transparent);
      z-index:1;
      white-space:nowrap;
      color: var(--muted);
      font-weight:600;
      letter-spacing:.02em;
      text-transform: uppercase;
      font-size: 11px;
    }
    td.num{text-align:right; font-variant-numeric: tabular-nums;}
    tr:nth-child(even) td{background: color-mix(in oklab, var(--panel2) 20%, transparent);}
    tr:hover td{background: color-mix(in oklab, var(--chip2) 26%, transparent);}
    tr.sel td{background: color-mix(in oklab, var(--chip2) 40%, transparent);}
    .rank{color:var(--muted); width:56px;}
    .model{max-width: 420px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
    .kbd{font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; font-size:12px; color:var(--muted);}

    /* Mobile: allow horizontal scroll for wide tables */
    .scrollX{overflow-x:auto; -webkit-overflow-scrolling: touch;}

    .footer{margin-top: 14px; color: var(--muted); font-size: 12px;}
  </style>
</head>
<body>
  <div class="top">
    <div>
      <h1>Leaderboard</h1>
      <div class=\"meta\">
        Static dashboard (local). Sort by clicking headers. Compare two models by selecting rows.
        <span class=\"kbd\">Tip: click a row to select for compare</span>
      </div>
    </div>
    <button class="btn" id="themeToggle" title="Toggle theme">Theme</button>
  </div>

  <div class=\"toolbar\">
    <div class=\"field\" title=\"Filter by model name\">
      <small>Filter</small>
      <input id=\"filter\" placeholder=\"type to filter models...\" />
    </div>
    <button class=\"btn primary\" id=\"clearCompare\">Clear compare</button>
    <button class=\"btn\" id=\"toggleOnlyCompared\">Show compared only</button>
    <div class=\"chips\" id=\"chips\"></div>
  </div>

  <div class=\"grid\">
    <div class=\"tableWrap\">
      <div class=\"scrollX\">
        <table id=\"tbl\"></table>
      </div>
    </div>
    <div class=\"card\">
      <h2>Comparison</h2>
      <div class=\"hint\">Select up to 2 models in the table to compare side-by-side.</div>
      <div class=\"compare\" id=\"compare\"></div>
    </div>
  </div>
  <div class="footer">Generated locally from <span class="kbd">leaderboard.json</span>. No network calls beyond loading the JSON file.</div>

<script>
async function load(){
  const res = await fetch('leaderboard.json');
  const data = await res.json();
  const columns = [
    { key: 'rank', label: '#' },
    { key: 'model_id', label: 'model' },
    { key: 'total', label: 'total' },
    { key: 'chemistry', label: 'chem' },
    { key: 'emotions', label: 'emo' },
    { key: 'math', label: 'math' },
    { key: 'reasoning3d', label: '3d' },
    { key: 'no_knowledge', label: 'noK' },
    { key: 'contradiction', label: 'contr' },
    { key: 'correct', label: 'correct' },
    { key: 'wrong', label: 'wrong' },
    { key: 'blank', label: 'blank' },
    { key: 'format_violations', label: 'format' },
  ];

  let sortKey = 'total';
  let sortDir = -1;
  let onlyCompared = false;
  const compared = []; // model_id list (max 2)

  const scoreKeys = ['total','chemistry','emotions','math','reasoning3d','no_knowledge','contradiction'];

  function clamp(n, a, b){ return Math.max(a, Math.min(b, n)); }

  function scoreDot(total){
    if (typeof total !== 'number') return 'dot warn';
    if (total >= 0) return 'dot good';
    if (total <= -50) return 'dot bad';
    return 'dot warn';
  }

  function renderChips(){
    const el = document.getElementById('chips');
    if (compared.length === 0){
      el.innerHTML = `<span class="chip"><b>Compare</b> none</span>`;
      return;
    }
    el.innerHTML = compared.map(m => `<span class="chip"><b>Compare</b> ${escapeHtml(m)}</span>`).join('');
  }

  function escapeHtml(s){
    return String(s ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'","&#39;");
  }

  function computeRanges(rows){
    const ranges = {};
    for (const k of scoreKeys){
      let min = Infinity, max = -Infinity;
      for (const r of rows){
        const v = r[k];
        if (typeof v === 'number'){
          min = Math.min(min, v);
          max = Math.max(max, v);
        }
      }
      if (!Number.isFinite(min)) { min = 0; max = 1; }
      if (min === max) { max = min + 1; }
      ranges[k] = { min, max };
    }
    return ranges;
  }

  const rangesAll = computeRanges(data);

  function renderCompare(rows){
    const el = document.getElementById('compare');
    const picks = compared.map(id => rows.find(r => r.model_id === id)).filter(Boolean);

    if (picks.length === 0){
      el.innerHTML = `<div class="cmpModel"><div class="cmpTitle"><span class="name">No models selected</span><span class="pill">pick 2</span></div><div class="hint">Click table rows to compare.</div></div>`;
      return;
    }

    const cards = picks.map(r => {
      const total = r.total;
      const dot = scoreDot(total);
      const metrics = [
        ['Total', 'total'],
        ['Chemistry', 'chemistry'],
        ['Emotions', 'emotions'],
        ['Math', 'math'],
        ['Reasoning3D', 'reasoning3d'],
        ['No knowledge', 'no_knowledge'],
        ['Contradiction', 'contradiction'],
        ['Correct', 'correct'],
        ['Wrong', 'wrong'],
        ['Blank', 'blank'],
        ['Format violations', 'format_violations'],
      ];

      const metricHtml = metrics.map(([label, key])=>{
        const v = r[key];
        const isScore = scoreKeys.includes(key);
        const range = rangesAll[key] || { min: 0, max: 1 };
        const pct = isScore && typeof v === 'number'
          ? (100 * (v - range.min) / (range.max - range.min))
          : null;
        const bar = isScore ? `<div class="bar"><span style="width:${clamp(pct ?? 0, 0, 100)}%"></span></div>` : '';
        return `<div class="metric"><span class="k">${escapeHtml(label)}</span>${bar}<span class="v">${escapeHtml(v ?? '')}</span></div>`;
      }).join('');

      return `
        <div class="cmpModel">
          <div class="cmpTitle">
            <span class="name">${escapeHtml(r.model_id)}</span>
            <span class="pill"><span class="${dot}"></span> ${escapeHtml(total ?? '')}</span>
          </div>
          ${metricHtml}
        </div>
      `;
    }).join('');

    // If only 1 selected, show a placeholder second slot
    if (picks.length === 1){
      el.innerHTML = cards + `<div class="cmpModel"><div class="cmpTitle"><span class="name">Select another model</span><span class="pill">pick 2</span></div><div class="hint">Click a second row in the table.</div></div>`;
    } else {
      el.innerHTML = cards;
    }
  }

  function render(rows){
    const f = document.getElementById('filter').value.toLowerCase();
    const filteredBase = rows.filter(r => (r.model_id||'').toLowerCase().includes(f));
    const filtered = onlyCompared ? filteredBase.filter(r => compared.includes(r.model_id)) : filteredBase;

    filtered.sort((a,b)=>{
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === 'number' && typeof bv === 'number') return sortDir*(av-bv);
      return sortDir*String(av).localeCompare(String(bv));
    });

    const thead = `<tr>${columns.map(c=>`<th data-k="${c.key}">${c.label}${sortKey===c.key ? (sortDir<0 ? ' ↓' : ' ↑') : ''}</th>`).join('')}</tr>`;
    const tbody = filtered.map((r, idx)=>{
      const isSel = compared.includes(r.model_id);
      const rank = idx + 1;
      const total = r.total;
      const dot = scoreDot(total);
      return `<tr data-mid="${escapeHtml(r.model_id)}" class="${isSel ? 'sel' : ''}">
        <td class="rank num">${rank}</td>
        <td class="model" title="${escapeHtml(r.model_id)}">${escapeHtml(r.model_id)}</td>
        <td class="num"><span class="scoreTag"><span class="${dot}"></span>${escapeHtml(total ?? '')}</span></td>
        <td class="num">${escapeHtml(r.chemistry ?? '')}</td>
        <td class="num">${escapeHtml(r.emotions ?? '')}</td>
        <td class="num">${escapeHtml(r.math ?? '')}</td>
        <td class="num">${escapeHtml(r.reasoning3d ?? '')}</td>
        <td class="num">${escapeHtml(r.no_knowledge ?? '')}</td>
        <td class="num">${escapeHtml(r.contradiction ?? '')}</td>
        <td class="num">${escapeHtml(r.correct ?? '')}</td>
        <td class="num">${escapeHtml(r.wrong ?? '')}</td>
        <td class="num">${escapeHtml(r.blank ?? '')}</td>
        <td class="num">${escapeHtml(r.format_violations ?? '')}</td>
      </tr>`;
    }).join('');
    document.getElementById('tbl').innerHTML = thead + tbody;

    document.querySelectorAll('th').forEach(th=>{
      th.onclick = ()=>{
        const k = th.getAttribute('data-k');
        if (sortKey === k) sortDir *= -1; else { sortKey = k; sortDir = -1; }
        render(rows);
      };
    });

    document.querySelectorAll('tr[data-mid]').forEach(tr=>{
      tr.onclick = ()=>{
        const mid = tr.getAttribute('data-mid');
        const idx = compared.indexOf(mid);
        if (idx >= 0){
          compared.splice(idx, 1);
        } else {
          if (compared.length >= 2) compared.shift();
          compared.push(mid);
        }
        renderChips();
        render(rows);
        renderCompare(rows);
      };
    });

    renderCompare(rows);
  }

  document.getElementById('filter').addEventListener('input', ()=>render(data));
  document.getElementById('clearCompare').onclick = ()=>{
    compared.splice(0, compared.length);
    renderChips();
    render(data);
    renderCompare(data);
  };
  document.getElementById('toggleOnlyCompared').onclick = ()=>{
    onlyCompared = !onlyCompared;
    document.getElementById('toggleOnlyCompared').textContent = onlyCompared ? 'Show all' : 'Show compared only';
    render(data);
  };

  renderChips();
  render(data);
}

// Theme: default to system; persist toggle in localStorage.
(function initTheme(){
  const key = 'lb_theme';
  const saved = localStorage.getItem(key);
  const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const initial = saved || (prefersDark ? 'dark' : 'light');
  document.documentElement.setAttribute('data-theme', initial);
  const btn = document.getElementById('themeToggle');
  const setLabel = ()=>{
    const t = document.documentElement.getAttribute('data-theme') || 'light';
    btn.textContent = (t === 'dark') ? 'Dark' : 'Light';
  };
  setLabel();
  btn.onclick = ()=>{
    const cur = document.documentElement.getAttribute('data-theme') || 'light';
    const next = (cur === 'dark') ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem(key, next);
    setLabel();
  };
})();

load();
</script>
</body>
</html>"""

    (Path(out_dir) / "index.html").write_text(html, encoding="utf-8")
