/* Presentation-only progressive disclosure for the existing conversion owner.
 * Do not replace conversion requests, job state, resource checks or polling. */
(() => {
  'use strict';
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const targetNames = {onnx:'ONNX',sophon:'算能 BMODEL',rockchip:'瑞芯微 RKNN',ascend:'昇腾 OM',tensorrt:'TensorRT',paddle_inference:'Paddle'};

  const UI_STATUS_PRESETS = [
    ['全部',''],['执行中','running'],['已完成','done'],['失败','failed'],['等待资源','waiting_resource']
  ];

  function prepareStatusShortcuts(root, filters) {
    if (root.querySelector('.conversion-ui-quick-filters')) return;
    const select = [...filters.querySelectorAll('select')].find(el =>
      /status/i.test(el.name || el.id || '') ||
      [...el.options].some(option => option.value === 'waiting_resource')
    );
    if (!select) return; // The original server filter remains available.
    const possible = new Set([...select.options].map(option => option.value));
    const tabs = document.createElement('div');
    tabs.className = 'conversion-ui-quick-filters';
    tabs.setAttribute('role','group');
    tabs.setAttribute('aria-label','按转换状态筛选');
    for (const [label, value] of UI_STATUS_PRESETS) {
      if (!possible.has(value)) continue;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'conversion-ui-filter-button';
      button.dataset.conversionUiStatus = value;
      button.textContent = label;
      button.setAttribute('aria-pressed', String(select.value === value));
      button.addEventListener('click', () => {
        if (!root.isConnected || select.value === value) return;
        select.value = value;
        sync();
        // Reuse the canonical filter submit action, never client-filter a paged list.
        const form = select.closest('form');
        if (form && typeof form.requestSubmit === 'function') form.requestSubmit();
        else {
          const apply = [...filters.querySelectorAll('button')].find(el => /查询|筛选|应用/.test(el.textContent || ''));
          if (apply) apply.click();
          else select.dispatchEvent(new Event('change', {bubbles:true}));
        }
      });
      tabs.append(button);
    }
    if (tabs.children.length < 2) return;
    function sync() {
      for (const button of tabs.querySelectorAll('button')) {
        button.setAttribute('aria-pressed', String(select.value === button.dataset.conversionUiStatus));
      }
    }
    select.addEventListener('change', sync);
    root.querySelector('.conversion560-status-strip')?.after(tabs);
    if (!tabs.isConnected) (filters.closest('.conversion560-filter-shell') || filters).before(tabs);
  }

  function decorateHistory(root) {
    if (root.dataset.conversionWorkbenchReady === '1') return;
    root.dataset.conversionWorkbenchReady = '1';
    root.classList.add('conversion560-history');
    const top = root.querySelector('.convert428-top');
    const summary = root.querySelector('.convert428-summary');
    if (top && summary) {
      const summaryValues = [...summary.querySelectorAll(':scope > div')].map(cell => ({label:cell.querySelector('span')?.textContent||'',value:cell.querySelector('b')?.textContent||'0'}));
      const bar = document.createElement('div');
      bar.className = 'conversion560-status-strip';
      bar.setAttribute('aria-label','转换任务概览');
      bar.innerHTML = summaryValues.map(({label,value}) => `<span><strong>${escapeHtml(value)}</strong> ${escapeHtml(label.replace('筛选结果总数','当前筛选').replace('本页已产生产物','本页已产生产物').replace('本页进行中','本页进行中'))}</span>`).join('');
      top.insertAdjacentElement('afterend',bar);
    }
    const filters = root.querySelector('.convert428-history-filters');
    if (filters && !filters.closest('.conversion560-filter-shell')) {
      const details = document.createElement('details');
      details.className = 'conversion560-filter-shell';
      const summary = document.createElement('summary');
      summary.textContent = '高级筛选';
      details.append(summary);
      filters.before(details);
      details.append(filters);
      // A previous active filter must stay visible when returning to the list.
      details.open = filters.matches('form')
        ? [...new FormData(filters).values()].some(v => String(v).trim() !== '')
        : [...filters.querySelectorAll('input,select')].some(el => String(el.value || '').trim() !== '');
    }
    prepareStatusShortcuts(root, filters);
    const list = root.querySelector('.convert428-job-list');
    if (!list) return;
    list.classList.add('conversion560-list');
    const heading = document.createElement('div');
    heading.className = 'conversion560-columns';
    heading.innerHTML = '<span>转换目标</span><span>资源 / 配置</span><span>执行状态</span><span>操作</span>';
    list.before(heading);
    const detailHeader = document.createElement('div');
    detailHeader.className = 'conversion-ui-detail-header';
    detailHeader.hidden = true;
    detailHeader.innerHTML = '<button type="button" class="btn conversion-ui-back" data-conversion-ui-back>← 返回转换记录</button><div><strong data-conversion-ui-detail-title>转换详情</strong><small>执行概况、配置、产物与原始证据</small></div>';
    list.before(detailHeader);
    let lastScroll = 0;
    let lastTrigger = null;
    let previousDetails = null;
    let previousDetailsOpen = false;
    const modalScroll = () => root.closest('.modal-body') || root.closest('[role="dialog"]') || root;
    const closeDetail = () => {
      if(previousDetails?.isConnected)previousDetails.open = previousDetailsOpen;
      previousDetails = null;
      root.classList.remove('conversion-ui-inspecting');
      root.querySelector('.conversion-ui-inspected')?.classList.remove('conversion-ui-inspected');
      detailHeader.hidden = true;
      modalScroll().scrollTop = lastScroll;
      (lastTrigger?.isConnected ? lastTrigger : root.querySelector('[data-conversion-ui-open]'))?.focus({preventScroll:true});
    };
    root.addEventListener('click', event => {
      const more = event.target.closest('.conversion-ui-more');
      if(!more)root.querySelectorAll('.conversion-ui-more[open]').forEach(menu => {menu.open=false});
      else if(event.target.closest('.conversion-ui-more-list button,.conversion-ui-more-list a'))more.open=false;
      if (event.target.closest('[data-conversion-ui-back]')) { closeDetail(); return; }
      const trigger = event.target.closest('[data-conversion-ui-open]');
      if (!trigger) return;
      const job = trigger.closest('.convert428-job');
      if (!job) return;
      lastScroll = modalScroll().scrollTop;
      lastTrigger = trigger;
      root.querySelector('.conversion-ui-inspected')?.classList.remove('conversion-ui-inspected');
      job.classList.add('conversion-ui-inspected');
      root.classList.add('conversion-ui-inspecting');
      detailHeader.querySelector('[data-conversion-ui-detail-title]').textContent =
        job.querySelector('.convert428-job-title b')?.textContent?.trim() || '转换详情';
      detailHeader.hidden = false;
      const details = job.querySelector('.convert428-job-details');
      previousDetails = details;
      previousDetailsOpen = Boolean(details?.open);
      if (details) details.open = true;
      modalScroll().scrollTop = 0;
      detailHeader.querySelector('[data-conversion-ui-back]').focus({preventScroll:true});
    });
    for (const job of list.querySelectorAll(':scope > .convert428-job')) {
      job.classList.add('conversion560-job');
      const jobId=job.dataset.conversionJobId||'',record=window.versionConversionJob428?.(jobId);
      if(record&&['done','blocked_by_hardware'].includes(String(record.status||'').toLowerCase())&&
        /\.pt(?:h)?$/i.test(record.source_name||'')&&(record.outputs||[]).some(row=>/\.onnx$/i.test(row.name||''))) {
        const actions=job.querySelector('.convert428-actions');
        if(actions&&!actions.querySelector('[data-conversion-numeric]')) {
          const button=document.createElement('button');
          button.type='button';button.className='btn mini conversion560-numeric-action';button.textContent='数值验证';
          button.dataset.conversionNumeric='1';
          button.addEventListener('click',()=>window.openConversionNumeric560?.(root.dataset.versionConversionAid,root.dataset.versionConversionVid,jobId));
          actions.prepend(button);
        }
      }
      const actions = job.querySelector('.convert428-actions');
      if (actions && !actions.querySelector('[data-conversion-ui-open]')) {
        const open = document.createElement('button');
        open.type = 'button';
        open.className = 'btn mini conversion-ui-open';
        open.dataset.conversionUiOpen = '1';
        open.textContent = '查看详情';
        const originalActions = [...actions.children].filter(node => node.matches('button,a'));
        const primary = originalActions.find(node => /板端验证/.test(node.textContent || '')) ||
          originalActions.find(node => /下载/.test(node.textContent || '')) ||
          originalActions.find(node => node.dataset.conversionNumeric === '1') ||
          originalActions.find(node => /查看日志|日志/.test(node.textContent || ''));
        if (primary) primary.classList.add('conversion-ui-primary-action');
        const secondary = originalActions.filter(node => node !== primary);
        if (secondary.length) {
          const more = document.createElement('details');
          more.className = 'conversion-ui-more';
          const summary = document.createElement('summary');
          summary.textContent = '更多';
          summary.setAttribute('aria-label','更多转换操作');
          more.append(summary);
          const panel = document.createElement('div');
          panel.className = 'conversion-ui-more-list';
          secondary.forEach(node => panel.append(node));
          more.append(panel);
          actions.append(more);
        }
        actions.prepend(open);
      }
      const details = job.querySelector('.convert428-job-details');
      if (details) {
        const summary = details.querySelector('summary');
        if (summary) summary.textContent = '查看完整配置、证据与产物';
      }
      if(record?.target==='sophon'&&record.execution_evidence&&details){
        const status=record.execution_evidence.compiler_numeric_status;
        const line=document.createElement('div');line.className='conversion560-compiler-evidence';
        line.textContent=status==='passed_synthetic_reference'?'官方 SDK 编译数值对照：合成输入通过（真实图片仍需验证）':
          '官方 SDK 编译数值对照：未验证（请查看 SDK 能力及转换日志）';
        details.append(line);
      }
    }
  }

  function decorateCreate(form) {
    if (form.dataset.conversionWorkbenchReady === '1') return;
    form.dataset.conversionWorkbenchReady = '1';
    form.classList.add('conversion560-create');
    const allChildren = [...form.children];
    const main = document.createElement('div');
    main.className = 'conversion560-main';
    const sidebar = document.createElement('aside');
    sidebar.className = 'conversion560-aside';
    sidebar.innerHTML = `<div class="conversion560-aside-head"><span>本次转换概览</span><span class="conversion560-live-dot" aria-hidden="true"></span></div>
      <div class="conversion560-route"><div><small>源模型</small><strong id="conversion560Source">正在读取模型…</strong></div><span aria-hidden="true">↓</span><div><small>目标格式</small><strong id="conversion560Target">请选择转换目标</strong></div></div>
      <dl class="conversion560-aside-params"><div><dt>目标芯片</dt><dd id="conversion560Chip">—</dd></div><div><dt>输出精度</dt><dd id="conversion560Precision">—</dd></div><div><dt>输入尺寸</dt><dd id="conversion560Shape">—</dd></div><div><dt>转换资源</dt><dd id="conversion560Resource">待选择</dd></div></dl>
      <div class="conversion560-verification"><span>后续验证</span><small>模型转换完成不等于数值或板端验证通过。可在质量中心使用真实图片验证。</small></div>`;
    for (const node of allChildren) main.append(node);
    form.append(main,sidebar);
    const sections = main.querySelectorAll(':scope > section');
    const names = ['源模型','选择目标格式','','转换配置'];
    sections.forEach((section,index) => {
      section.classList.add('conversion560-section');
      const title = section.querySelector(':scope > b');
      if (title && names[index]) title.textContent = names[index];
    });
    if (sections[2]) sections[2].classList.add('conversion560-vendor-section');
    if (sections[3]) {
      sections[3].classList.add('conversion560-settings-section');
      const formRows=sections[3].querySelector(':scope > .form');
      if (formRows) formRows.classList.add('conversion560-primary-fields');
      const advance = document.createElement('details');
      advance.className = 'conversion560-advanced';
      advance.innerHTML = '<summary>高级设置 <span>CSC 设备适配</span></summary>';
      if(formRows)formRows.after(advance);else sections[3].prepend(advance);
      // Target-specific controls are primary configuration, not optional disclosure.
      // In particular INT8 calibration, TensorRT environment, ONNX opset and Sophon
      // preprocessing must remain reachable whenever the existing owner reveals them.
      for(const selector of ['#conv428OnnxFields','#conv428SophonFields','#conv428TensorRtFields','#conv428Calibration']) {
        const node=sections[3].querySelector(selector);
        if(node)sections[3].insertBefore(node,advance);
      }
      const csc=sections[3].querySelector('.convert428-csc');
      if(csc)advance.append(csc);
    }
    const buttons=main.querySelector('[data-convert-submit]')?.closest('.row.end');
    if(buttons)buttons.classList.add('conversion560-submit-bar');
    const sourceButton=main.querySelector('[data-convert-submit]');
    const args=sourceButton?.getAttribute('onclick')?.match(/submitConvert428\('([^']+)','([^']+)'\)/);
    if(args) {
      const back=document.createElement('button');
      back.className='btn';back.type='button';back.textContent='返回转换记录';
      back.addEventListener('click',async()=>{
        // A history modal must not be opened until the editor has fully closed.
        await window.closeModal?.();
        await window.openVersionConvert428?.(args[1],args[2]);
      });
      main.querySelector('.conversion560-submit-bar')?.prepend(back);
    }
    const update=()=>{
      if(!form.isConnected)return;
      const checked=form.querySelector('input[name="conv428Target"]:checked');
      const target=checked?.value||'',value=id=>form.querySelector(id)?.value||'';
      const show=(id,text)=>{const node=sidebar.querySelector(id),value=String(text||'—');if(node&&node.textContent!==value)node.textContent=value;};
      show('#conversion560Source',form.querySelector('.convert428-source strong')?.textContent||'读取中');
      show('#conversion560Target',checked?.closest('label')?.querySelector('b')?.textContent||targetNames[target]||'选择目标');
      show('#conversion560Chip',value('#conv428Chip')?.toUpperCase()||'不适用');
      show('#conversion560Precision',value('#conv428Precision')?.toUpperCase()||'自动');
      const h=target==='sophon'?value('#conv428Height'):value('#conv428Input');
      const w=target==='sophon'?value('#conv428Width'):h;
      show('#conversion560Shape',h&&w?`${w} × ${h}`:'按模型配置');
      const resource=form.querySelector('#conv428Resource');
      show('#conversion560Resource',resource?.selectedOptions?.[0]?.textContent||'待检测');
    };
    form.addEventListener('input',update);
    form.addEventListener('change',update);
    form.conversion560Update=update;
    update();
  }

  function decorate() {
    for(const root of document.querySelectorAll('.convert428-v2:not([data-conversion-workbench-ready])'))decorateHistory(root);
    for(const form of document.querySelectorAll('.convert428-create:not([data-conversion-workbench-ready])'))decorateCreate(form);
    for(const form of document.querySelectorAll('.convert428-create[data-conversion-workbench-ready]')){
      const main=form.querySelector('.conversion560-main');
      // Source/catalog loader inserts into the editor asynchronously.
      for(const id of ['conv428SourceLoad','conv428CatalogLoad']){
        const notice=form.querySelector(`:scope > #${id}`);
        if(notice&&main)main.prepend(notice);
      }
      form.conversion560Update?.();
    }
    // Backend counters are authoritative: do not replace server totals with the
    // number of records visible on the current paged list.
  }
  let scheduled=false;
  const schedule=()=>{if(scheduled)return;scheduled=true;queueMicrotask(()=>{scheduled=false;decorate();});};
  const observer=new MutationObserver(schedule);
  observer.observe(document.documentElement,{childList:true,subtree:true});
  schedule();
  window.ConversionWorkbenchUI=Object.freeze({refresh:decorate});
  window.openConversionNumeric560=async(aid,vid,jobId)=>{
    window.pendingConversionNumerical560={aid:String(aid||''),vid:String(vid||''),jobId:String(jobId||'')};
    await window.closeModal?.();
    await window.setPage?.('质量中心');
    await window.setQualityCenterTab411?.('detect');
    window.setScenarioMode64?.('conversion');
  };
})();
