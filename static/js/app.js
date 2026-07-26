(() => {
  const sidebar = document.querySelector('#sidebar');
  document.querySelector('[data-toggle-sidebar]')?.addEventListener('click', () => sidebar?.classList.toggle('open'));
  document.addEventListener('click', e => {
    if (e.target.matches('[data-dismiss]')) e.target.parentElement.remove();
    const copy = e.target.closest('[data-copy]');
    if (copy) {
      const target = document.querySelector(copy.dataset.copy);
      navigator.clipboard.writeText(target?.textContent || '');
      const old = copy.textContent; copy.textContent = 'Copied'; setTimeout(() => copy.textContent = old, 1200);
    }
  });
  document.querySelectorAll('[data-filter-input]').forEach(input => input.addEventListener('input', () => {
    const cls = input.dataset.filterInput, q = input.value.toLowerCase();
    document.querySelectorAll('.' + cls).forEach(el => el.hidden = !((el.dataset.filterValue || el.textContent).toLowerCase().includes(q)));
  }));
  const tabs = document.querySelector('[data-tabs]');
  if (tabs) tabs.addEventListener('click', e => {
    const button = e.target.closest('[data-tab]'); if (!button) return;
    tabs.querySelectorAll('button').forEach(b => b.classList.toggle('active', b === button));
    document.querySelectorAll('[data-panel]').forEach(p => p.hidden = p.dataset.panel !== button.dataset.tab);
  });
  const chart = document.querySelector('#metrics-chart');
  const dataEl = document.querySelector('#trend-data');
  if (chart && dataEl) drawChart(chart, JSON.parse(dataEl.textContent || '{}'));
  function drawChart(canvas, rows) {
    const ctx = canvas.getContext('2d'), ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth || 900, height = 300;
    canvas.width = width * ratio; canvas.height = height * ratio; ctx.scale(ratio, ratio);
    const dates = Object.keys(rows).sort(), metrics = ['downloads','crashes','anrs'];
    const palette = ['#1769e0','#c94254','#bd7a10'];
    const values = dates.flatMap(d => metrics.map(m => Number(rows[d][m] || 0)));
    const max = Math.max(...values, 1), pad = {l:42,r:16,t:18,b:32};
    ctx.font = '10px Inter, sans-serif'; ctx.strokeStyle = '#e7ebf1'; ctx.fillStyle = '#8090a3'; ctx.lineWidth = 1;
    for (let i=0;i<=4;i++) { const y=pad.t+(height-pad.t-pad.b)*i/4; ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(width-pad.r,y);ctx.stroke(); const label=Math.round(max*(1-i/4));ctx.fillText(label,4,y+3); }
    if (!dates.length) {ctx.fillText('No report data yet', width/2-42,height/2);return;}
    metrics.forEach((m,mi)=>{ctx.beginPath();ctx.strokeStyle=palette[mi];ctx.lineWidth=2;dates.forEach((d,i)=>{const x=pad.l+(width-pad.l-pad.r)*(dates.length===1?.5:i/(dates.length-1));const y=pad.t+(height-pad.t-pad.b)*(1-Number(rows[d][m]||0)/max);i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke()});
    ctx.fillStyle='#8090a3'; const step=Math.max(1,Math.ceil(dates.length/6)); dates.forEach((d,i)=>{if(i%step===0||i===dates.length-1){const x=pad.l+(width-pad.l-pad.r)*(dates.length===1?.5:i/(dates.length-1));ctx.fillText(d.slice(5),x-14,height-8)}});
  }
})();
