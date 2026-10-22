"use strict";
(() => {
  let data = JSON.parse(document.getElementById('simulation-data').textContent);
  let selected = 'baseline', view = 'overview', trend = 'completed', product = 'all', station = 'M1';
  let comparisonMetric = 'completed';
  let playbackIndex = 0, timer = null, online = false, busy = false;
  const $ = id => document.getElementById(id);
  const colors = {processing:'#6b9d87',setup:'#dfb777',repair:'#d78b82',blocked:'#afa0c7',idle:'#e5e9ef'};
  const states = {processing:'加工',setup:'换模',repair:'维修',blocked:'阻塞',idle:'空闲'};
  const products = {P1:'#4e8b72',P2:'#82a4c6',P3:'#d4b27c',P4:'#aa9cbe'};
  const views = {overview:'仿真总览',economics:'成本与收益',comparison:'方案对比',timeline:'机床时间线',model:'模型与假设'};
  const policyNames = {fifo:'FIFO',same_family:'同类优先',aging:'超时优先'};
  const defaults = {horizon:2400,arrival_mean:10,batch_min:5,batch_max:20,machine_counts:{M1:2,M2:1,M3:2,M4:1,M5:2},buffer_capacity:50,processing_cv:.1,setup_time:15,mtbf:6000,mttr:240,failures_enabled:true,policy_name:'fifo',aging_threshold:120,sample_interval:20,product_prices:{P1:200,P2:180,P3:250,P4:300},machine_purchase_cost:500000,operating_cost_per_hour:100,operating_cost_basis:'machine_active'};
  const fmt = (v,d=0) => v == null || !Number.isFinite(v) ? '—' : v.toLocaleString('zh-CN',{maximumFractionDigits:d,minimumFractionDigits:d});
  const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const current = () => data.scenarios.find(s => s.id === selected) || data.scenarios[0];
  const metric = key => current().summary[key].mean;
  const sign = (v,d=1) => v == null ? '—' : (v>0?'+':'') + fmt(v,d);
  const ciText = (stat,d=1) => stat.ci95 == null ? '单次运行 · 无置信区间' : `95% CI ${fmt(stat.mean-stat.ci95,d)} – ${fmt(stat.mean+stat.ci95,d)}`;
  const money = v => v == null ? '—' : '¥'+fmt(v,2);
  const metricCards = cards => cards.map(([label,value,unit,icon,note])=>`<article class="metric-card"><div class="metric-label">${label}<span class="metric-icon">${icon}</span></div><div class="metric-value">${value}<small>${unit}</small></div><div class="metric-footer">${note}</div></article>`).join('');
  const legend = () => Object.keys(states).map(s=>`<span class="legend-item"><i class="legend-dot" style="background:${colors[s]}"></i>${states[s]}</span>`).join('');
  const table = (headers,rows,numberFrom=1) => `<table><thead><tr>${headers.map((h,i)=>`<th${i>=numberFrom?' class="number"':''}>${h}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map((v,i)=>`<td${i>=numberFrom?' class="number"':''}>${v}</td>`).join('')}</tr>`).join('')}</tbody></table>`;

  function initContext() {
    $('run-count').textContent=data.replications;
    $('horizon-label').textContent=fmt(data.base_config.horizon)+' min';
    $('seed-label').textContent=data.seeds.length>1?`${data.seeds[0]}–${data.seeds.at(-1)}`:data.seeds[0];
    $('generated-label').textContent='生成于 '+new Date(data.generated_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})+' CST';
    $('scenario-tabs').innerHTML=data.scenarios.map((s,i)=>`<button data-scenario="${s.id}" aria-pressed="${selected===s.id}" class="${selected===s.id?'active':''}">${i===0?'◉ ':''}${s.name}</button>`).join('');
    $('state-legend').innerHTML=legend(); $('timeline-legend').innerHTML=legend();
    $('product-filters').innerHTML=['all',...Object.keys(products)].map(p=>`<button data-product="${p}" aria-pressed="${p===product}" class="${p===product?'active':''}">${p==='all'?'全部路线':p}</button>`).join('');
  }

  function renderMetrics() {
    const s=current(), summary=s.summary, changed=s.id!=='baseline';
    const outputFooter=changed?`<span class="metric-tag ${s.output_change_pct<0?'negative':''}">${sign(s.output_change_pct)}%</span> 相对基准均值`:`${ciText(summary.completed,1)}`;
    const cards=[
      ['成品总产量',fmt(metric('completed'),1),'件','↗',outputFooter],
      ['平均完成周期',fmt(metric('mean_cycle_time'),1),'min','◷',`已完成件 · 含线外等待 · ${summary.mean_cycle_time.n}/${data.replications} 轮有样本`],
      ['平均加工利用率',fmt(metric('processing_utilization')*100,1),'%','▥',`换模占比 ${fmt(metric('setup_share')*100,1)}% · 维修 ${fmt(metric('repair_share')*100,1)}%`],
      ['期末线外待投料',fmt(metric('external'),1),'件','⇥',`线内在制 ${fmt(metric('wip'),1)} 件 · 到达 ${fmt(metric('arrived'),1)} 件`]
    ];
    $('metrics').innerHTML=metricCards(cards);
    $('economics-strip').innerHTML=[['销售收入','sales_revenue'],['运行成本','operating_cost'],['经营贡献','operating_contribution']].map(([label,key])=>`<div><span>${label}</span><b class="${key==='operating_contribution'&&metric(key)<0?'delta-negative':''}">${money(metric(key))}</b></div>`).join('')+'<a href="#economics">成本与收益分析 ↗</a><p>当前观察期均值 · 经营贡献仅扣除已知运行成本</p>';
  }

  function renderTrend() {
    document.querySelectorAll('[data-trend]').forEach(el=>el.classList.toggle('active',el.dataset.trend===trend));
    const s=current(), baseline=data.scenarios[0], W=640,H=220,pad={l:trend==='economics'?58:42,r:23,t:14,b:32}, w=W-pad.l-pad.r,h=H-pad.t-pad.b;
    const lines=trend==='completed'?[{rows:s.samples,key:'completed',color:'#3d8b6e',label:s.name},...(s.id!=='baseline'?[{rows:baseline.samples,key:'completed',color:'#adb8bd',label:'基准方案',dashed:true}]:[])]:trend==='economics'?[
      {rows:s.samples,key:'sales_revenue',color:'#3d8b6e',label:'累计销售收入'},{rows:s.samples,key:'operating_cost',color:'#c29359',label:'累计运行成本'}]:[
      {rows:s.samples,key:'external',color:'#89a5bf',label:'线外待投料'},{rows:s.samples,key:'wip',color:'#4d8d74',label:'线内在制'}];
    const peak=Math.max(1,...lines.flatMap(l=>l.rows.map(r=>r[l.key])));
    const unit=10**Math.floor(Math.log10(peak)), maxY=Math.ceil(peak/unit)*unit;
    const x=t=>pad.l+t/data.base_config.horizon*w,y=v=>pad.t+h-v/maxY*h;
    let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${trend==='completed'?'累计成品':trend==='economics'?'累计销售收入与运行成本':'线内在制与线外待投料'}随仿真时间的变化"><defs><linearGradient id="area-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#7ab697" stop-opacity=".2"/><stop offset="100%" stop-color="#7ab697" stop-opacity=".01"/></linearGradient></defs>`;
    for(let i=0;i<=4;i++){const v=maxY*i/4;svg+=`<line x1="${pad.l}" x2="${W-pad.r}" y1="${y(v)}" y2="${y(v)}" stroke="#edf0f2" stroke-dasharray="3 4"/><text x="${pad.l-12}" y="${y(v)+3}" text-anchor="end">${fmt(v)}</text>`;}
    for(let i=0;i<=5;i++){const t=data.base_config.horizon*i/5;svg+=`<text x="${x(t)}" y="${H-10}" text-anchor="middle">${fmt(t)}</text>`;}
    const points=l=>l.rows.map(r=>`${x(r.time)},${y(r[l.key])}`).join(' ');
    if(trend==='completed')svg+=`<polygon points="${x(0)},${y(0)} ${points(lines[0])} ${x(data.base_config.horizon)},${y(0)}" fill="url(#area-fill)"/>`;
    for(const l of [...lines].reverse())svg+=`<polyline points="${points(l)}" fill="none" stroke="${l.color}" stroke-width="2.2" ${l.dashed?'stroke-dasharray="5 5"':''} stroke-linecap="round" stroke-linejoin="round"/>`;
    svg+=`<text x="${pad.l}" y="7" style="font-size:8px">${trend==='economics'?'元':'件'}</text><text x="${W-pad.r}" y="${H-10}" dx="14" text-anchor="start" style="font-size:8px">min</text></svg>`;
    $('trend-chart').innerHTML=svg;
    $('trend-legend').innerHTML=lines.map(l=>`<span class="legend-item"><i class="legend-stroke" style="background:${l.color}"></i>${l.label}</span>`).join('');
    $('trend-subtitle').textContent=trend==='completed'?'各时点累计成品数 · 重复实验均值':trend==='economics'?'随完工确认收入，随计费时间累计成本 · 均值':'库存数量 · 重复实验均值 · 两类库存分别计数';
  }

  function renderProducts() {
    const s=current(), total=metric('completed'); let angle=0;
    const gradient=Object.keys(products).map(p=>{const start=angle;angle+=total?s.products[p].mean/total*360:0;return `${products[p]} ${start}deg ${angle}deg`;}).join(',');
    $('product-chart').innerHTML=`<div class="product-summary"><div class="donut" role="img" aria-label="${Object.keys(products).map(p=>p+' '+fmt(s.products[p].mean,1)+' 件').join('，')}" style="background:${total?'conic-gradient('+gradient+')':'#edf1f4'}"><div class="donut-center"><b>${fmt(total,1)}</b><small>平均成品 / 件</small></div></div><div class="product-total"><small>产品组合</small><b>4 种工艺路线</b><small style="margin-top:8px">${policyNames[s.config.policy_name]}</small></div></div><div>${Object.keys(products).map(p=>{const v=s.products[p].mean,percent=total?v/total*100:0;return `<div class="product-row"><span>${p}</span><span class="bar"><i style="width:${percent}%;background:${products[p]}"></i></span><span class="data-number">${fmt(v,1)}</span><span class="share">${fmt(percent)}%</span></div>`;}).join('')}</div>`;
  }

  function renderReplay() {
    const s=current(),samples=s.representative.samples;
    playbackIndex=Math.min(playbackIndex,samples.length-1);
    const sample=samples[playbackIndex],route=product==='all'?Object.keys(s.config.machine_counts):data.routes[product].map(r=>r[0]);
    $('replay-subtitle').textContent=`种子 ${s.representative.seed} · 每 ${fmt(s.config.sample_interval)} 分钟采样 · 回放数值为单次运行`;
    $('route-description').textContent=product==='all'?'各产品按各自工艺路线流转；选择产品可查看跳站路线':product+' 路线：'+data.routes[product].map(r=>r[0]).join(' → ');
    $('replay-inventory').textContent=`成品 ${fmt(sample.completed)} · 在制 ${fmt(sample.wip)} · 线外 ${fmt(sample.external)}`;
    $('production-line').innerHTML=Object.keys(s.config.machine_counts).map(n=>{
      const machines=Object.entries(sample.machines).filter(([name])=>name.startsWith(n+'-'));
      const count=sample.queues[n],ratio=count/s.config.buffer_capacity*100;
      return `<div class="station-node ${route.includes(n)?'':'dimmed'} ${station===n?'selected':''}" data-station="${n}" tabindex="0" role="button" aria-label="查看 ${n} 工位统计"><div class="station-node-top"><b>${n}</b><span>${machines.length} 台机床</span></div><div class="machines">${machines.map(([name,m])=>`<span class="machine-chip ${m.state}" title="${name}：${states[m.state]}${m.job_id?'，工件 #'+m.job_id:''}">${m.product||'—'} · ${states[m.state]}</span>`).join('')}</div><div class="buffer-label"><span>缓冲区</span><span>${count} / ${s.config.buffer_capacity}</span></div><div class="buffer-bar"><i class="${ratio>=100?'full':''}" style="width:${ratio}%"></i></div></div>`;
    }).join('');
    const slider=$('time-slider');slider.max=samples.length-1;slider.step=1;slider.value=playbackIndex;slider.setAttribute('aria-valuetext',fmt(sample.time)+' 分钟');
    $('playback-time').textContent=fmt(sample.time)+' min';$('playback-end').textContent=fmt(s.config.horizon)+' min';
  }

  function renderResources() {
    const s=current();
    $('utilization-chart').innerHTML=s.stations.map(row=>`<div class="util-row"><button class="station-select ${station===row.name?'active':''}" data-station="${row.name}">${row.name}</button><div class="state-bar" role="img" aria-label="${row.name} ${Object.keys(states).map(key=>states[key]+fmt(row.states[key]*100,1)+'%').join('，')}">${Object.keys(states).map(key=>`<span style="width:${row.states[key]*100}%;background:${colors[key]}" title="${states[key]} ${fmt(row.states[key]*100,1)}%"></span>`).join('')}</div><span class="util-value">${fmt(row.states.processing*100,1)}%</span></div>`).join('');
    const row=s.stations.find(r=>r.name===station);
    $('station-detail').innerHTML=`<b>${station}</b> · ${row.machine_count} 台机床 · ${fmt(row.setup_count.mean,1)} 次换模 · ${fmt(row.failure_count.mean,1)} 次故障<br>平均排队 ${fmt(row.mean_queue.mean,1)} 件，已派工工件平均等待 ${fmt(row.mean_wait.mean,1)} min。`;
    $('queue-table').innerHTML=table(['工位','平均队长 / 件','平均等待 / min','期末排队 / 件'],s.stations.map(r=>[r.name,fmt(r.mean_queue.mean,1),fmt(r.mean_wait.mean,1),fmt(r.waiting_at_end.mean,1)]));
    const ranked=[...s.stations].sort((a,b)=>(b.states.processing+b.states.setup)-(a.states.processing+a.states.setup));
    const possible=ranked[0];
    $('insight').innerHTML=`<span>◈</span><div><b>${possible.name} 的加工与换模占比最高（${fmt((possible.states.processing+possible.states.setup)*100,1)}%）。</b> 可结合排队与阻塞进一步检查瓶颈。<small>这是本组实验的瓶颈线索，仍需扩容对照验证；当前线外待投料均值为 ${fmt(metric('external'),1)} 件。</small></div>`;
  }

  function renderComparisonChart(key, target) {
    const unit=key==='completed'?'件':'元';
    const W=950,H=280,l=112,r=130,t=20,b=35,w=W-l-r;
    const upper=Math.max(1,...data.scenarios.map(s=>s.summary[key].mean+(s.summary[key].ci95||0)));
    const lower=Math.min(0,...data.scenarios.map(s=>s.summary[key].mean-(s.summary[key].ci95||0)));
    const x=v=>l+(v-lower)/(upper-lower)*w;
    let svg=`<svg viewBox="0 0 ${W} ${H}" class="comparison-svg" role="img" aria-label="五种方案的${key==='completed'?'平均成品数':'平均经营贡献'}与95%置信区间">`;
    for(let i=0;i<=4;i++){let val=lower+(upper-lower)*i/4;svg+=`<line x1="${x(val)}" x2="${x(val)}" y1="${t}" y2="${H-b}" stroke="#edf1f3" stroke-dasharray="3 4"/><text x="${x(val)}" y="${H-9}" text-anchor="middle">${fmt(val)} ${unit}</text>`;}
    svg+=`<line x1="${x(0)}" x2="${x(0)}" y1="${t}" y2="${H-b}" stroke="#ccd5d0"/>`;
    data.scenarios.forEach((s,i)=>{const v=s.summary[key],y=t+16+i*43,selectedColor=v.mean<0?'#d49a91':s.id===selected?'#4d8c70':'#b9d1c2';
      svg+=`<text x="${l-15}" y="${y+4}" text-anchor="end">${s.name}</text><rect x="${Math.min(x(0),x(v.mean))}" y="${y-10}" width="${Math.abs(x(v.mean)-x(0))}" height="20" fill="${selectedColor}" rx="3"/>`;
      if(v.ci95!=null){const lo=x(v.mean-v.ci95),hi=x(v.mean+v.ci95);svg+=`<path d="M${lo},${y}H${hi}M${lo},${y-5}V${y+5}M${hi},${y-5}V${y+5}" stroke="#557761" stroke-width="1.5" fill="none"/>`;}
      svg+=`<text x="${W-r+15}" y="${y+4}" style="fill:#56755f">${fmt(v.mean,1)}${key==='completed'&&s.id!=='baseline'?'  ('+sign(s.output_change_pct)+'%)':''}</text>`;
    });svg+='</svg>';
    const zero=(0-lower)/(upper-lower)*100;
    const mobile=`<div class="mobile-comparison">${data.scenarios.map(s=>{
      const stat=s.summary[key],end=(stat.mean-lower)/(upper-lower)*100;
      return `<div class="mobile-comparison-row ${s.id===selected?'selected':''}"><div><span>${s.name}</span><b class="${stat.mean<0?'delta-negative':''}">${fmt(stat.mean,1)} ${unit}</b></div><div class="mobile-comparison-track"><i style="left:${Math.min(zero,end)}%;width:${Math.abs(end-zero)}%;background:${stat.mean<0?'#d49a91':'#75a58d'}"></i><em style="left:${zero}%"></em></div><small>${ciText(stat,1)}</small></div>`;
    }).join('')}</div>`;
    $(target).innerHTML=svg+mobile;
  }

  function renderComparison() {
    renderComparisonChart(comparisonMetric, 'comparison-chart');
    document.querySelectorAll('[data-comparison]').forEach(el=>{el.classList.toggle('active',el.dataset.comparison===comparisonMetric);el.setAttribute('aria-pressed',el.dataset.comparison===comparisonMetric);});
    $('comparison-table').innerHTML=`<table><thead><tr><th>实验方案</th><th class="number">成品均值 / 件</th><th class="number">配对差值 / 件</th><th class="number">差值 95% CI / 件</th><th class="number">平均周期 / min</th><th class="number">期末线外 / 件</th></tr></thead><tbody>${data.scenarios.map(s=>{const p=s.paired_output_difference;return `<tr class="${s.id===selected?'compare-highlight':''}"><td><button class="text-button" data-scenario="${s.id}">${s.name}</button></td><td class="number">${fmt(s.summary.completed.mean,1)}</td><td class="number ${p.mean>=0?'delta-positive':'delta-negative'}">${s.id==='baseline'?'—':sign(p.mean)}</td><td class="number">${s.id==='baseline'||p.ci95==null?'—':fmt(p.mean-p.ci95,1)+' ~ '+fmt(p.mean+p.ci95,1)}</td><td class="number">${fmt(s.summary.mean_cycle_time.mean,1)}</td><td class="number">${fmt(s.summary.external.mean,1)}</td></tr>`;}).join('')}</tbody></table>`;
    $('runs-table').innerHTML=table(['种子','到达 / 件','成品 / 件','线内 / 件','线外 / 件','平均周期 / min','收入 / 元','成本 / 元','经营贡献 / 元'],current().runs.map(r=>[r.seed,fmt(r.arrived),fmt(r.completed),fmt(r.wip),fmt(r.external),fmt(r.mean_cycle_time,1),fmt(r.sales_revenue,2),fmt(r.operating_cost,2),fmt(r.operating_contribution,2)]));
    if(comparisonMetric==='operating_contribution')$('comparison-table').innerHTML=economicTable();
  }

  function paybackLabel(investment) {
    if(investment.status==='no_additional_capex')return '无需新增购机';
    if(investment.payback_periods==null)return '无法回收（增量≤0）';
    return fmt(investment.payback_periods,1)+' 个观察期'+(investment.status==='uncertain_gain'?'（方向未确认）':'');
  }

  function economicTable() {
    return table(['方案','销售收入 / 元','运行成本 / 元','经营贡献 / 元','贡献配对增量 / 元','增量 95% CI / 元','新增购机 / 元'],data.scenarios.map(s=>{
      const p=s.paired_contribution_difference;
      return [`<button class="text-button" data-scenario="${s.id}">${s.name}</button>`,fmt(s.summary.sales_revenue.mean,2),fmt(s.summary.operating_cost.mean,2),`<strong class="${s.summary.operating_contribution.mean<0?'delta-negative':'delta-positive'}">${fmt(s.summary.operating_contribution.mean,2)}</strong>`,s.id==='baseline'?'—':sign(p.mean,2),s.id==='baseline'||p.ci95==null?'—':`${fmt(p.mean-p.ci95,2)} ~ ${fmt(p.mean+p.ci95,2)}`,fmt(s.investment.additional_capex)];
    }));
  }

  function renderEconomics() {
    const s=current(), c=s.config, summary=s.summary;
    const hours=c.horizon/60, count=Object.values(c.machine_counts).reduce((a,b)=>a+b,0), investment=s.investment;
    const basis=data.operating_cost_bases[c.operating_cost_basis];
    $('economics-subtitle').textContent=`${s.name} · 每个观察期 ${fmt(hours,2)} 个工作小时 · ${data.replications} 次重复均值`;
    $('economic-metrics').innerHTML=metricCards([
      ['销售收入',fmt(summary.sales_revenue.mean,2),'元','↗',ciText(summary.sales_revenue,2)],
      ['运行成本',fmt(summary.operating_cost.mean,2),'元','◷',c.operating_cost_basis==='machine_active'?ciText(summary.operating_cost,2):`${c.operating_cost_basis==='line_calendar'?'整条产线':count+' 台机床'} · 费率 ${money(c.operating_cost_per_hour)}/h`],
      ['经营贡献',fmt(summary.operating_contribution.mean,2),'元','¥',ciText(summary.operating_contribution,2)],
      ['相对基准新增购机',fmt(investment.additional_capex),'元','＋',`当前配置设备价值 ${money(count*c.machine_purchase_cost)} · 单独列示`]
    ]);
    $('economic-metrics').children[2].querySelector('.metric-value').classList.toggle('delta-negative',summary.operating_contribution.mean<0);
    const total=summary.sales_revenue.mean;
    $('revenue-table').innerHTML=table(['产品','售价 / 元','成品 / 件','收入 / 元'],Object.keys(products).map(p=>[
      `<span class="revenue-product"><i style="background:${products[p]}"></i>${p}</span>`,fmt(c.product_prices[p],2),fmt(s.products[p].mean,1),`<span class="revenue-cell">${fmt(s.product_revenues[p].mean,2)}<i style="width:${total?s.product_revenues[p].mean/total*100:0}%;background:${products[p]}"></i></span>`
    ]));
    $('cost-basis-label').textContent=basis;
    const chargeableHours=c.operating_cost_basis==='line_calendar'?hours:c.operating_cost_basis==='machine_calendar'?count*hours:s.stations.reduce((sum,row)=>sum+row.machine_count*hours*(row.states.processing+row.states.setup),0);
    const formula=c.operating_cost_basis==='machine_calendar'?`${count} 台 × ${fmt(hours,2)} h × ${fmt(c.operating_cost_per_hour,2)} 元/(台·h)`:c.operating_cost_basis==='line_calendar'?`${fmt(hours,2)} h × ${fmt(c.operating_cost_per_hour,2)} 元/h`:`${fmt(chargeableHours,2)} 台时 × ${fmt(c.operating_cost_per_hour,2)} 元/(台·h)`;
    $('cost-ledger').innerHTML=`<div class="ledger-formula">${formula}</div><div class="ledger-row"><span>销售收入</span><b>${money(total)}</b></div><div class="ledger-row"><span>减：运行成本</span><b>${money(summary.operating_cost.mean)}</b></div><div class="ledger-row total"><span>观察期经营贡献</span><b class="${summary.operating_contribution.mean<0?'delta-negative':''}">${money(summary.operating_contribution.mean)}</b></div>`;
    renderComparisonChart('operating_contribution','economics-chart');
    $('economics-table').innerHTML=economicTable();
    const expanded=data.scenarios.find(row=>row.id==='m4_extra'), inv=expanded.investment, delta=expanded.paired_contribution_difference;
    const uncertainty=delta.ci95==null?'仅一次重复，无法估计增量的不确定性。':delta.mean-delta.ci95<=0&&delta.mean+delta.ci95>=0?'增量区间包含 0，当前重复实验尚不能确认收益方向。':delta.mean+delta.ci95<0?'增量区间完全低于 0，当前实验显示扩容降低经营贡献。':'增量区间完全高于 0，当前实验支持经营贡献增加。';
    $('investment-analysis').innerHTML=`<div class="investment-grid"><div><small>新增投资</small><b>${money(inv.additional_capex)}</b><span>${inv.additional_machines} 台 × ${money(expanded.config.machine_purchase_cost)}/台</span></div><div><small>每观察期经营贡献增量</small><b class="${delta.mean<0?'delta-negative':'delta-positive'}">${sign(delta.mean,2)} 元</b><span>${ciText(delta,2)}</span></div><div><small>简单回收期</small><b class="payback-value">${paybackLabel(inv)}</b><span>${inv.payback_work_hours==null?'仅在新增投资与贡献增量均为正时计算':fmt(inv.payback_work_hours,1)+' 个累计工作小时'}</span></div></div><p class="investment-conclusion">${uncertainty} 首个观察期的增量现金（贡献增量 − 新增购机款）为 <strong>${money(inv.first_period_incremental_cash)}</strong>。</p>`;
  }

  function renderTimeline() {
    const s=current(),filter=$('timeline-station').value,machines=s.representative.machines.filter(m=>filter==='all'||m.station===filter),horizon=s.config.horizon;
    $('timeline-subtitle').textContent=`${s.name} · 种子 ${s.representative.seed} · 第一轮实际状态区间 · [0, ${fmt(horizon)}) min`;
    $('gantt-chart').innerHTML=`<div class="gantt"><div class="gantt-axis">${Array.from({length:6},(_,i)=>`<span>${fmt(horizon*i/5)} min</span>`).join('')}</div>${machines.map(m=>`<div class="gantt-row"><span class="gantt-label">${m.name}</span><div class="gantt-track">${m.intervals.map(row=>{const label=`${m.name} · ${states[row.state]} · ${fmt(row.time,2)}–${fmt(row.end,2)} min${row.job_id?' · '+row.product+' #'+row.job_id:''}`;return `<span class="gantt-segment" style="left:${row.time/horizon*100}%;width:${(row.end-row.time)/horizon*100}%;background:${colors[row.state]}" title="${label}" tabindex="0" aria-label="${label}"></span>`;}).join('')}</div></div>`).join('')}</div>`;
    const events=machines.flatMap(m=>m.intervals.map(e=>({...e,machine:m.name}))).sort((a,b)=>b.time-a.time).slice(0,60);
    $('events-table').innerHTML=table(['机床','状态','产品 / 工件','开始 / min','结束 / min','持续 / min'],events.map(e=>[e.machine,`<span class="machine-chip ${e.state}">${states[e.state]}</span>`,e.job_id?`${e.product} / #${e.job_id}`:'—',fmt(e.time,2),fmt(e.end,2),fmt(e.end-e.time,2)]),3);
  }

  function renderModel() {
    const s=current();
    $('routes-table').innerHTML=table(['产品','到达比例','售价 / 元','工艺路线（加工均值 / min）'],Object.keys(products).map(p=>[p,fmt(data.product_mix[p]*100)+'%',fmt(s.config.product_prices[p],2),data.routes[p].map(([st,d])=>`${st}(${d})`).join(' → ')]),99);
    $('assumptions').innerHTML=data.assumptions.map(a=>`<li>${esc(a)}</li>`).join('');
    $('censored-table').innerHTML=table(['当前方案：'+s.name,'期末仍排队 / 件','已等待时长 / min','有等待样本的重复次数'],s.stations.map(r=>[r.name,fmt(r.waiting_at_end.mean,1),fmt(r.censored_wait_mean.mean,1),`${r.censored_wait_mean.n} / ${data.replications}`]));
    $('model-config').innerHTML=table(['当前方案参数','数值'],[
      ['调度规则',policyNames[s.config.policy_name]],['机床数量',Object.entries(s.config.machine_counts).map(([n,v])=>`${n}: ${v}`).join(' / ')],
      ['换模 / 缓冲',`${s.config.setup_time} min / ${s.config.buffer_capacity} 件`],['到达 / 批量',`EXPO(${s.config.arrival_mean}) min / U{${s.config.batch_min}, …, ${s.config.batch_max}}`],
      ['加工时间',`正态分布，CV = ${s.config.processing_cv}；非正样本重抽`],['故障 / 维修',s.config.failures_enabled?`EXPO(${s.config.mtbf}) / EXPO(${s.config.mttr}) min`:'故障关闭'],
      ['运行费率与口径',`${money(s.config.operating_cost_per_hour)}/h · ${data.operating_cost_bases[s.config.operating_cost_basis]}`],
      ['机床购置单价',money(s.config.machine_purchase_cost)+'/台；相对当前基准计新增投资'],
      ['超时优先阈值',s.config.aging_threshold+' min'],['单次回放检查',s.representative.checks.conservation_error===0&&s.representative.checks.buffer_capacity_respected&&s.representative.checks.state_time_conserved?'数量、容量与状态时间检查通过':'请复核检查记录']]);
  }

  function render() {
    initContext();renderMetrics();renderTrend();renderProducts();renderReplay();renderResources();
    if(view==='comparison')renderComparison();
    if(view==='economics')renderEconomics();
    if(view==='timeline')renderTimeline();
    if(view==='model')renderModel();
  }
  function navigate(next) {
    view=views[next]?next:'overview';
    document.querySelectorAll('.view').forEach(el=>el.hidden=el.id!==`view-${view}`);
    document.querySelectorAll('[data-view]').forEach(el=>{el.classList.toggle('active',el.dataset.view===view);if(el.dataset.view===view)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
    $('breadcrumb').textContent=views[view];
    if(view!=='overview')stopPlayback();
    render();
  }
  function selectScenario(id) {selected=id;playbackIndex=0;stopPlayback();render();}
  function stopPlayback() {if(timer)clearInterval(timer);timer=null;$('play-button').textContent='▶';$('play-button').setAttribute('aria-label','播放回放');}
  function play() {
    if(timer){stopPlayback();return;}
    if(playbackIndex>=current().representative.samples.length-1)playbackIndex=0;
    $('play-button').textContent='Ⅱ';$('play-button').setAttribute('aria-label','暂停回放');
    timer=setInterval(()=>{playbackIndex=Math.min(playbackIndex+Number($('playback-speed').value),current().representative.samples.length-1);renderReplay();if(playbackIndex>=current().representative.samples.length-1)stopPlayback();},280);
  }

  const field=(name,label,value,min,max,step=1)=>`<label class="field">${label}<input type="number" name="${name}" value="${value}" min="${min}" max="${max}" step="${step}" required></label>`;
  function populateForm(config=data.base_config,reps=data.replications,seed=data.seeds[0]) {
    $('main-fields').innerHTML=field('horizon','仿真时长 / min',config.horizon,1,14400)+field('replications','重复次数 / 组',reps,1,30)+field('seed','起始随机种子',seed,0,2147483617)+field('processing_cv','加工时间 CV',config.processing_cv,0,1,.01);
    $('machine-fields').innerHTML=Object.entries(config.machine_counts).map(([k,v])=>field(k,k+' / 台',v,1,8)).join('');
    $('resource-fields').innerHTML=field('buffer_capacity','每工位缓冲 / 件',config.buffer_capacity,1,500)+field('setup_time','不同产品换模 / min',config.setup_time,0,2400,.1);
    $('arrival-fields').innerHTML=field('arrival_mean','平均到达间隔 / min',config.arrival_mean,1,10000,.1)+field('mtbf','平均故障间隔 / min',config.mtbf,1,1000000,.1)+field('batch_min','最小批量 / 件',config.batch_min,1,100)+field('batch_max','最大批量 / 件',config.batch_max,1,100)+field('mttr','平均维修时间 / min',config.mttr,.1,100000,.1);
    $('price-fields').innerHTML=Object.keys(products).map(p=>field('price_'+p,p+' 售价 / 元每件',config.product_prices[p],0,1e9,.01)).join('');
    $('cost-fields').innerHTML=field('machine_purchase_cost','机床购置成本 / 元每台',config.machine_purchase_cost,0,1e9,.01)+field('operating_cost_per_hour','运行费率 / 元每小时',config.operating_cost_per_hour,0,1e9,.01);
    $('cost-basis-select').innerHTML=Object.entries(data.operating_cost_bases).map(([key,label])=>`<option value="${key}">${label}</option>`).join('');
    $('cost-basis-select').value=config.operating_cost_basis;
    $('config-form').elements.failures_enabled.checked=config.failures_enabled;
    $('config-form').elements.policy_name.value=config.policy_name;
    $('form-error').hidden=true;$('run-button').disabled=!online||busy;
    if(!online){$('form-error').textContent='当前为离线快照。运行 uv run soft-procedure serve 后，在 http://127.0.0.1:8765 中重新计算。';$('form-error').hidden=false;}
  }
  function showStatus(text,error=false,running=false) {const box=$('run-status');box.textContent=text;box.hidden=false;box.className='status-message'+(error?' error':'')+(running?' busy':'');}
  async function run(event) {
    event.preventDefault();if(!online||busy)return;
    const form=new FormData($('config-form')),config={...data.base_config,machine_counts:{},product_prices:{}};
    for(const key of ['horizon','processing_cv','buffer_capacity','setup_time','arrival_mean','batch_min','batch_max','mtbf','mttr','machine_purchase_cost','operating_cost_per_hour'])config[key]=Number(form.get(key));
    for(const key of Object.keys(defaults.machine_counts))config.machine_counts[key]=Number(form.get(key));
    for(const key of Object.keys(products))config.product_prices[key]=Number(form.get('price_'+key));
    config.operating_cost_basis=form.get('operating_cost_basis');
    config.failures_enabled=$('config-form').elements.failures_enabled.checked;config.policy_name=form.get('policy_name');
    const replications=Number(form.get('replications')),seed=Number(form.get('seed'));
    if(config.batch_min>config.batch_max){$('form-error').textContent='最小批量不能大于最大批量。';$('form-error').hidden=false;return;}
    busy=true;stopPlayback();$('run-button').disabled=true;$('config-button').disabled=true;$('config-dialog').close();
    showStatus(`正在运行 5 组方案 × ${replications} 次重复。完成后将更新全部图表…`,false,true);
    const start=performance.now();
    try {
      const response=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({config,replications,seed})});
      const payload=await response.json();if(!response.ok)throw new Error(payload.error||'实验运行失败');
      data=payload;playbackIndex=0;render();
      showStatus(`实验完成 · ${5*replications} 次运行 · 用时 ${fmt((performance.now()-start)/1000,1)} 秒 · 图表与导出结果已更新。`);
    } catch(error){showStatus(`未能完成实验：${error.message}。当前仍展示上一组结果。`,true);}
    finally {busy=false;$('config-button').disabled=false;$('run-button').disabled=!online;}
  }

  function download(content,type,name) {const url=URL.createObjectURL(new Blob([content],{type}));const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);}
  function csvRows(onlySelected=false) {
    const rows=(onlySelected?[current()]:data.scenarios).flatMap(s=>s.runs.map(r=>({scenario:s.id,...r})));
    return toCSV(rows);
  }
  function toCSV(rows) {
    const headers=Object.keys(rows[0]);const cell=v=>'"'+String(v??'').replaceAll('"','""')+'"';
    return '\ufeff'+[headers,...rows.map(row=>headers.map(k=>row[k]))].map(r=>r.map(cell).join(',')).join('\r\n');
  }
  function economicCSV() {
    return toCSV(data.scenarios.map(s=>({scenario:s.id,operating_cost_basis:s.config.operating_cost_basis,period_hours:s.config.horizon/60,sales_revenue:s.summary.sales_revenue.mean,operating_cost:s.summary.operating_cost.mean,operating_contribution:s.summary.operating_contribution.mean,paired_contribution_mean:s.paired_contribution_difference.mean,paired_contribution_ci95:s.paired_contribution_difference.ci95,...s.investment})));
  }
  function exportData(kind) {
    $('export-dialog').close();
    if(kind==='json')download(JSON.stringify(data,null,2),'application/json','flexline-results.json');
    if(kind==='csv')download(csvRows(),'text/csv;charset=utf-8','flexline-replications.csv');
    if(kind==='economics')download(economicCSV(),'text/csv;charset=utf-8','flexline-economics.csv');
    if(kind==='html'){
      stopPlayback();const clone=document.documentElement.cloneNode(true);
      clone.querySelector('#simulation-data').textContent=JSON.stringify(data).replaceAll('<','\\u003c');
      clone.querySelectorAll('dialog').forEach(d=>d.removeAttribute('open'));clone.querySelector('#run-status').hidden=true;clone.querySelector('#toast').hidden=true;
      download('<!doctype html>\n'+clone.outerHTML,'text/html;charset=utf-8','flexline-dashboard.html');
    }
    $('toast').textContent='导出文件已准备';$('toast').hidden=false;setTimeout(()=>$('toast').hidden=true,2500);
  }

  document.addEventListener('click',event=>{
    const target=event.target.closest('button,a,[data-station]');if(!target)return;
    if(target.dataset.view)return;
    if(target.dataset.navigate){location.hash=target.dataset.navigate;return;}
    if(target.dataset.scenario){selectScenario(target.dataset.scenario);return;}
    if(target.dataset.product){product=target.dataset.product;initContext();renderReplay();return;}
    if(target.dataset.station){station=target.dataset.station;renderReplay();renderResources();return;}
    if(target.dataset.trend){trend=target.dataset.trend;document.querySelectorAll('[data-trend]').forEach(el=>el.classList.toggle('active',el.dataset.trend===trend));renderTrend();return;}
    if(target.dataset.comparison){comparisonMetric=target.dataset.comparison;renderComparison();return;}
    if(target.dataset.close){$(target.dataset.close).close();return;}
    if(target.dataset.export){exportData(target.dataset.export);return;}
  });
  document.addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ')&&event.target.matches('.station-node')){event.preventDefault();station=event.target.dataset.station;renderReplay();renderResources();}});
  $('play-button').addEventListener('click',play);
  $('time-slider').addEventListener('input',()=>{stopPlayback();playbackIndex=Number($('time-slider').value);renderReplay();});
  $('timeline-station').addEventListener('change',renderTimeline);
  $('config-button').addEventListener('click',()=>{populateForm();$('config-dialog').showModal();});
  $('reset-config').addEventListener('click',()=>populateForm(defaults,10,42));
  $('export-button').addEventListener('click',()=>$('export-dialog').showModal());
  $('config-form').addEventListener('submit',run);
  $('download-runs').addEventListener('click',()=>download(csvRows(true),'text/csv;charset=utf-8',`flexline-${selected}-runs.csv`));
  $('download-economics').addEventListener('click',()=>download(economicCSV(),'text/csv;charset=utf-8','flexline-economics.csv'));
  window.addEventListener('hashchange',()=>navigate(location.hash.slice(1)));
  navigate(location.hash.slice(1));
  if(location.protocol==='http:'||location.protocol==='https:')fetch('/api/health').then(r=>r.ok?r.json():null).then(r=>{online=r?.engine==='SimPy';$('mode-badge').textContent=online?'本地引擎已连接':'离线结果快照';}).catch(()=>$('mode-badge').textContent='离线结果快照');
  else $('mode-badge').textContent='离线结果快照';
})();
