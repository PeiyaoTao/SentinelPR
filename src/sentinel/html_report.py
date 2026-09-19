"""Self-contained, offline report viewer. Repository/model text is never HTML."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
from sentinel.state import ConsolidatedReport

STYLE = """
:root{font:15px/1.55 system-ui,sans-serif;color:#192e3b;background:#f3f5f6}*{box-sizing:border-box}body{margin:0}header{background:#152d3b;color:white;padding:30px max(24px,calc((100vw - 1180px)/2))}h1{margin:4px 0;font-size:30px;letter-spacing:-1px}header p{margin:8px 0;color:#c6d6df}.eyebrow{text-transform:uppercase;letter-spacing:2px;font-size:12px;color:#8edace}main{max-width:1180px;margin:auto;padding:24px}.overview{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:22px}.stat{padding:18px;background:white;border:1px solid #dbe2e6;border-radius:10px}.stat strong{display:block;font-size:24px;color:#193f54}.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}input,select,button{font:inherit;padding:9px 12px;border:1px solid #becdd4;border-radius:6px;background:white;color:#19394b}input{flex:1;min-width:190px}button{cursor:pointer}button:hover{background:#eaf2f5}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #16827c;outline-offset:2px}.card{background:white;border:1px solid #dbe2e6;border-left:4px solid #31847e;border-radius:8px;padding:20px;margin:14px 0}.card h2{font-size:18px;margin:8px 0}.meta{font:12px/1.7 ui-monospace,monospace;color:#486474;overflow-wrap:anywhere}.detail{white-space:pre-wrap;overflow-wrap:anywhere;margin:10px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf2f4;padding:16px;border-radius:6px;max-height:520px;overflow:auto;font-size:12px}.note{color:#526b79;font-size:13px}.card select{float:right;font-size:12px}.hidden{display:none!important}details{margin-top:20px}summary{cursor:pointer;font-weight:600}.empty{padding:50px;text-align:center;border:1px dashed #bccdd4;border-radius:10px;color:#526b79}#storage{color:#89561a}footer{padding:25px 0;font-size:12px;color:#526b79}@media(max-width:650px){.overview{grid-template-columns:1fr}h1{font-size:25px}main{padding:16px}.toolbar>*{width:100%}.card select{float:none}}
"""
SCRIPT = r"""
'use strict';
const report = JSON.parse(document.getElementById('report-data').textContent);
const reportId = document.documentElement.dataset.reportId;
const items = [];
const add = (kind,title,body,meta='') => items.push({id:String(items.length),kind,title,body,meta});
for(const a of report.critic_audit || []) {
  const body = a.claim + '\n\nDecision: ' + a.reason;
  add('audit',a.title,body,`${a.decision} · ${a.file_path}:${a.line} · ${a.proof_status}`);
  if(['ACCEPT','DOWNGRADE'].includes(a.decision)) add('findings',a.title,body,`${a.final_severity} · ${a.file_path}:${a.line} · ${a.proof_status}`);
}
const quality = report.quality_review;
if(quality){
  for(const a of quality.contextual_advice || []) {
    if(a.decision && a.decision.disposition === 'recommend') add('advice',a.subject,a.decision.recommendation+'\n\n'+a.decision.rationale,`Model opinion · ${a.decision.impact} impact · ${a.decision.confidence} confidence`);
  }
  for(const f of quality.findings || []) add('metrics',f.title,f.explanation+'\n\nRule prompt: '+f.recommendation,`${f.subject} · ${f.verification_status} · ${f.rule_id}`);
  add('coverage','Specialist coverage',(quality.limitations||[]).join('\n'),`Static scope complete: ${quality.complete} · Unresolved calls: ${quality.unresolved_calls}`);
}
if(report.project_assessment){
  for(const a of report.project_assessment.advice) add('advice',a.title,a.rationale+'\n\n'+a.recommendation,`${a.source} · ${a.priority}`);
  add('coverage','Project context limits',report.project_assessment.limitations.join('\n'));
}
if(report.delegated_review){
  const d=report.delegated_review;
  for(const f of d.findings) {
    const evidence=f.evidence.map(c=>{const e=report.delegation_excerpts.find(e=>e.id===c.excerpt_id);return e?`${e.file_path}:${c.line}`:c.excerpt_id;}).join(', ');
    add('advice',f.title,f.claim+'\n\n'+f.recommendation,`UNVERIFIED EXTERNAL OPINION · ${f.priority} · ${evidence}`);
  }
  add('coverage','Delegated review coverage',d.limitations.join('\n'),`${d.reviewed_excerpts.length}/${report.delegation_excerpts.length} supplied excerpts declared reviewed · ${d.reviewer}`);
}
if(report.validation){for(const c of report.validation.results) add('validation',c.name,c.summary+'\n\n'+JSON.stringify(c.issues,null,2),c.status);}
else add('validation','Project validation','Tests, builds and other executable checks were not run for this report.','NOT RUN');
add('coverage','Uninspected files',(report.uninspected_files||[]).join('\n')||'None recorded within supported collection scope.');
add('coverage','Critic limitations',(report.critic_limitations||[]).join('\n')||'See the candidate audit for individual decisions.');
if(report.llm_usage.length) add('coverage','Model execution',JSON.stringify(report.llm_usage,null,2),'Recorded timing and provider-reported usage; missing usage is unavailable.');
const byId=id=>document.getElementById(id);
byId('outcome').textContent=report.review_outcome;
byId('findings-count').textContent=report.accepted_findings_count;
byId('advice-count').textContent=items.filter(i=>i.kind==='advice').length;
byId('audit-count').textContent=report.critic_audit.length;
byId('raw').textContent=report.summary_markdown;
const key='sentinel-triage-'+reportId;
let triage=Object.create(null);
try {const saved=JSON.parse(localStorage.getItem(key)||'{}');for(const i of items) if(['reviewed','ignored'].includes(saved[i.id])) triage[i.id]=saved[i.id];}
catch(error){byId('storage').textContent='Browser storage is unavailable. Triage works for this page session; use Export triage to save it.';}
function save(){try{localStorage.setItem(key,JSON.stringify(triage));}catch(error){byId('storage').textContent='Could not save triage in this browser. Use Export triage.';}}
function render(){
  const query=byId('search').value.toLowerCase(), kind=byId('kind').value, status=byId('status').value;
  const visible=items.filter(i=>(kind==='all'||(kind==='actionable'?['findings','advice'].includes(i.kind):i.kind===kind))&&
    (status==='all'||(triage[i.id]||'open')===status)&&`${i.title} ${i.body} ${i.meta}`.toLowerCase().includes(query));
  byId('results').replaceChildren();
  byId('count').textContent=`${visible.length} item(s) shown`;
  for(const item of visible){
    const card=document.createElement('article');card.className='card';
    const state=document.createElement('select');state.setAttribute('aria-label','Triage '+item.title);
    for(const value of ['open','reviewed','ignored']){const option=document.createElement('option');option.value=value;option.textContent=value;state.append(option);}
    state.value=triage[item.id]||'open';state.addEventListener('change',()=>{triage[item.id]=state.value;save();render();});
    const meta=document.createElement('div');meta.className='meta';meta.textContent=item.kind.toUpperCase()+' · '+item.meta;
    const title=document.createElement('h2');title.textContent=item.title;
    const body=document.createElement('div');body.className='detail';body.textContent=item.body;
    card.append(state,meta,title,body);byId('results').append(card);
  }
  byId('empty').classList.toggle('hidden',visible.length!==0);
}
function download(value,name){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
for(const id of ['search','kind','status'])byId(id).addEventListener('input',render);
byId('export-report').addEventListener('click',()=>download(report,'sentinel-review.json'));
byId('export-triage').addEventListener('click',()=>download({report_id:reportId,dispositions:triage,meaning:'Local triage only; does not change evidence or the gate outcome.'},'sentinel-triage.json'));
render();
"""


def render_html(report: ConsolidatedReport) -> str:
    data = report.model_dump_json().replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    identity = hashlib.sha256(data.encode()).hexdigest()
    script_hash = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    style_hash = base64.b64encode(hashlib.sha256(STYLE.encode()).digest()).decode()
    csp = f"default-src 'none'; script-src 'sha256-{script_hash}'; style-src 'sha256-{style_hash}'; base-uri 'none'; form-action 'none'; connect-src 'none'"
    return f"""<!doctype html>
<html lang="en" data-report-id="{identity}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{csp}"><title>SentinelPR review</title><style>{STYLE}</style></head>
<body><header><div class="eyebrow">SentinelPR · Local report</div><h1>Code review, with the evidence.</h1>
<p>Outcome: <strong id="outcome"></strong> · A review of supported checks, not merge approval.</p></header>
<main><section class="overview" aria-label="Report overview"><div class="stat"><strong id="findings-count"></strong>Retained findings</div><div class="stat"><strong id="advice-count"></strong>Suggested improvements</div><div class="stat"><strong id="audit-count"></strong>Audited candidates</div></section>
<p class="note">External and model advice is unverified opinion. Local triage marks help organize work; they never change the report's evidence or gate outcome.</p>
<div class="toolbar"><input id="search" type="search" aria-label="Search report" placeholder="Search findings, paths, rules…">
<select id="kind" aria-label="Section"><option value="actionable">Findings & advice</option><option value="findings">Code findings</option><option value="advice">Advice</option><option value="audit">Critic audit</option><option value="metrics">Static metrics</option><option value="validation">Validation</option><option value="coverage">Coverage & usage</option><option value="all">All sections</option></select>
<select id="status" aria-label="Triage status"><option value="all">All triage states</option><option value="open">Open</option><option value="reviewed">Reviewed</option><option value="ignored">Ignored</option></select></div>
<p id="count" class="note" aria-live="polite"></p><p id="storage" role="status"></p><section id="results" aria-label="Review items"></section><div id="empty" class="empty hidden">No items match this view. Check Coverage and Validation before drawing conclusions.</div>
<div class="toolbar"><button id="export-report">Download report JSON</button><button id="export-triage">Export triage</button></div>
<details><summary>Complete Markdown report (plain text)</summary><pre id="raw"></pre></details>
<noscript>Enable JavaScript to use the viewer, or open the accompanying Markdown/JSON report.</noscript>
<footer>Standalone report · No external scripts, fonts, services or network requests.</footer></main>
<script id="report-data" type="application/json">{data}</script><script>{SCRIPT}</script></body></html>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = ConsolidatedReport.model_validate_json(args.report.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_html(report), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
