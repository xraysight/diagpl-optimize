#!/usr/bin/env python3
"""Lokalny interfejs WWW DIAG.pl Optimize bez dodatkowych zależności."""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from diagpl_optimize_core import (
    DEFAULT_DB,
    PolishArgumentParser,
    database_status,
    get_institution,
    initialize_database_if_needed,
    optimize_products,
    refresh_database,
    search_institutions,
    search_products,
)

HTML = r"""<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DIAG.pl Optimize</title>
<style>
:root {
  color-scheme:light; font:15px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  --ink:#10243e; --muted:#56687e; --line:#dce5ef; --blue:#0878d1; --blue-dark:#075b9d;
  --sky:#eaf6ff; --surface:#fff; --warm:#f7f8f5; --green:#087f5b;
  background:var(--warm); color:var(--ink)
}
* { box-sizing:border-box }
body { margin:0; min-height:100vh; background:
  radial-gradient(circle at 8% 10%,#dff2ff 0,transparent 28%),
  radial-gradient(circle at 92% 18%,#e5f8ef 0,transparent 24%),var(--warm) }
button,input { font:inherit }
button { cursor:pointer }
.topbar { height:6px; background:linear-gradient(90deg,#075b9d,#09a9d5 55%,#0fb57a) }
main { max-width:1120px; margin:auto; padding:28px 24px 64px }
header { display:flex; align-items:center; justify-content:space-between; gap:24px; margin-bottom:28px }
.brand { display:flex; align-items:flex-start; gap:14px }
.logo { display:grid; flex:0 0 48px; place-items:center; width:48px; height:48px; border-radius:14px; color:white; background:linear-gradient(145deg,var(--blue),#08a8ce); box-shadow:0 10px 24px #0878d135; font-size:25px; font-weight:800 }
h1,h2,p { margin:0 }
h1 { font-size:25px; line-height:1.05; letter-spacing:-.7px }
.brand p { color:var(--muted); margin-top:5px }
.status-line { display:flex; align-items:center; gap:7px; color:var(--muted); font-size:13px; margin-top:7px }
.status-dot { width:7px; height:7px; border-radius:50%; background:#11a66a; box-shadow:0 0 0 4px #11a66a18 }
button { border:1px solid var(--line); border-radius:10px; padding:10px 14px; color:var(--ink); background:#fff; font-weight:650; transition:transform .15s,box-shadow .15s,border-color .15s,background .15s }
button:hover { transform:translateY(-1px); border-color:#9ac5e4; box-shadow:0 6px 16px #16334d12 }
button:active { transform:translateY(0) }
button:disabled { cursor:not-allowed; opacity:.45; transform:none; box-shadow:none }
button.primary { padding:12px 18px; color:white; border-color:transparent; background:linear-gradient(135deg,var(--blue),var(--blue-dark)); box-shadow:0 9px 20px #0878d12d }
button.primary:hover { box-shadow:0 12px 25px #0878d142 }
button.danger { border:0; color:#9d3340; background:#fff1f2; padding:6px 9px; font-size:12px; box-shadow:none }
.workspace { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; align-items:start; transition:opacity .2s }
.workspace.locked { opacity:.68 }
.workspace.busy { opacity:.68; pointer-events:none }
.card { position:relative; background:#ffffffd9; border:1px solid #fff; border-radius:18px; padding:22px; box-shadow:0 12px 35px #1734500c,0 2px 8px #17345008; backdrop-filter:blur(10px) }
.search-card { z-index:20 }
.institution-card { z-index:30; margin-bottom:18px }
.card + .card { margin-top:18px }
.step { display:inline-flex; align-items:center; gap:8px; margin-bottom:13px; color:var(--blue-dark); font-size:12px; font-weight:750; letter-spacing:.08em; text-transform:uppercase }
.step b { display:grid; place-items:center; width:22px; height:22px; border-radius:7px; color:white; background:var(--blue) }
h2 { font-size:20px; letter-spacing:-.35px; margin-bottom:5px }
.lead { color:var(--muted); margin-bottom:18px }
.search-wrap { position:relative }
.search-icon { position:absolute; left:14px; top:50%; transform:translateY(-50%); color:#8294a9; pointer-events:none }
input { width:100%; border:1px solid #cdd9e6; border-radius:12px; padding:13px 14px 13px 42px; color:var(--ink); background:#fff; outline:none; box-shadow:0 2px 7px #17345008; transition:border .15s,box-shadow .15s }
input:focus { border-color:#52a7df; box-shadow:0 0 0 4px #0878d116 }
.matches { position:absolute; z-index:10; left:0; right:0; margin-top:7px; border:1px solid var(--line); border-radius:13px; max-height:320px; overflow:auto; background:#fff; box-shadow:0 18px 45px #17345022 }
.match,.selected,.choice { display:flex; justify-content:space-between; gap:14px; align-items:center; width:100%; padding:12px 13px; border:0; border-bottom:1px solid #edf1f5; border-radius:0; text-align:left; box-shadow:none; font-weight:500 }
.match:last-child,.selected:last-child,.choice:last-child { border-bottom:0 }
.match:hover { transform:none; background:var(--sky); box-shadow:none }
.match.active { background:#e5f3fd; box-shadow:inset 3px 0 0 var(--blue) }
.match small { display:block; margin-top:2px }
.match-main { min-width:0 }
.institution-selected { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:14px; padding:13px 15px; border:1px solid #b9dfd0; border-radius:12px; background:#effbf6 }
.institution-selected strong,.institution-selected small { display:block }
.institution-selected strong { color:var(--green) }
.loading { margin-top:12px; color:var(--blue-dark); font-weight:650 }
.price { white-space:nowrap; font-weight:750; color:#183d5d }
.muted,small { color:var(--muted) }
.hidden { display:none!important }
#selected { counter-reset:item; min-height:68px }
.selected { counter-increment:item; background:#fbfcfd; border:1px solid #edf1f5; border-radius:11px; margin-bottom:8px }
.selected::before { content:counter(item); display:grid; place-items:center; flex:0 0 27px; height:27px; border-radius:8px; color:var(--blue-dark); background:var(--sky); font-size:12px; font-weight:800 }
.selected > a { flex:1; color:var(--ink); font-weight:600; text-decoration:none }
.selected > a:hover { color:var(--blue-dark); text-decoration:underline; text-underline-offset:3px }
.selected-summary { display:flex; justify-content:space-between; align-items:center; margin-top:12px; padding:12px 13px; border-radius:11px; color:var(--muted); background:var(--sky) }
.selected-summary strong { color:var(--blue-dark); font-size:17px }
.list-title { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:5px }
.list-title h2 { margin-bottom:0 }
.empty { display:grid; place-items:center; min-height:105px; border:1px dashed #cfdbe7; border-radius:12px; color:var(--muted); text-align:center; background:#fafcfe }
.actions { display:flex; justify-content:flex-end; margin-top:15px }
#result { margin-top:18px; overflow:hidden; background:linear-gradient(145deg,#fff,#f5fbff) }
#result::before { content:""; position:absolute; width:180px; height:180px; right:-75px; top:-90px; border-radius:50%; background:#21bf8214 }
.metrics { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin:18px 0 15px }
.metric { border:1px solid #e2e9f0; border-radius:13px; padding:13px; color:var(--muted); background:#fff }
.metric strong { display:block; color:var(--ink); font-size:20px; letter-spacing:-.35px; margin-top:5px }
.metric.saving { border-color:#bce8d5; background:#effbf6 }
.saving strong { color:var(--green) }
.choice { margin-top:9px; border:1px solid #e2e9f0!important; border-radius:12px; background:#fff }
.choice > span:first-child { flex:1; font-weight:650 }
.choice a { color:var(--ink); text-decoration:none }
.choice a:hover { color:var(--blue-dark); text-decoration:underline; text-underline-offset:3px }
.choice small { display:block; margin-top:3px; font-weight:400 }
.error { color:#9d2938; background:#fff1f2; border:1px solid #ffd5da; padding:12px; border-radius:11px }
.warning { margin-top:9px; padding:12px; border:1px solid #f2d18e; border-radius:11px; background:#fffbeb; color:#713f12; white-space:pre-line; overflow-wrap:anywhere }
@media(max-width:780px){.workspace{grid-template-columns:1fr}header{align-items:flex-start}.brand p{display:none}}
@media(max-width:560px){main{padding:20px 12px 42px}header{flex-direction:column}.card{padding:17px}.metrics{grid-template-columns:1fr}.choice{align-items:flex-start;flex-direction:column}.price{align-self:flex-end}}
</style>
</head>
<body><div class="topbar"></div><main>
<header>
  <div class="brand"><div class="logo">+</div><div><h1>DIAG.pl Optimize</h1><p>Znajdź najkorzystniejszy zestaw badań</p><div class="status-line"><span class="status-dot"></span><span id="status">Wczytywanie informacji o bazie…</span></div></div></div>
  <button id="refresh" disabled>↻&nbsp; Odśwież dane</button>
</header>
<section class="card institution-card">
  <div class="step"><b>1</b> Punkt pobrań</div>
  <h2>Wybierz punkt pobrań</h2>
  <p class="lead">Ceny badań zależą od lokalizacji. Wyszukaj punkt po nazwie, mieście lub adresie.</p>
  <div id="institution-selected" class="institution-selected hidden"><div><strong id="institution-name"></strong><small id="institution-address"></small></div><button id="change-institution">Zmień punkt</button></div>
  <div id="institution-picker" class="search-wrap"><span class="search-icon">⌕</span><input id="institution-search" autocomplete="off" placeholder="Np. Gdańsk, Zwycięstwa…" aria-autocomplete="list" aria-controls="institution-matches"><div id="institution-matches" class="matches hidden" role="listbox"></div></div>
  <div id="institution-loading" class="loading hidden">Pobieram produkty i aktualne ceny dla wybranego punktu…</div>
  <div id="institution-error" class="error hidden"></div>
</section>
<div id="workspace" class="workspace locked">
  <div>
    <section class="card search-card">
      <div class="step"><b>2</b> Wyszukiwanie</div>
      <h2>Jakich badań potrzebujesz?</h2>
      <p class="lead">Wpisz co najmniej dwa znaki i dodaj badania do swojej listy.</p>
      <div class="search-wrap"><span class="search-icon">⌕</span><input id="search" disabled autocomplete="off" placeholder="Najpierw wybierz punkt pobrań" aria-autocomplete="list" aria-controls="matches"><div id="matches" class="matches hidden" role="listbox"></div></div>
    </section>
    <section id="result" class="card hidden"><div class="step"><b>4</b> Wynik</div><h2>Proponowany zestaw</h2><div id="result-body"></div></section>
  </div>
  <section class="card">
    <div class="step"><b>3</b> Twoja lista</div>
    <div class="list-title"><h2>Wybrane badania</h2><button id="clear-selected" class="danger" disabled>Wyczyść</button></div>
    <p class="lead">Dodaj wszystkie pozycje, które chcesz wykonać.</p>
    <div id="selected"><span class="empty">Lista jest jeszcze pusta.<br>Wyszukaj i dodaj pierwsze badanie.</span></div>
    <div class="selected-summary"><span>Suma wybranych badań</span><strong id="selected-total">0,00 PLN</strong></div>
    <div class="actions"><button id="optimize" class="primary" disabled>Oblicz najlepszy zestaw&nbsp; →</button></div>
  </section>
</div>
</main>
<script>
const $ = id => document.getElementById(id), selected = [];
const money = (value, currency='PLN') => Number(value).toLocaleString('pl-PL',{minimumFractionDigits:2,maximumFractionDigits:2})+' '+(currency||'PLN');
const SELECTED_PRODUCTS_STORAGE_KEY='diagpl-optimize:selected-products';
let selectedInstitution=null, productAreaBusy=false, productTimer, institutionTimer, activeMatch=-1, activeInstitutionMatch=-1;
async function api(path, options) { const r=await fetch(path,options); const data=await r.json(); if(!r.ok) throw Error(data.error||'Błąd serwera'); return data }
function node(tag, text, cls) { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n }
function updateStatus(s){ if(s.fetched_at){const date=new Date(s.fetched_at).toLocaleString('pl-PL',{dateStyle:'medium',timeStyle:'short',timeZone:'Europe/Warsaw'});$('status').textContent=`Zaktualizowano ${date} · ${s.total_items} produktów · ${s.institutions} punktów pobrań`}else{$('status').textContent=`Baza zainicjalizowana · ${s.institutions} punktów pobrań · wybierz punkt`} }
function applyInstitution(institution){ selectedInstitution=institution; const ready=Boolean(institution); $('workspace').classList.toggle('locked',!ready); $('search').disabled=productAreaBusy||!ready; $('search').placeholder=ready?'Np. morfologia, CRP, witamina D…':'Najpierw wybierz punkt pobrań'; $('refresh').disabled=productAreaBusy||!ready; $('institution-selected').classList.toggle('hidden',!ready); $('institution-picker').classList.toggle('hidden',ready); if(ready){$('institution-name').textContent=institution.name;$('institution-address').textContent=institution.full_address||'Brak adresu'} renderSelected() }
function setProductAreaBusy(busy){ productAreaBusy=busy; const workspace=$('workspace'); workspace.classList.toggle('busy',busy); workspace.inert=busy; workspace.setAttribute('aria-busy',String(busy)); $('search').disabled=busy||!selectedInstitution; $('refresh').disabled=busy||!selectedInstitution; $('change-institution').disabled=busy; $('clear-selected').disabled=busy||!selected.length; $('optimize').disabled=busy||!selectedInstitution||!selected.length }
function saveProductSelection(){ try { if(!selectedInstitution||!selected.length){localStorage.removeItem(SELECTED_PRODUCTS_STORAGE_KEY);return} localStorage.setItem(SELECTED_PRODUCTS_STORAGE_KEY,JSON.stringify({institutionId:selectedInstitution.id,products:selected})) } catch(_){} }
function restoreProductSelection(){ selected.splice(0); try { const stored=JSON.parse(localStorage.getItem(SELECTED_PRODUCTS_STORAGE_KEY)||'null'); if(stored?.institutionId===selectedInstitution?.id&&Array.isArray(stored.products)){stored.products.slice(0,100).forEach(p=>{const price=Number(p?.price);if(typeof p?.name==='string'&&typeof p?.slug==='string'&&Number.isFinite(price)){selected.push({name:p.name,slug:p.slug,price,currency:typeof p.currency==='string'?p.currency:'PLN'})}})}else if(stored){localStorage.removeItem(SELECTED_PRODUCTS_STORAGE_KEY)} } catch(_){localStorage.removeItem(SELECTED_PRODUCTS_STORAGE_KEY)} renderSelected() }
async function loadStatus(){ try { const s=await api('/api/status'); updateStatus(s); applyInstitution(s.selected_institution); restoreProductSelection(); return s } catch(e){ $('status').textContent=e.message; throw e } }
function clearProductSelection(){ selected.splice(0); saveProductSelection(); $('matches').classList.add('hidden'); $('result').classList.add('hidden'); renderSelected() }
function setActiveMatch(index){ const buttons=[...$('matches').querySelectorAll('button.match')]; buttons.forEach((button,i)=>{const active=i===index;button.classList.toggle('active',active);button.setAttribute('aria-selected',String(active))}); activeMatch=index; if(index>=0)buttons[index].scrollIntoView({block:'nearest'}) }
function setActiveInstitutionMatch(index){ const buttons=[...$('institution-matches').querySelectorAll('button.match')]; buttons.forEach((button,i)=>{const active=i===index;button.classList.toggle('active',active);button.setAttribute('aria-selected',String(active))}); activeInstitutionMatch=index; if(index>=0)buttons[index].scrollIntoView({block:'nearest'}) }
function handleListKeys(event,boxId,getActive,setActive){ const box=$(boxId),buttons=[...box.querySelectorAll('button.match')]; if(box.classList.contains('hidden')||!buttons.length)return; const active=getActive(); if(event.key==='ArrowDown'){event.preventDefault();setActive((active+1)%buttons.length)}else if(event.key==='ArrowUp'){event.preventDefault();setActive(active<=0?buttons.length-1:active-1)}else if(event.key==='Enter'&&active>=0){event.preventDefault();buttons[active].click()}else if(event.key==='Escape'){event.preventDefault();box.classList.add('hidden');setActive(-1)} }
$('institution-search').addEventListener('input',()=>{clearTimeout(institutionTimer);setActiveInstitutionMatch(-1);institutionTimer=setTimeout(searchInstitutions,180)});
$('institution-search').addEventListener('keydown',event=>handleListKeys(event,'institution-matches',()=>activeInstitutionMatch,setActiveInstitutionMatch));
async function searchInstitutions(){ const q=$('institution-search').value.trim(),box=$('institution-matches');activeInstitutionMatch=-1;if(q.length<2){box.classList.add('hidden');return}try{const rows=await api('/api/institutions?q='+encodeURIComponent(q));box.replaceChildren();rows.forEach(institution=>{const b=node('button',undefined,'match'),main=node('span',undefined,'match-main');main.append(node('strong',institution.name),node('small',institution.full_address||'brak adresu'));b.setAttribute('role','option');b.setAttribute('aria-selected','false');b.append(main);b.onclick=()=>chooseInstitution(institution);box.append(b)});if(!rows.length)box.append(node('div','Brak pasujących punktów','match muted'));box.classList.remove('hidden')}catch(e){showInstitutionError(e)} }
async function chooseInstitution(institution){const input=$('institution-search');input.disabled=true;setProductAreaBusy(true);$('institution-matches').classList.add('hidden');$('institution-error').classList.add('hidden');$('institution-loading').classList.remove('hidden');try{const response=await api('/api/institution',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({institution_id:institution.id})});clearProductSelection();applyInstitution(response.status.selected_institution);updateStatus(response.status);input.value=''}catch(e){$('institution-picker').classList.remove('hidden');showInstitutionError(e)}finally{input.disabled=false;setProductAreaBusy(false);$('institution-loading').classList.add('hidden')} }
function showInstitutionError(e){$('institution-error').textContent=e.message;$('institution-error').classList.remove('hidden')}
$('change-institution').onclick=()=>{$('institution-selected').classList.add('hidden');$('institution-picker').classList.remove('hidden');$('institution-search').focus()};
$('search').addEventListener('input',()=>{clearTimeout(productTimer);setActiveMatch(-1);productTimer=setTimeout(search,180)});
$('search').addEventListener('keydown',event=>handleListKeys(event,'matches',()=>activeMatch,setActiveMatch));
async function search(){ const q=$('search').value.trim(), box=$('matches'); activeMatch=-1; if(!selectedInstitution||q.length<2){box.classList.add('hidden');return} try { const rows=await api('/api/products?q='+encodeURIComponent(q)); box.replaceChildren(); rows.forEach(p=>{ const b=node('button',undefined,'match'); b.setAttribute('role','option'); b.setAttribute('aria-selected','false'); b.append(node('span',p.name),node('span',money(p.price,p.currency),'price')); b.onclick=()=>add(p); box.append(b) }); if(!rows.length)box.append(node('div','Brak wyników','match muted')); box.classList.remove('hidden'); } catch(e){showError(e)} }
function add(p){ if(!selected.some(x=>x.name===p.name)){selected.push(p);saveProductSelection()} $('search').value=''; $('matches').classList.add('hidden'); activeMatch=-1; renderSelected() }
function renderSelected(){ const box=$('selected'); box.replaceChildren(); selected.forEach((p,i)=>{ const row=node('div',undefined,'selected'); const link=node('a',p.name); link.href=`https://diag.pl/sklep/badania/${encodeURIComponent(p.slug)}/`; link.target='_blank'; link.rel='noopener noreferrer'; link.title='Otwórz stronę badania w DIAG.pl'; row.append(link,node('span',money(p.price,p.currency),'price')); const remove=node('button','Usuń','danger'); remove.onclick=()=>{selected.splice(i,1);saveProductSelection();renderSelected()}; row.append(remove); box.append(row) }); if(!selected.length)box.append(node('span','Lista jest jeszcze pusta. Wyszukaj i dodaj pierwsze badanie.','empty')); const total=selected.reduce((sum,p)=>sum+Number(p.price||0),0); $('selected-total').textContent=money(total,selected[0]?.currency||'PLN'); $('clear-selected').disabled=productAreaBusy||!selected.length; $('optimize').disabled=productAreaBusy||!selectedInstitution||!selected.length }
$('clear-selected').onclick=clearProductSelection;
$('optimize').onclick=async()=>{ const button=$('optimize'); button.disabled=true; button.textContent='Optymalizuję…'; try { const r=await api('/api/optimize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({products:selected.map(x=>x.name)})}); renderResult(r); } catch(e){showError(e)} finally {button.disabled=!selected.length||!selectedInstitution;button.textContent='Oblicz najlepszy zestaw →'} };
function optimizationMethod(note){ return {'exact DP':'dokładna','ILP exact':'dokładna','greedy approximate':'przybliżona (algorytm zachłanny)'}[note]||note }
function renderResult(r){ const box=$('result-body'); box.replaceChildren(); const metrics=node('div',undefined,'metrics'); [['Cena osobno',r.original_sum,''],['Cena zestawu',r.optimized_sum,''],['Oszczędność',r.savings,'saving']].forEach(([label,value,cls])=>{const m=node('div',label,'metric '+cls);m.append(node('strong',money(value,r.currency)));metrics.append(m)}); box.append(metrics,node('small','Metoda optymalizacji: '+optimizationMethod(r.solver_note)));
if(r.warning)box.append(node('p',r.warning,'warning'));
r.chosen.forEach(item=>{const row=node('div',undefined,'choice'),text=node('span'),link=node('a',item.name);text.append(document.createTextNode(item.kind==='package'?'Pakiet: ':'Produkt: '),link);link.href=`https://diag.pl/sklep/${item.kind==='package'?'pakiety':'badania'}/${encodeURIComponent(item.slug)}/`;link.target='_blank';link.rel='noopener noreferrer';if(item.kind==='package')text.append(node('small','pokrywa: '+item.covered_names.join(', ')));row.append(text,node('span',money(item.price,r.currency),'price'));box.append(row)}); $('result').classList.remove('hidden'); $('result').scrollIntoView({behavior:'smooth'}) }
function showError(e){ const box=$('result-body');box.replaceChildren(node('div',e.message,'error'));$('result').classList.remove('hidden') }
$('refresh').onclick=async()=>{ const b=$('refresh'); if(!selectedInstitution||!confirm('Pobrać aktualne ceny dla wybranego punktu DIAG.pl?'))return; b.disabled=true;b.textContent='Pobieram…';try{const r=await api('/api/refresh',{method:'POST'});await loadStatus();clearProductSelection();alert(`Pobrano ${r.items} produktów i ${r.institutions} punktów pobrań.`)}catch(e){showError(e)}finally{b.disabled=!selectedInstitution;b.textContent='↻  Odśwież dane'} };
loadStatus();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    db = DEFAULT_DB

    def send_json(self, value: object, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                body = HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif parsed.path == "/api/status":
                self.send_json(database_status(self.db))
            elif parsed.path == "/api/products":
                query = parse_qs(parsed.query).get("q", [""])[0].strip()
                self.send_json(search_products(self.db, query) if len(query) >= 2 else [])
            elif parsed.path == "/api/institutions":
                query = parse_qs(parsed.query).get("q", [""])[0].strip()
                self.send_json(search_institutions(self.db, query) if len(query) >= 2 else [])
            else:
                self.send_json({"error": "Nie znaleziono"}, 404)
        except Exception as exc:  # noqa: BLE001 - API boundary
            self.send_json({"error": str(exc)}, 500)

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        try:
            if self.path == "/api/institution":
                length = int(self.headers.get("Content-Length", "0"))
                if length > 64_000:
                    raise ValueError("Żądanie jest za duże")
                payload = json.loads(self.rfile.read(length) or b"{}")
                institution_id = payload.get("institution_id")
                if not isinstance(institution_id, int) or isinstance(institution_id, bool) or institution_id <= 0:
                    raise ValueError("Wybierz prawidłowy punkt pobrań")
                if get_institution(self.db, institution_id) is None:
                    raise ValueError("Wybrany punkt pobrań nie istnieje")
                refresh = refresh_database(self.db, institution_id)
                self.send_json({"refresh": refresh, "status": database_status(self.db)})
            elif self.path == "/api/optimize":
                length = int(self.headers.get("Content-Length", "0"))
                if length > 64_000:
                    raise ValueError("Żądanie jest za duże")
                payload = json.loads(self.rfile.read(length) or b"{}")
                products = payload.get("products")
                if not isinstance(products, list) or not products or len(products) > 100 or not all(isinstance(x, str) for x in products):
                    raise ValueError("Podaj listę od 1 do 100 badań")
                self.send_json(optimize_products(self.db, products))
            elif self.path == "/api/refresh":
                status = database_status(self.db)
                institution = status["selected_institution"]
                if institution is None:
                    raise ValueError("Najpierw wybierz punkt pobrań")
                self.send_json(refresh_database(self.db, institution["id"]))
            else:
                self.send_json({"error": "Nie znaleziono"}, 404)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001 - API boundary
            self.send_json({"error": str(exc)}, 500)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def prepare_database(db: str) -> dict[str, object]:
    return initialize_database_if_needed(db)


def main() -> None:
    parser = PolishArgumentParser(description="Lokalny interfejs WWW DIAG.pl Optimize.")
    parser.add_argument("--adres", dest="host", default="127.0.0.1", metavar="ADRES", help="adres nasłuchiwania; domyślnie: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, metavar="NUMER", help="port serwera; domyślnie: 8765")
    parser.add_argument("--baza", dest="db", default=DEFAULT_DB, metavar="PLIK", help=f"ścieżka do bazy SQLite; domyślnie: {DEFAULT_DB}")
    parser.add_argument("--bez-przegladarki", dest="no_browser", action="store_true", help="nie otwieraj automatycznie przeglądarki")
    args = parser.parse_args()
    initialization = prepare_database(args.db)
    if initialization["initialized"]:
        print(f"Zainicjalizowano bazę: pobrano {initialization['institutions']} punktów pobrań.")
    Handler.db = args.db
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"DIAG.pl Optimize: {url} (Ctrl+C kończy)")
    if not args.no_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nZatrzymano.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
