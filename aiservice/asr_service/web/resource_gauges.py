"""Live resource speedometers for the administration overview."""

STYLE = """
.resource-grid{grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.resource-card{border-radius:0!important;background-color:var(--card);background-image:radial-gradient(var(--line) .6px,transparent .6px);background-size:10px 10px;padding:16px}
.resource-title{display:flex;justify-content:space-between;gap:12px;font-weight:300}
.resource-title b{font-weight:400}.resource-note{font-weight:300;font-variant-numeric:tabular-nums}
.resource-dial{width:100%;max-width:220px;display:block;margin:6px auto 0;overflow:visible;direction:ltr}
.dial-track,.dial-fill{fill:none;stroke-width:9}.dial-track{stroke:var(--line)}
.dial-fill{stroke:var(--p)}.dial-needle{stroke:var(--ink);stroke-width:2}
.dial-number{fill:var(--ink);font-size:25px;font-weight:300}.dial-label{fill:var(--muted);font-size:9px}
.dial-tick{stroke:var(--muted);stroke-width:1}.resource-details{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;font-size:11px;font-weight:300}
.resource-dual{display:flex;gap:12px}.resource-dual>div{flex:1;min-width:0;text-align:center}
.resource-live-status{font-size:11px;font-weight:300;color:var(--muted)}
.resource-stale{opacity:.55}.resource-stale .dial-fill{stroke:var(--muted)}
"""

SCRIPT = r"""
function gaugeNumber(value,digits=1){return Number.isFinite(value)?fa(value.toFixed(digits)):'—'}
function resourceDial(value,label,display=null){
  let valid=Number.isFinite(value),p=valid?Math.max(0,Math.min(100,value)):0;
  let angle=Math.PI*(1-p/100),x=110+64*Math.cos(angle),y=102-64*Math.sin(angle);
  let ticks=Array.from({length:11},(_,i)=>{let a=Math.PI*(1-i/10);return `<line class="dial-tick" x1="${110+82*Math.cos(a)}" y1="${102-82*Math.sin(a)}" x2="${110+88*Math.cos(a)}" y2="${102-88*Math.sin(a)}"/>`}).join('');
  return `<svg class="resource-dial" viewBox="0 0 220 144" role="img" aria-label="${esc(label)}: ${esc(display??(gaugeNumber(value)+'٪'))}"><path class="dial-track" d="M 24 102 A 86 86 0 0 1 196 102"/><path class="dial-fill" d="M 24 102 A 86 86 0 0 1 196 102" pathLength="100" stroke-dasharray="${p} 100"/>${ticks}${valid?`<line class="dial-needle" x1="110" y1="102" x2="${x}" y2="${y}"/><circle cx="110" cy="102" r="4" fill="var(--p)"/>`:''}<text x="23" y="119" text-anchor="middle" class="dial-label">${fa(0)}</text><text x="197" y="119" text-anchor="middle" class="dial-label">${fa(100)}</text><text x="110" y="128" text-anchor="middle" class="dial-number">${esc(display??(gaugeNumber(value)+'٪'))}</text><title>${esc(label)}</title></svg>`;
}
function resourceCard(title,value,percent,note){return `<article class="resource-card"><div class="resource-title"><span>${title}</span></div>${resourceDial(percent,title,value)}<div class="resource-note">${note}</div></article>`}
function gpuResourceCard(g){
  let memory=g.memory_total?100*(g.memory_total-g.memory_free)/g.memory_total:null;
  let details=[['حافظه مصرف‌شده',gpuBytes(g.memory_total-g.memory_free)+' / '+gpuBytes(g.memory_total)],['کار فعال',fa(g.active??0)]];
  if(Number.isFinite(g.temperature_celsius))details.push(['دما',gaugeNumber(g.temperature_celsius)+' °C']);
  if(Number.isFinite(g.power_watts))details.push(['توان',gaugeNumber(g.power_watts)+' W'+(Number.isFinite(g.power_limit_watts)?' / '+gaugeNumber(g.power_limit_watts,0)+' W':'')]);
  if(Number.isFinite(g.fan_percent))details.push(['فن',gaugeNumber(g.fan_percent)+'٪']);
  return `<article class="resource-card"><div class="resource-title"><span>${esc(g.name)}</span><b dir="ltr">GPU ${fa(g.index)}</b></div><div class="resource-dual"><div>${resourceDial(g.utilization_percent,'پردازش GPU')}<div>پردازش GPU</div></div><div>${resourceDial(memory,'حافظه VRAM')}<div>حافظه VRAM</div></div></div><div class="resource-details">${details.map(([label,value])=>`<span>${label}: <b dir="ltr">${esc(value)}</b></span>`).join('')}</div></article>`;
}
function networkResourceCard(n,title){
  let rx=n.receive_bytes_per_second,tx=n.send_bytes_per_second;
  let maximum=Math.max(1024,2**Math.ceil(Math.log2(Math.max(rx||0,tx||0,1))));
  return `<article class="resource-card"><div class="resource-title"><span>${title}</span></div><div class="resource-dual"><div>${resourceDial(Number.isFinite(rx)?100*rx/maximum:null,'دریافت',Number.isFinite(rx)?bytes(rx)+'/s':'—')}<div>دریافت</div></div><div>${resourceDial(Number.isFinite(tx)?100*tx/maximum:null,'ارسال',Number.isFinite(tx)?bytes(tx)+'/s':'—')}<div>ارسال</div></div></div><div class="resource-note">مقیاس خودکار: ${esc(bytes(maximum))}/s · ${esc(n.interface||'—')}</div></article>`;
}
let metricsBusy=false;
async function refreshResourceGauges(){
  if(metricsBusy||!key||document.hidden||!$('resourceGrid')||location.pathname!='/admin')return;
  metricsBusy=true;
  let controller=new AbortController(),deadline=setTimeout(()=>controller.abort(),5000);
  let status=$('resourceLiveStatus');
  if(!status){status=document.createElement('span');status.id='resourceLiveStatus';status.className='resource-live-status';$('systemMeta').after(status)}
  try{
    let data=await api('/api/system-metrics',{signal:controller.signal});renderSystem(data);
    status.textContent='آخرین نمونه: '+new Date(data.sampled_at*1000).toLocaleTimeString('fa-IR')+' · هر ثانیه';
    $('resourceGrid').classList.remove('resource-stale');
  }catch(error){
    $('resourceGrid').classList.add('resource-stale');
    let status=$('resourceLiveStatus');if(status)status.textContent='SS-SYS-0001 · دریافت آمار قطع شد؛ اتصال سرویس را بررسی کنید.';
  }finally{clearTimeout(deadline);metricsBusy=false}
}
setInterval(refreshResourceGauges,1000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshResourceGauges()});
refreshResourceGauges();
"""
