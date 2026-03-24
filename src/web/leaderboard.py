import json
from pathlib import Path
from typing import List, Dict


def write_leaderboard_assets(rows: List[Dict], out_dir: str) -> None:
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    # JSON
    (Path(out_dir) / "leaderboard.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    # Simple HTML
    html = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>LLM Leaderboard</title>
  <style>
    body{font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; margin: 24px;}
    h1{margin: 0 0 12px 0;}
    .meta{color:#555; margin-bottom: 16px;}
    input{padding:10px 12px; width: min(520px, 100%); border:1px solid #ccc; border-radius:10px;}
    table{width:100%; border-collapse: collapse; margin-top: 12px;}
    th,td{padding:10px 8px; border-bottom:1px solid #eee; text-align:left;}
    th{cursor:pointer; user-select:none; position:sticky; top:0; background:#fff;}
    .tag{display:inline-block; padding:2px 8px; border-radius:999px; background:#f2f2f2; font-size:12px;}
  </style>
</head>
<body>
  <h1>Leaderboard</h1>
  <div class=\"meta\">Static dashboard (local). Sort columns by clicking headers. Filter by typing.</div>
  <input id=\"filter\" placeholder=\"Filter models...\" />
  <table id=\"tbl\"></table>

<script>
async function load(){
  const res = await fetch('leaderboard.json');
  const data = await res.json();
  const columns = ['model_id','total','chemistry','emotions','math','reasoning3d','no_knowledge','contradiction','correct','wrong','blank','format_violations'];

  let sortKey = 'total';
  let sortDir = -1;

  function render(rows){
    const f = document.getElementById('filter').value.toLowerCase();
    const filtered = rows.filter(r => (r.model_id||'').toLowerCase().includes(f));

    filtered.sort((a,b)=>{
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === 'number' && typeof bv === 'number') return sortDir*(av-bv);
      return sortDir*String(av).localeCompare(String(bv));
    });

    const thead = `<tr>${columns.map(c=>`<th data-k="${c}">${c}</th>`).join('')}</tr>`;
    const tbody = filtered.map(r=>`<tr>${columns.map(c=>`<td>${r[c] ?? ''}</td>`).join('')}</tr>`).join('');
    document.getElementById('tbl').innerHTML = thead + tbody;

    document.querySelectorAll('th').forEach(th=>{
      th.onclick = ()=>{
        const k = th.getAttribute('data-k');
        if (sortKey === k) sortDir *= -1; else { sortKey = k; sortDir = -1; }
        render(rows);
      };
    });
  }

  document.getElementById('filter').addEventListener('input', ()=>render(data));
  render(data);
}
load();
</script>
</body>
</html>"""

    (Path(out_dir) / "index.html").write_text(html, encoding="utf-8")
