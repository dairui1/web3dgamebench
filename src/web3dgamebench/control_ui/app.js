/* Web3DGameBench Matrix control console — client logic (no external assets, localhost only). */
(function () {
  'use strict';

  const TOKEN = (document.querySelector('meta[name="control-token"]') || {}).content || '';
  const $ = (id) => document.getElementById(id);

  // ------------------------------------------------------------------
  // Static vocab
  // ------------------------------------------------------------------

  const CELL_STATUS = {
    pending: { label: '待执行', icon: 'i-circle', cls: 'cell-pending', kind: 'pending', chip: 'chip-neutral', tag: '·' },
    running: { label: '运行中', icon: 'i-loader', cls: 'cell-running', kind: 'running', chip: 'chip-cyan', spin: true, tag: '运行' },
    completed: { label: '可打开游玩', icon: 'i-check', cls: 'cell-completed', kind: 'completed', chip: 'chip-green', tag: '成功' },
    'candidate-failure': { label: '无法构建或启动', icon: 'i-x', cls: 'cell-candidate-failure', kind: 'failed', chip: 'chip-red', terminal: true, tag: '失败' },
    'evidence-failure': { label: '无法打开游玩', icon: 'i-alert-triangle', cls: 'cell-evidence-failure', kind: 'failed', chip: 'chip-red', terminal: true, tag: '失败' },
    'infrastructure-error': { label: '基础设施错误', icon: 'i-alert-octagon', cls: 'cell-infrastructure-error', kind: 'resumable', chip: 'chip-amber', resumable: true, tag: '设施' },
    interrupted: { label: '已中断', icon: 'i-pause-circle', cls: 'cell-interrupted', kind: 'resumable', chip: 'chip-amber', resumable: true, tag: '中断' },
  };
  const UNKNOWN_STATUS = { label: '未知状态', icon: 'i-info', cls: 'cell-pending', kind: 'pending', chip: 'chip-neutral', tag: '?' };

  const MATRIX_STATUS = {
    running: { label: '执行中', chip: 'chip-cyan' },
    incomplete: { label: '未完成（停在任务边界）', chip: 'chip-amber' },
    interrupted: { label: '已中断', chip: 'chip-amber' },
    complete: { label: '已完成 · 已封存', chip: 'chip-green' },
    invalidated: { label: '已作废', chip: 'chip-red' },
  };

  const RUNNER_STATUS = {
    idle: { label: '空闲', chip: 'chip-neutral' },
    running: { label: '运行中', chip: 'chip-cyan' },
    exited: { label: '已退出', chip: 'chip-neutral' },
  };

  const OPERATION_LABEL = {
    'matrix-prepare': '准备运行配置',
    'matrix-start': '启动 Matrix',
    'matrix-resume': '继续 Matrix',
    'matrix-retry': '重跑失败项',
  };

  const ACTION_LABEL = {
    prepare: '准备配置',
    start: '启动',
    pause: '暂停',
    interrupt: '中断',
    resume: '继续',
    retry: '重跑失败项',
    invalidate: '作废',
  };

  const PHASE_LABEL = {
    evaluating: '评估中',
    running: '执行中',
    building: '构建中',
  };

  // Display names for the three core coding harnesses probed by Harbor Smoke.
  const HARNESS_LABEL = {
    codex: 'Codex',
    'claude-code': 'Claude Code',
    pi: 'Pi',
  };
  const CORE_HARNESSES = 'Codex、Claude Code、Pi';

  const RUN_FILES = [
    { rel: 'manifest.json', kind: '候选清单' },
    { rel: 'events.jsonl', kind: '候选事件流' },
    { rel: 'stderr.log', kind: '候选标准错误' },
    { rel: 'final.txt', kind: '候选最终输出' },
    { rel: 'evaluation/report.json', kind: '评估报告' },
    { rel: 'evaluation/evaluator.stdout.log', kind: '评估器标准输出' },
    { rel: 'evaluation/evaluator.stderr.log', kind: '评估器标准错误' },
    { rel: 'evaluation/build.stdout.log', kind: '构建标准输出' },
    { rel: 'evaluation/build.stderr.log', kind: '构建标准错误' },
  ];

  // ------------------------------------------------------------------
  // Runtime state
  // ------------------------------------------------------------------

  const app = {
    state: null,
    lastUpdate: 0,
    source: null,
    pollTimer: null,
    busy: false,
    filter: 'all',
    selectedCell: null,
    lastFocus: null,
    matrixSignature: '',
    optionsSignature: '',
    combos: [],
    comboDiagnostics: null,
    selectedComboId: null,
    cellButtons: new Map(),
    pauseRequestedAt: null,
    lastRunnerKey: null,
    lastMatrixStatus: null,
    planCache: { path: null, data: null, loading: false },
    smokeCache: { path: null, data: null, loading: false },
    fileDialogPath: null,
  };

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const key of Object.keys(attrs)) {
        const value = attrs[key];
        if (value === null || value === undefined || value === false) continue;
        if (key === 'class') node.className = value;
        else if (key === 'text') node.textContent = value;
        else if (key === 'html') node.innerHTML = value;
        else node.setAttribute(key, value === true ? '' : String(value));
      }
    }
    if (children) {
      for (const child of [].concat(children)) {
        if (child === null || child === undefined) continue;
        node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
      }
    }
    return node;
  }

  function svgIcon(id, extraClass) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'icon' + (extraClass ? ' ' + extraClass : ''));
    svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', '#' + id);
    svg.appendChild(use);
    return svg;
  }

  function setText(id, text) {
    const node = $(id);
    if (!node) return;
    const next = text === null || text === undefined || text === '' ? '--' : String(text);
    if (node.textContent !== next) node.textContent = next;
  }

  function setChip(node, cls, text) {
    if (!node) return;
    const classes = ['chip', cls];
    if (node.className !== classes.join(' ')) node.className = classes.join(' ');
    if (node.textContent !== text) node.textContent = text;
  }

  function shortDigest(value) {
    if (typeof value !== 'string' || !value) return '--';
    return value.length > 16 ? value.slice(0, 8) + '…' + value.slice(-6) : value;
  }

  function baseName(path) {
    if (typeof path !== 'string' || !path) return '--';
    const parts = path.replace(/\/+$/, '').split('/');
    return parts[parts.length - 1] || path;
  }

  function parentName(path) {
    if (typeof path !== 'string' || !path) return '';
    const parts = path.replace(/\/+$/, '').split('/');
    return parts.length >= 2 ? parts[parts.length - 2] : '';
  }

  function pad2(n) { return n < 10 ? '0' + n : String(n); }

  function tsValue(iso) {
    if (!iso) return 0;
    const t = new Date(iso).getTime();
    return Number.isNaN(t) ? 0 : t;
  }

  function harnessLabel(value) {
    if (typeof value !== 'string' || !value) return '';
    return HARNESS_LABEL[value] || value;
  }

  function phaseLabel(value) {
    if (typeof value !== 'string' || !value) return '';
    return PHASE_LABEL[value] || value;
  }

  function fmtTime(iso) {
    if (!iso) return '--';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
  }

  function fmtClock(iso) {
    if (!iso) return '--:--:--';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '--:--:--';
    return `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}:${pad2(d.getUTCSeconds())}Z`;
  }

  function fmtDuration(startIso, endIso) {
    if (!startIso) return '--';
    const start = new Date(startIso).getTime();
    const end = endIso ? new Date(endIso).getTime() : Date.now();
    if (Number.isNaN(start) || Number.isNaN(end)) return '--';
    let seconds = Math.max(0, Math.round((end - start) / 1000));
    const h = Math.floor(seconds / 3600); seconds -= h * 3600;
    const m = Math.floor(seconds / 60); seconds -= m * 60;
    if (h > 0) return `${h}h ${pad2(m)}m ${pad2(seconds)}s`;
    if (m > 0) return `${m}m ${pad2(seconds)}s`;
    return `${seconds}s`;
  }

  function fmtAge(ms) {
    if (ms < 0 || !Number.isFinite(ms)) return '--';
    const s = Math.round(ms / 1000);
    if (s < 60) return s + 's';
    const m = Math.floor(s / 60);
    if (m < 60) return m + 'm';
    return Math.floor(m / 60) + 'h';
  }

  function pathButton(path, label) {
    if (typeof path !== 'string' || !path) return document.createTextNode('--');
    const btn = el('button', {
      type: 'button',
      class: 'path-btn mono',
      title: '查看 ' + path,
      'aria-label': '查看文件 ' + path,
    }, [svgIcon('i-file-text'), label || path]);
    btn.addEventListener('click', () => openFile(path));
    return btn;
  }

  function replaceChildren(node, children) {
    while (node.firstChild) node.removeChild(node.firstChild);
    for (const child of [].concat(children)) {
      if (child === null || child === undefined) continue;
      node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
    }
  }

  // ------------------------------------------------------------------
  // Notices & activity log
  // ------------------------------------------------------------------

  let noticeTimer = null;
  function notify(kind, text, sticky) {
    const box = $('notice');
    const icon = { ok: 'i-check', warn: 'i-alert-triangle', error: 'i-octagon-x', info: 'i-info' }[kind] || 'i-info';
    box.className = 'notice notice-' + kind;
    $('notice-icon').setAttribute('href', '#' + icon);
    $('notice-text').textContent = text;
    box.hidden = false;
    if (noticeTimer) clearTimeout(noticeTimer);
    if (!sticky) noticeTimer = setTimeout(() => { box.hidden = true; }, 8000);
  }

  function logActivity(kind, text) {
    const list = $('activity');
    const now = new Date();
    const item = el('li', null, [
      el('time', { datetime: now.toISOString(), text: `${pad2(now.getHours())}:${pad2(now.getMinutes())}:${pad2(now.getSeconds())}` }),
      el('span', { class: 'act-' + kind, text }),
    ]);
    list.insertBefore(item, list.firstChild);
    while (list.children.length > 60) list.removeChild(list.lastChild);
  }

  // ------------------------------------------------------------------
  // Networking (localhost API only)
  // ------------------------------------------------------------------

  async function fetchState() {
    const response = await fetch('/api/state', { cache: 'no-store' });
    if (!response.ok) throw new Error(`GET /api/state 返回 ${response.status}`);
    const state = await response.json();
    applyState(state);
    return state;
  }

  async function postAction(action, body) {
    const response = await fetch('/api/actions/' + action, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Web3D-Control-Token': TOKEN,
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    let payload = null;
    try { payload = await response.json(); } catch (_) { payload = null; }
    if (!response.ok) {
      const detail = payload && payload.detail ? (typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail)) : `HTTP ${response.status}`;
      throw new Error(detail);
    }
    return payload || {};
  }

  function connectEvents() {
    if (app.source) { try { app.source.close(); } catch (_) { /* ignore */ } }
    setConnection('connecting', '连接中');
    let source;
    try {
      source = new EventSource('/api/events');
    } catch (_) {
      startPolling();
      return;
    }
    app.source = source;
    source.addEventListener('state', (event) => {
      try {
        applyState(JSON.parse(event.data));
        setConnection('live', '实时');
        stopPolling();
      } catch (error) {
        setConnection('lost', '数据异常');
      }
    });
    source.addEventListener('open', () => setConnection('live', '实时'));
    source.addEventListener('error', () => {
      setConnection('lost', '重连中');
      startPolling();
    });
  }

  function startPolling() {
    if (app.pollTimer) return;
    app.pollTimer = setInterval(() => {
      fetchState().then(() => {
        if (!app.source || app.source.readyState !== 1) setConnection('connecting', '轮询');
      }).catch(() => setConnection('lost', '离线'));
    }, 3000);
  }

  function stopPolling() {
    if (app.pollTimer) { clearInterval(app.pollTimer); app.pollTimer = null; }
  }

  function setConnection(state, label) {
    const node = $('conn-indicator');
    const cls = 'conn conn-' + state;
    if (node.className !== cls) node.className = cls;
    setText('conn-label', label);
  }

  // ------------------------------------------------------------------
  // Derived data
  // ------------------------------------------------------------------

  function statusMeta(status) { return CELL_STATUS[status] || UNKNOWN_STATUS; }

  function derive(state) {
    const receipt = state.receipt || null;
    const planData = app.planCache.data;
    const preview = !state.canonical
      && state.controls && state.controls.can_start === true
      && planData && Array.isArray(planData.cells);
    const cells = preview
      ? planData.cells.map((cell) => ({
        ...cell,
        status: 'pending',
        run: null,
        passed: false,
        trusted: false,
      }))
      : (receipt && Array.isArray(receipt.cells) ? receipt.cells : []);
    const tasks = [];
    const profiles = [];
    const grid = new Map();
    const counts = { total: cells.length, pending: 0, running: 0, completed: 0, candidate: 0, evidence: 0, infra: 0, interrupted: 0, trusted: 0, playable: 0, warning: 0, evaluating: 0 };
    const taskState = new Map();

    for (const cell of cells) {
      if (!tasks.includes(cell.task)) tasks.push(cell.task);
      if (!profiles.includes(cell.profile)) profiles.push(cell.profile);
      const key = cell.task + ':' + cell.profile;
      if (!grid.has(key)) grid.set(key, []);
      grid.get(key).push(cell);
      switch (cell.status) {
        case 'pending': counts.pending++; break;
        case 'running': counts.running++; if (cell.phase === 'evaluating') counts.evaluating++; break;
        case 'completed': counts.completed++; break;
        case 'candidate-failure': counts.candidate++; break;
        case 'evidence-failure': counts.evidence++; break;
        case 'infrastructure-error': counts.infra++; break;
        case 'interrupted': counts.interrupted++; break;
        default: break;
      }
      if (cell.trusted === true) counts.trusted++;
      if (cell.playable === true) counts.playable++;
      if (Array.isArray(cell.admission_warnings) && cell.admission_warnings.length) counts.warning++;
      const ts = taskState.get(cell.task) || { total: 0, terminal: 0, running: 0 };
      ts.total++;
      if (cell.status === 'running') ts.running++;
      if (statusMeta(cell.status).terminal || cell.status === 'completed') ts.terminal++;
      taskState.set(cell.task, ts);
    }

    const runningCells = cells.filter((c) => c.status === 'running');
    const runningTasks = Array.from(new Set(runningCells.map((c) => c.task)));
    const runner = state.runner || { status: 'idle' };
    const active = runner.active === true;
    const canonical = state.canonical || null;

    let currentTask = runningTasks.length ? runningTasks.join(', ') : null;
    if (!currentTask && active) {
      const next = tasks.find((t) => (grid.size && cells.some((c) => c.task === t && (c.status === 'pending' || statusMeta(c.status).resumable))));
      currentTask = next ? next + '（准备中）' : null;
    }

    let phase;
    if (active) {
      if (counts.evaluating > 0 && counts.running === counts.evaluating) phase = '评估中';
      else if (counts.evaluating > 0) phase = '候选执行中 + 评估中';
      else if (counts.running > 0) phase = '候选执行中';
      else phase = '执行进程启动中 / 校验冻结输入';
      if (app.pauseRequestedAt) phase += ' · 已请求暂停，将在下一个任务边界停止';
    } else if (preview) {
      phase = '待启动（Plan 预览）';
    } else if (!receipt) {
      phase = canonical ? '正式回执不可读' : '未启动';
    } else {
      switch (receipt.status) {
        case 'complete': phase = 'Matrix 已完成'; break;
        case 'incomplete': phase = '已在任务边界停止，等待继续'; break;
        case 'interrupted': phase = '已中断，等待继续'; break;
        case 'invalidated': phase = '回执已作废'; break;
        case 'running': phase = '执行进程未运行（回执仍标记为执行中，可继续）'; break;
        default: phase = receipt.status || '--';
      }
    }

    return {
      receipt, cells, tasks, profiles, grid, counts, runner, active, canonical, currentTask, phase, taskState, runningTasks, preview,
    };
  }

  // ------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------

  function applyState(state) {
    app.state = state;
    app.lastUpdate = Date.now();
    const d = derive(state);
    trackTransitions(d);
    renderTop(state);
    renderStartPanel(state, d);
    renderControls(state, d);
    renderOverview(state, d);
    renderMatrix(d);
    renderProvenance(state, d);
    renderRunner(state, d);
    if (app.selectedCell) {
      const cell = d.cells.find((c) => c.cell_id === app.selectedCell);
      if (cell) renderDrawer(cell, d); else closeDrawer();
    }
  }

  function trackTransitions(d) {
    const runnerKey = `${d.runner.status}|${d.runner.pid || ''}|${d.runner.returncode === undefined ? '' : d.runner.returncode}`;
    if (app.lastRunnerKey !== null && runnerKey !== app.lastRunnerKey) {
      if (d.runner.status === 'exited') {
        const code = d.runner.returncode;
        const label = OPERATION_LABEL[d.runner.operation] || d.runner.operation || '执行';
        logActivity(code === 0 ? 'ok' : 'warn', `${label} 进程已退出${code === null || code === undefined ? '' : `（退出码 ${code}）`}${d.runner.exit_reason ? '：' + d.runner.exit_reason : ''}`);
        app.pauseRequestedAt = null;
      } else if (d.runner.status === 'running') {
        logActivity('info', `${OPERATION_LABEL[d.runner.operation] || d.runner.operation || '执行'} 进程已启动（进程号 ${d.runner.pid}）`);
      }
    }
    app.lastRunnerKey = runnerKey;
    if (!d.active) app.pauseRequestedAt = null;

    const matrixStatus = d.receipt ? d.receipt.status : null;
    if (app.lastMatrixStatus !== null && matrixStatus !== app.lastMatrixStatus && matrixStatus) {
      const meta = MATRIX_STATUS[matrixStatus];
      logActivity('info', `Matrix 回执状态变为「${meta ? meta.label : matrixStatus}」`);
    }
    app.lastMatrixStatus = matrixStatus;

  }

  function renderTop(state) {
    setText('server-time', fmtClock(state.server_time));
  }

  function renderControls(state, d) {
    const controls = state.controls || {};
    const buttons = {
      prepare: $('btn-prepare'),
      start: $('btn-start'),
      pause: $('btn-pause'),
      interrupt: $('btn-interrupt'),
      resume: $('btn-resume'),
      retry: $('btn-retry'),
      invalidate: $('btn-invalidate'),
    };
    const hasCombo = app.combos.length > 0;
    buttons.prepare.disabled = app.busy || controls.can_prepare !== true;
    buttons.start.disabled = app.busy || controls.can_start !== true || !hasCombo;
    buttons.pause.disabled = app.busy || controls.can_pause !== true;
    buttons.interrupt.disabled = app.busy || controls.can_interrupt !== true;
    buttons.resume.disabled = app.busy || controls.can_resume !== true;
    buttons.retry.disabled = app.busy || controls.can_retry !== true;
    buttons.invalidate.disabled = app.busy || controls.can_invalidate !== true;

    const runnerMeta = RUNNER_STATUS[d.runner.status] || { label: d.runner.status || '--', chip: 'chip-neutral' };
    let runnerLabel = '执行进程' + runnerMeta.label;
    let runnerChip = runnerMeta.chip;
    if (d.runner.status === 'running' && !d.active) { runnerLabel = '执行进程丢失'; runnerChip = 'chip-red'; }
    if (d.active && d.runner.operation) runnerLabel += ' · ' + (OPERATION_LABEL[d.runner.operation] || d.runner.operation);
    setChip($('runner-chip'), runnerChip, runnerLabel);

    let hint;
    const receiptStatus = d.receipt ? d.receipt.status : null;
    if (d.active) {
      hint = d.runner.operation === 'matrix-prepare'
        ? '正在生成冻结 Plan 并执行 Harbor Smoke；完成后会自动出现在启动前配置中，也可立即中断。'
        : controls.can_pause
        ? 'Matrix 正在执行。「暂停」会在下一个任务边界优雅停止；「中断」会立即向执行进程组发送中断信号。'
        : '执行进程正在运行，当前回执状态不接受暂停，仅可立即中断。';
      if (app.pauseRequestedAt) hint = `已于 ${fmtTime(app.pauseRequestedAt)} 请求暂停，执行进程将在当前任务完成后停止。仍可立即中断。`;
    } else if (!d.canonical) {
      if (controls.can_start !== true) hint = '服务端当前不允许启动 Matrix。';
      else if (!hasCombo) hint = '启动前配置尚未就绪：需要一份冻结配置 Plan，以及与之匹配且已通过的 Harbor Smoke 连通性检查。';
      else if (app.combos.length === 1) hint = '运行配置已自动选定并就绪，点击「启动」创建本季的正式 Matrix。';
      else hint = '在「启动前配置」中选择一套运行配置，然后点击「启动」创建本季的正式 Matrix。';
    } else if (controls.can_resume) {
      const retryHint = controls.can_retry
        ? `当前有 ${controls.retryable_cells || 0} 个失败单元格；额度恢复后可点「重跑失败项」重新排队。`
        : '';
      hint = `正式 Matrix 处于「${(MATRIX_STATUS[receiptStatus] || { label: receiptStatus }).label}」，可通过「继续」恢复。${retryHint}`;
    } else if (receiptStatus === 'complete') {
      hint = '正式 Matrix 已完成并封存，没有可执行的操作。';
    } else if (receiptStatus === 'invalidated') {
      hint = '正式回执已作废，控制面不提供进一步操作。';
    } else if (!d.receipt) {
      hint = '正式记录存在，但回执无法加载或校验失败，请人工检查。';
    } else {
      hint = '当前没有可用操作。';
    }
    setText('controls-hint', hint);
  }

  // ------------------------------------------------------------------
  // Start panel: one combined "运行配置" (Plan + newest matching passed
  // Harbor Smoke) instead of two raw file selectors.
  // ------------------------------------------------------------------

  function isUsableSmoke(smoke) {
    return !!smoke && smoke.status === 'passed' && (smoke.backend || 'harbor') === 'harbor' && !!smoke.plan_digest;
  }

  function buildCombos(options) {
    const plans = Array.isArray(options.plans) ? options.plans : [];
    const smokes = Array.isArray(options.smokes) ? options.smokes : [];
    const combos = [];
    const diagnostics = {
      plans: plans.length,
      smokes: smokes.length,
      plansWithoutSmoke: [],
      matchedButFailed: 0,
      matchedWrongBackend: 0,
      orphanSmokes: 0,
    };
    const planDigests = new Set(plans.map((p) => p.digest).filter(Boolean));
    for (const smoke of smokes) {
      if (!smoke.plan_digest || !planDigests.has(smoke.plan_digest)) { diagnostics.orphanSmokes++; continue; }
      if (smoke.status !== 'passed') diagnostics.matchedButFailed++;
      else if ((smoke.backend || 'harbor') !== 'harbor') diagnostics.matchedWrongBackend++;
    }
    for (const plan of plans) {
      if (!plan || !plan.path) continue;
      const matches = smokes
        .filter((s) => isUsableSmoke(s) && s.plan_digest === plan.digest)
        .sort((a, b) => tsValue(b.completed_at) - tsValue(a.completed_at));
      if (!matches.length) { diagnostics.plansWithoutSmoke.push(plan); continue; }
      combos.push({ id: plan.path + '\n' + matches[0].path, plan, smoke: matches[0], alternatives: matches.length - 1 });
    }
    // Newest Plan first (server already orders by modification time, keep it stable).
    combos.sort((a, b) => tsValue(b.plan.modified_at) - tsValue(a.plan.modified_at));
    return { combos, diagnostics };
  }

  function comboLabel(combo) {
    const season = combo.plan.season || '未知赛季';
    return `${season} · Plan 生成于 ${fmtTime(combo.plan.modified_at)} · Smoke 通过于 ${fmtTime(combo.smoke.completed_at)}`;
  }

  function selectedCombo() {
    if (!app.combos.length) return null;
    return app.combos.find((c) => c.id === app.selectedComboId) || app.combos[0];
  }

  function selectedPlan() {
    const combo = selectedCombo();
    return combo ? combo.plan : null;
  }

  function selectedSmoke() {
    const combo = selectedCombo();
    return combo ? combo.smoke : null;
  }

  function renderStartPanel(state, d) {
    const panel = $('start-panel');
    const controls = state.controls || {};
    const show = controls.can_start === true;
    if (panel.hidden === show) panel.hidden = !show;

    const options = state.options || { plans: [], smokes: [] };
    const plans = Array.isArray(options.plans) ? options.plans : [];
    const smokes = Array.isArray(options.smokes) ? options.smokes : [];
    const signature = plans.map((p) => p.path + '|' + p.digest + '|' + p.modified_at).join(';')
      + '##' + smokes.map((s) => s.path + '|' + s.status + '|' + s.backend + '|' + s.plan_digest + '|' + s.completed_at).join(';');
    if (signature !== app.optionsSignature) {
      app.optionsSignature = signature;
      const built = buildCombos(options);
      app.combos = built.combos;
      app.comboDiagnostics = built.diagnostics;
      const select = $('sel-config');
      const labels = app.combos.map(comboLabel);
      // Guard against identical labels (same second) by numbering duplicates.
      const seen = new Map();
      const optionNodes = app.combos.map((combo, index) => {
        let text = labels[index];
        const count = (seen.get(text) || 0) + 1;
        seen.set(text, count);
        if (count > 1) text += `（第 ${count} 份）`;
        return el('option', { value: combo.id, text });
      });
      replaceChildren(select, optionNodes.length ? optionNodes : [el('option', { value: '', text: '（没有可用的运行配置）' })]);
      const keep = app.combos.some((c) => c.id === app.selectedComboId);
      app.selectedComboId = keep ? app.selectedComboId : (app.combos[0] ? app.combos[0].id : null);
      if (app.selectedComboId) select.value = app.selectedComboId;
      select.disabled = !app.combos.length;
    }
    if (!show) return;
    renderStartReadiness();
  }

  function setReadiness(tone, icon, title, text) {
    const box = $('start-readiness');
    const cls = 'readiness readiness-' + tone;
    if (box.className !== cls) box.className = cls;
    const use = $('start-readiness-icon');
    if (use.getAttribute('href') !== '#' + icon) use.setAttribute('href', '#' + icon);
    setText('start-readiness-title', title);
    const textNode = $('start-readiness-text');
    if (textNode.textContent !== text) textNode.textContent = text;
    textNode.hidden = !text;
  }

  function kvItems(pairs) {
    const items = [];
    for (const [key, value, mono] of pairs) {
      items.push(el('dt', { text: key }));
      const dd = el('dd', { class: mono ? 'mono' : null });
      replaceChildren(dd, value === null || value === undefined || value === '' ? '--' : value);
      items.push(dd);
    }
    return items;
  }

  function renderStartReadiness() {
    const combos = app.combos;
    const diag = app.comboDiagnostics || { plans: 0, smokes: 0, plansWithoutSmoke: [], matchedButFailed: 0, matchedWrongBackend: 0, orphanSmokes: 0 };
    const combo = selectedCombo();
    const field = $('start-config-field');
    const multi = combos.length > 1;
    if (field.hidden === multi) field.hidden = !multi;

    const facts = $('start-facts');
    const details = $('start-details-kv');
    const warningBox = $('start-warning');

    if (!combo) {
      // Nothing usable: explain in status language what is missing.
      let text;
      if (diag.plans === 0) {
        text = '未找到冻结配置（Plan）。请先为本季生成冻结配置，再运行 Harbor Smoke 连通性检查。';
      } else if (diag.smokes === 0) {
        text = `已找到 ${diag.plans} 份冻结配置，但没有任何 Harbor Smoke 记录。请先对当前 Plan 运行 Harbor 连通性检查（${CORE_HARNESSES}）。`;
      } else {
        const reasons = [];
        if (diag.matchedButFailed) reasons.push(`${diag.matchedButFailed} 份与 Plan 匹配的检查未通过`);
        if (diag.matchedWrongBackend) reasons.push(`${diag.matchedWrongBackend} 份匹配的检查不是在 Harbor 环境完成的`);
        if (diag.orphanSmokes) reasons.push(`${diag.orphanSmokes} 份检查对应的 Plan 已不存在或内容已变更`);
        text = `已找到 ${diag.plans} 份冻结配置与 ${diag.smokes} 份 Smoke 记录，但没有一份已通过的 Harbor Smoke 与现有 Plan 匹配`
          + (reasons.length ? `：${reasons.join('；')}。` : '。')
          + `请对最新的 Plan 重新运行 Harbor 连通性检查（${CORE_HARNESSES}）。`;
      }
      setReadiness('amber', 'i-alert-triangle', '尚未就绪，无法启动', text);
      if (facts.dataset.rendered !== 'none') {
        replaceChildren(facts, kvItems([
          ['冻结配置', diag.plans ? `${diag.plans} 份，均缺少匹配且通过的连通性检查` : '未找到'],
          ['连通性检查', diag.smokes ? `${diag.smokes} 份记录，均不可用` : '未找到'],
          ['执行环境', 'Harbor'],
        ]));
        facts.dataset.rendered = 'none';
      }
      const plans = (app.state && app.state.options && app.state.options.plans) || [];
      const smokes = (app.state && app.state.options && app.state.options.smokes) || [];
      const key = 'none|' + app.optionsSignature;
      if (details.dataset.rendered !== key) {
        const pairs = [];
        plans.forEach((p, i) => pairs.push([`Plan ${i + 1}`, el('span', null, [pathButton(p.path, p.name), ` · ${p.season || '未知赛季'} · 摘要 ${shortDigest(p.digest)} · ${p.modified_at || '--'}`]), true]));
        smokes.forEach((s, i) => pairs.push([`Smoke ${i + 1}`, el('span', null, [pathButton(s.path, s.name), ` · ${s.status || '?'} · ${s.backend || 'harbor'} · 对应 Plan 摘要 ${shortDigest(s.plan_digest)} · ${s.completed_at || '--'}`]), true]));
        if (!pairs.length) pairs.push(['扫描目录', 'runs/plans 与 runs/smoke 下没有可读取的文件', true]);
        replaceChildren(details, kvItems(pairs));
        details.dataset.rendered = key;
      }
      warningBox.hidden = true;
      return;
    }

    const plan = combo.plan;
    const smoke = combo.smoke;
    const season = plan.season || '未知赛季';

    if (multi) {
      setReadiness('green', 'i-check-circle', '已就绪，请选择运行配置',
        `找到 ${combos.length} 套可用的运行配置。每套均由本地冻结配置生成，并已通过 Harbor 的 ${CORE_HARNESSES} 连通性检查；每个 Plan 已自动匹配最新的通过记录。`);
    } else {
      setReadiness('green', 'i-check-circle', '已就绪，可以启动',
        `已自动选用唯一可用的运行配置：Plan 由本地冻结配置生成，Harbor 已完成 ${CORE_HARNESSES} 连通性检查并全部通过。`);
    }

    if (multi) {
      setText('config-meta', combo.alternatives > 0
        ? `已自动选用该 Plan 最新的通过记录（另有 ${combo.alternatives} 份较早的记录未列出）。`
        : '该 Plan 只有这一份已通过的连通性检查。');
    }

    const factsKey = combo.id + '|' + combo.alternatives;
    if (facts.dataset.rendered !== factsKey) {
      let smokeText = `Harbor 已完成 ${CORE_HARNESSES} 连通性检查，全部通过 · ${fmtTime(smoke.completed_at)}`;
      if (!multi && combo.alternatives > 0) smokeText += `（自动选用最新一次，另有 ${combo.alternatives} 份较早的通过记录）`;
      replaceChildren(facts, kvItems([
        ['赛季', season],
        ['运行规模', `${plan.task_count || '?'} 个任务 × ${plan.profile_count || '?'} 个模型配置，共 ${plan.cell_count || '?'} 个单元格`],
        ['时间上限', `每个单元格 ${plan.timeout_minutes || '?'} 分钟`],
        ['冻结配置', `由本地冻结配置生成 · ${fmtTime(plan.modified_at)}`],
        ['连通性检查', smokeText],
        ['执行环境', 'Harbor'],
      ]));
      facts.dataset.rendered = factsKey;
    }

    if (details.dataset.rendered !== combo.id) {
      replaceChildren(details, kvItems([
        ['Plan 文件', pathButton(plan.path, plan.path), true],
        ['Plan 编号', plan.plan_id, true],
        ['Plan 摘要', plan.digest, true],
        ['Plan 修改时间', plan.modified_at, true],
        ['Smoke 回执', pathButton(smoke.path, smoke.path), true],
        ['Smoke 编号', smoke.smoke_id, true],
        ['Smoke 完成时间', smoke.completed_at, true],
        ['Smoke 对应 Plan 摘要', smoke.plan_digest, true],
        ['执行环境', smoke.backend || 'harbor', true],
      ]));
      details.dataset.rendered = combo.id;
    }

    warningBox.hidden = true;
  }

  function renderOverview(state, d) {
    const receipt = d.receipt;
    const canonical = d.canonical;
    const previewPlan = d.preview ? app.planCache.data : null;
    const previewOption = d.preview ? selectedPlan() : null;
    const previewSmoke = d.preview ? selectedSmoke() : null;
    const receiptMatches = !!(receipt && canonical && receipt.matrix_id === canonical.matrix_id);

    let chipCls = 'chip-neutral';
    let chipText = '无正式 Matrix';
    if (canonical && receiptMatches) {
      const meta = MATRIX_STATUS[receipt.status] || { label: receipt.status, chip: 'chip-neutral' };
      chipCls = meta.chip; chipText = '正式 · ' + meta.label;
    } else if (canonical) {
      chipCls = 'chip-red'; chipText = '正式回执不可读';
    } else if (d.preview) {
      chipCls = 'chip-neutral'; chipText = '待启动 · Plan 预览';
    } else if (receipt) {
      const meta = MATRIX_STATUS[receipt.status] || { label: receipt.status, chip: 'chip-neutral' };
      chipCls = receipt.status === 'invalidated' ? 'chip-red' : 'chip-amber';
      chipText = '历史回执 · ' + meta.label;
    }
    setChip($('matrix-chip'), chipCls, chipText);

    const banner = $('canonical-banner');
    let bannerCls = null; let bannerIcon = 'i-info'; let bannerText = '';
    if (d.preview) {
      bannerCls = 'banner-cyan'; bannerIcon = 'i-info';
      bannerText = receipt && receipt.status === 'invalidated'
        ? '当前显示的是新运行配置的待启动预览，尚未创建正式 Matrix。上一份正式 Matrix 已作废，审计记录仍然保留。'
        : '当前显示的是新运行配置的待启动预览，尚未创建正式 Matrix。';
    } else if (canonical && !receipt) {
      bannerCls = 'banner-red'; bannerIcon = 'i-alert-octagon';
      bannerText = `正式记录指向 ${canonical.receipt || '（未知路径）'}，但该回执无法加载或摘要校验失败。请人工检查后再操作。`;
    } else if (canonical && !receiptMatches) {
      bannerCls = 'banner-red'; bannerIcon = 'i-alert-octagon';
      bannerText = `正式记录（${canonical.matrix_id}）指向的回执无法加载；下方显示的是另一份历史回执 ${receipt.matrix_id || ''}，仅供参考。`;
    } else if (!canonical && receipt) {
      bannerCls = receipt.status === 'invalidated' ? 'banner-red' : 'banner-amber';
      bannerIcon = 'i-alert-triangle';
      bannerText = receipt.status === 'invalidated'
          ? `下方显示的历史回执（${receipt.matrix_id || ''}）已被作废，不是正式 Matrix；本季尚无正式声明。`
          : `下方显示的是历史回执（${receipt.matrix_id || ''}），不是正式 Matrix；本季尚无正式声明。`;
    } else if (receiptMatches && receipt.status === 'invalidated') {
      bannerCls = 'banner-red'; bannerIcon = 'i-alert-octagon';
      bannerText = '正式回执已被作废。';
    } else if (receiptMatches && receipt.status === 'complete') {
      bannerCls = 'banner-green'; bannerIcon = 'i-lock';
      bannerText = `正式 Matrix 已完成并封存（${fmtTime(receipt.completed_at)}）。`;
    }
    if (bannerCls) {
      banner.className = 'banner ' + bannerCls;
      $('canonical-banner-icon').setAttribute('href', '#' + bannerIcon);
      setText('canonical-banner-text', bannerText);
      banner.hidden = false;
    } else {
      banner.hidden = true;
    }

    const c = d.counts;
    const has = c.total > 0;
    setText('st-total', has ? c.total : '--');
    setText('st-trusted', has ? c.playable : '--');
    setText('st-running', has ? c.running : '--');
    setText('st-pending', has ? c.pending : '--');
    setText('st-cand', has ? c.candidate : '--');
    setText('st-evid', has ? c.evidence : '--');
    setText('st-infra', has ? c.infra : '--');
    setText('st-int', has ? c.interrupted : '--');

    const pct = (n) => (has ? (100 * n / c.total).toFixed(2) + '%' : '0%');
    $('pg-green').style.width = pct(c.completed);
    $('pg-red').style.width = pct(c.candidate + c.evidence);
    $('pg-amber').style.width = pct(c.infra + c.interrupted);
    $('pg-cyan').style.width = pct(c.running);

    setText('kv-phase', d.phase);
    setText('kv-task', d.preview ? '--' : (d.currentTask || (receipt && receipt.execution_window && receipt.execution_window.stopped_at_task_barrier ? `停在任务边界：${receipt.execution_window.stopped_at_task_barrier}` : '--')));
    const statusNode = $('kv-status');
    if (d.preview) {
      const wanted = 'chip-neutral|待启动';
      if (statusNode.dataset.rendered !== wanted) {
        replaceChildren(statusNode, el('span', { class: 'chip chip-neutral', text: '待启动' }));
        statusNode.dataset.rendered = wanted;
      }
    } else if (receipt) {
      const meta = MATRIX_STATUS[receipt.status] || { label: receipt.status || '--', chip: 'chip-neutral' };
      const wanted = `${meta.chip}|${meta.label}`;
      if (statusNode.dataset.rendered !== wanted) {
        replaceChildren(statusNode, el('span', { class: 'chip ' + meta.chip, text: meta.label }));
        statusNode.dataset.rendered = wanted;
      }
    } else if (statusNode.dataset.rendered !== '--') {
      replaceChildren(statusNode, '--');
      statusNode.dataset.rendered = '--';
    }
    const previewSeason = previewPlan && previewPlan.season ? previewPlan.season.id : (previewOption ? previewOption.season : null);
    setText('kv-matrix-id', d.preview ? '启动时创建' : (receipt ? receipt.matrix_id : (canonical ? canonical.matrix_id : '--')));
    setText('kv-season', d.preview ? (previewSeason || '--') : (receipt ? receipt.season : (canonical ? canonical.season : '--')));
    setText('kv-times-label', d.preview ? '配置时间' : '创建 / 更新');
    setText('kv-times', d.preview
      ? `Plan ${fmtTime((previewPlan && previewPlan.created_at) || (previewOption && previewOption.modified_at))} · Smoke ${fmtTime(previewSmoke && previewSmoke.completed_at)}`
      : (receipt ? `${fmtTime(receipt.created_at)} / ${fmtTime(receipt.updated_at)}` : '--'));
    setText('kv-window-label', '执行窗口');

    let windowText = d.preview ? '尚未开始' : '--';
    if (!d.preview && receipt && receipt.execution_window && typeof receipt.execution_window === 'object') {
      const w = receipt.execution_window;
      const parts = [];
      if (w.stop_after_task) parts.push(`在任务 ${w.stop_after_task} 之后停止`);
      if (w.pause_requested_at) parts.push(`暂停请求于 ${fmtTime(w.pause_requested_at)}`);
      if (w.stopped_at_task_barrier) parts.push(`已停在任务边界 ${w.stopped_at_task_barrier}`);
      if (w.stopped_at) parts.push(`停止于 ${fmtTime(w.stopped_at)}`);
      windowText = parts.length ? parts.join(' · ') : '（无约束）';
    } else if (!d.preview && receipt) {
      windowText = '（无约束，完整执行）';
    }
    setText('kv-window', windowText);
  }

  function renderMatrix(d) {
    const scroll = $('matrix-scroll');
    const head = $('matrix-head');
    const body = $('matrix-body');
    const hasCells = d.cells.length > 0;
    scroll.classList.toggle('is-empty', !hasCells);
    setText('matrix-dims', hasCells ? `${d.tasks.length} 个任务 × ${d.profiles.length} 个模型配置 · ${d.cells.length} 个单元格` : '任务 × 模型配置');
    if (!hasCells) {
      if (app.matrixSignature !== '') {
        replaceChildren(head, []);
        replaceChildren(body, []);
        app.cellButtons.clear();
        app.matrixSignature = '';
      }
      return;
    }

    const signature = d.cells.map((c) => c.cell_id).join('|');
    if (signature !== app.matrixSignature) {
      app.matrixSignature = signature;
      app.cellButtons.clear();
      const planData = app.planCache.data;
      const profileInfo = planData && planData.profiles && typeof planData.profiles === 'object' ? planData.profiles : {};

      const headRow = el('tr', null, [el('th', { class: 'corner', scope: 'col', text: '任务 \\ 模型配置' })]);
      for (const profile of d.profiles) {
        const info = profileInfo[profile] || {};
        const title = [profile, info.harness ? '执行框架：' + harnessLabel(info.harness) : null, info.model ? '模型：' + info.model : null, info.effort ? '推理强度：' + info.effort : null].filter(Boolean).join('\n');
        headRow.appendChild(el('th', { scope: 'col', title }, [
          el('div', { class: 'col-head' }, [
            el('span', { class: 'col-main', text: profile }),
            el('span', { class: 'col-sub', text: harnessLabel(info.harness || (profile.split('-')[0] || '')) }),
          ]),
        ]));
      }
      replaceChildren(head, headRow);

      const rows = [];
      for (const task of d.tasks) {
        const row = el('tr', null);
        const th = el('th', { scope: 'row', title: task }, [
          el('span', { class: 'task-state', 'aria-hidden': 'true' }),
          document.createTextNode(task),
        ]);
        row.appendChild(th);
        for (const profile of d.profiles) {
          const cells = d.grid.get(task + ':' + profile) || [];
          const wrap = el('div', { class: 'cell-wrap' });
          for (const cell of cells) {
            const btn = el('button', { type: 'button', class: 'cell', 'data-cell': cell.cell_id }, [
              svgIcon('i-circle'),
              el('span', { class: 'cell-tag', text: '' }),
            ]);
            btn.addEventListener('click', () => openDrawer(cell.cell_id, btn));
            app.cellButtons.set(cell.cell_id, btn);
            wrap.appendChild(btn);
          }
          row.appendChild(el('td', null, wrap));
        }
        rows.push(row);
      }
      replaceChildren(body, rows);
    }

    // Patch cell tiles in place (no structural change → no layout shift).
    const attemptsMatter = d.cells.some((c) => c.attempt && c.attempt > 1);
    for (const cell of d.cells) {
      const btn = app.cellButtons.get(cell.cell_id);
      if (!btn) continue;
      const meta = statusMeta(cell.status);
      let tag = meta.tag;
      if (cell.status === 'running' && cell.phase === 'evaluating') tag = '评估';
      else if (cell.status === 'pending') tag = attemptsMatter ? '#' + (cell.attempt || 1) : '·';
      const dimmed = !matchesFilter(cell, app.filter);
      const cls = ['cell', meta.cls, dimmed ? 'is-dimmed' : null, app.selectedCell === cell.cell_id ? 'is-selected' : null].filter(Boolean).join(' ');
      if (btn.className !== cls) btn.className = cls;
      const iconId = cell.status === 'running' && cell.phase === 'evaluating' ? 'i-scan' : meta.icon;
      const use = btn.querySelector('use');
      if (use.getAttribute('href') !== '#' + iconId) use.setAttribute('href', '#' + iconId);
      const svg = btn.querySelector('svg');
      svg.classList.toggle('icon-spin', !!meta.spin && cell.phase !== 'evaluating');
      const tagNode = btn.querySelector('.cell-tag');
      if (tagNode.textContent !== tag) tagNode.textContent = tag;
      const label = `${cell.task} × ${cell.profile}${attemptsMatter ? ' · 第 ' + (cell.attempt || 1) + ' 次尝试' : ''}：${meta.label}${cell.phase ? '（' + phaseLabel(cell.phase) + '）' : ''}${meta.terminal ? '（终态）' : ''}`;
      if (btn.getAttribute('aria-label') !== label) { btn.setAttribute('aria-label', label); btn.title = label; }
      btn.tabIndex = dimmed ? -1 : 0;
    }

    // Row markers
    const rows = body.querySelectorAll('tr');
    d.tasks.forEach((task, index) => {
      const marker = rows[index] && rows[index].querySelector('.task-state');
      if (!marker) return;
      const ts = d.taskState.get(task) || { total: 0, terminal: 0, running: 0 };
      const barrier = d.receipt && d.receipt.execution_window && d.receipt.execution_window.stopped_at_task_barrier === task;
      const cls = ['task-state', ts.running > 0 ? 'is-active' : null, ts.running === 0 && ts.total > 0 && ts.terminal === ts.total ? 'is-done' : null, barrier ? 'is-barrier' : null].filter(Boolean).join(' ');
      if (marker.className !== cls) marker.className = cls;
    });
  }

  function matchesFilter(cell, filter) {
    if (filter === 'all') return true;
    const meta = statusMeta(cell.status);
    return meta.kind === filter;
  }

  function onMatrixKeydown(event) {
    const target = event.target;
    if (!(target instanceof HTMLElement) || !target.classList.contains('cell')) return;
    const keys = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'];
    if (!keys.includes(event.key)) return;
    const td = target.closest('td');
    const tr = td && td.closest('tr');
    if (!td || !tr) return;
    let next = null;
    const colIndex = Array.prototype.indexOf.call(tr.children, td);
    if (event.key === 'ArrowLeft') {
      const sibling = target.previousElementSibling;
      next = sibling && sibling.classList.contains('cell') ? sibling : (td.previousElementSibling && td.previousElementSibling.querySelector('.cell:last-child'));
    } else if (event.key === 'ArrowRight') {
      const sibling = target.nextElementSibling;
      next = sibling && sibling.classList.contains('cell') ? sibling : (td.nextElementSibling && td.nextElementSibling.querySelector('.cell'));
    } else if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      const row = event.key === 'ArrowUp' ? tr.previousElementSibling : tr.nextElementSibling;
      next = row && row.children[colIndex] && row.children[colIndex].querySelector('.cell');
    } else if (event.key === 'Home') {
      next = tr.querySelector('.cell');
    } else if (event.key === 'End') {
      const all = tr.querySelectorAll('.cell');
      next = all[all.length - 1];
    }
    if (next) { event.preventDefault(); next.focus(); }
  }

  function renderProvenance(state, d) {
    const receipt = d.receipt;
    const plan = receipt && receipt.plan && typeof receipt.plan === 'object' ? receipt.plan : null;
    const smoke = receipt && receipt.harness_smoke && typeof receipt.harness_smoke === 'object' ? receipt.harness_smoke : null;
    const combo = !d.canonical ? selectedCombo() : null;

    const planPath = combo ? combo.plan.path : (plan ? plan.path : null);
    const smokePath = combo ? combo.smoke.path : (smoke ? smoke.receipt : null);

    updatePathCell('pv-plan', planPath, planPath ? baseName(planPath) : null);
    setText('pv-plan-digest', combo ? shortDigest(combo.plan.digest) : (receipt ? shortDigest(receipt.plan_digest) : '--'));
    updatePathCell('pv-smoke', smokePath, smokePath ? `${parentName(smokePath)}/${baseName(smokePath)}` : null);
    setText('pv-smoke-id', combo ? combo.smoke.smoke_id : (smoke ? smoke.smoke_id : '--'));
    const backend = combo ? combo.smoke.backend : (receipt ? receipt.backend : null);
    setText('pv-backend', backend ? (backend === 'harbor' ? 'Harbor' : backend) : '--');
    const historicalReceipt = d.preview && receipt;
    setText('pv-receipt-label', historicalReceipt ? '历史 Matrix 回执' : 'Matrix 回执');
    setText('btn-view-receipt-label', historicalReceipt ? '查看历史回执' : '查看回执');
    updatePathCell('pv-receipt', receipt ? receipt.path : null, receipt ? baseName(receipt.path) : null);

    $('btn-view-plan').disabled = !planPath;
    $('btn-view-smoke').disabled = !smokePath;
    $('btn-view-receipt').disabled = !(receipt && receipt.path);
    $('btn-view-plan').dataset.path = planPath || '';
    $('btn-view-smoke').dataset.path = smokePath || '';
    $('btn-view-receipt').dataset.path = (receipt && receipt.path) || '';

    ensurePlanLoaded(planPath);
    ensureSmokeLoaded(smokePath);
    renderImage();
  }

  function updatePathCell(id, path, label) {
    const node = $(id);
    const key = path || '--';
    if (node.dataset.rendered === key) return;
    node.dataset.rendered = key;
    replaceChildren(node, path ? pathButton(path, label) : '--');
  }

  function renderImage() {
    const planData = app.planCache.data;
    const smokeData = app.smokeCache.data;
    let text = '--';
    const image = planData && planData.runtime_environment && planData.runtime_environment.container_images && planData.runtime_environment.container_images.candidate;
    if (image && typeof image === 'object') {
      text = `${image.name || image.reference || '候选镜像'} · ${shortDigest(image.id || image.digest)}`;
      const smokeImage = smokeData && smokeData.candidate_image;
      if (smokeImage && smokeImage.id && image.id && smokeImage.id !== image.id) text += ' · ⚠ 与 Smoke 使用的镜像不一致';
    } else if (smokeData && smokeData.candidate_image && typeof smokeData.candidate_image === 'object') {
      text = `${smokeData.candidate_image.name || '候选镜像'} · ${shortDigest(smokeData.candidate_image.id)}（来自 Smoke 回执）`;
    } else if (app.planCache.loading || app.smokeCache.loading) {
      text = '读取中…';
    } else if (app.planCache.path || app.smokeCache.path) {
      text = '不可用';
    }
    setText('pv-image', text);
  }

  function ensurePlanLoaded(path) {
    if (!path) { app.planCache = { path: null, data: null, loading: false }; return; }
    if (app.planCache.path === path) return;
    app.planCache = { path, data: null, loading: true };
    loadJson(path).then((data) => {
      if (app.planCache.path !== path) return;
      app.planCache = { path, data, loading: false };
      app.matrixSignature = '';  // rebuild headers with profile metadata
      if (app.state) applyState(app.state);
    }).catch(() => {
      if (app.planCache.path !== path) return;
      app.planCache = { path, data: null, loading: false };
      renderImage();
    });
  }

  function ensureSmokeLoaded(path) {
    if (!path) { app.smokeCache = { path: null, data: null, loading: false }; return; }
    if (app.smokeCache.path === path) return;
    app.smokeCache = { path, data: null, loading: true };
    loadJson(path).then((data) => {
      if (app.smokeCache.path !== path) return;
      app.smokeCache = { path, data, loading: false };
      renderImage();
    }).catch(() => {
      if (app.smokeCache.path !== path) return;
      app.smokeCache = { path, data: null, loading: false };
      renderImage();
    });
  }

  async function loadJson(path) {
    const response = await fetch('/api/file?path=' + encodeURIComponent(path), { cache: 'no-store' });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const payload = await response.json();
    return JSON.parse(payload.content);
  }

  function renderRunner(state, d) {
    const r = d.runner;
    const meta = RUNNER_STATUS[r.status] || { label: r.status || '--', chip: 'chip-neutral' };
    const node = $('rn-status');
    let label = meta.label; let chip = meta.chip;
    if (r.status === 'running' && !d.active) { label = '进程丢失（记录为运行中，但进程号不存在）'; chip = 'chip-red'; }
    if (r.status === 'exited') {
      if (r.returncode === 0) { label = '正常退出'; chip = 'chip-green'; }
      else if (r.returncode === null || r.returncode === undefined) { label = '异常退出（' + (r.exit_reason || '原因未知') + '）'; chip = 'chip-red'; }
      else if (r.returncode === 130 || r.returncode === -2) { label = `被中断信号终止（退出码 ${r.returncode}）`; chip = 'chip-amber'; }
      else { label = `异常退出（退出码 ${r.returncode}）`; chip = 'chip-red'; }
    }
    const wanted = chip + '|' + label;
    if (node.dataset.rendered !== wanted) {
      replaceChildren(node, el('span', { class: 'chip ' + chip, text: label }));
      node.dataset.rendered = wanted;
    }
    setText('rn-op', r.operation ? (OPERATION_LABEL[r.operation] || r.operation) : '--');
    setText('rn-pid', r.pid ? `${r.pid} / ${r.pgid || '--'}` : '--');
    setText('rn-started', r.started_at ? `${fmtTime(r.started_at)}${d.active ? ' · 已运行 ' + fmtDuration(r.started_at) : ''}` : '--');
    setText('rn-exited', r.exited_at ? fmtTime(r.exited_at) : (d.active ? '运行中' : '--'));
    updatePathCell('rn-log', r.log || null, r.log ? baseName(r.log) : null);
    $('btn-view-runner-log').disabled = !r.log;
    $('btn-view-runner-log').dataset.path = r.log || '';
  }

  // ------------------------------------------------------------------
  // Drawer
  // ------------------------------------------------------------------

  function openDrawer(cellId, trigger) {
    if (!app.state) return;
    const d = derive(app.state);
    const cell = d.cells.find((c) => c.cell_id === cellId);
    if (!cell) return;
    const previous = app.selectedCell;
    app.selectedCell = cellId;
    app.lastFocus = trigger || document.activeElement;
    if (previous && app.cellButtons.get(previous)) app.cellButtons.get(previous).classList.remove('is-selected');
    if (app.cellButtons.get(cellId)) app.cellButtons.get(cellId).classList.add('is-selected');
    renderDrawer(cell, d);
    const drawer = $('drawer');
    const wasHidden = drawer.hidden;
    drawer.hidden = false;
    $('drawer-backdrop').hidden = false;
    if (wasHidden) $('drawer-close').focus();
  }

  function closeDrawer() {
    const drawer = $('drawer');
    if (drawer.hidden) return;
    drawer.hidden = true;
    $('drawer-backdrop').hidden = true;
    if (app.selectedCell && app.cellButtons.get(app.selectedCell)) app.cellButtons.get(app.selectedCell).classList.remove('is-selected');
    const focusTarget = app.lastFocus;
    app.selectedCell = null;
    if (focusTarget && typeof focusTarget.focus === 'function' && document.contains(focusTarget)) focusTarget.focus();
  }

  function renderDrawer(cell, d) {
    const meta = statusMeta(cell.status);
    setText('drawer-title', cell.cell_id);
    const planData = app.planCache.data;
    const info = planData && planData.profiles && planData.profiles[cell.profile];
    setText('drawer-sub', `任务 ${cell.task} · 模型配置 ${cell.profile}${info && info.model ? ' · ' + info.model : ''}${info && info.harness ? ' · ' + harnessLabel(info.harness) : ''} · 第 ${cell.attempt || 1} 次尝试`);

    const statusLine = $('drawer-status');
    const noteText = meta.terminal
      ? '本轮失败已记录；可在执行进程停止后通过「重跑失败项」重新排队。'
      : meta.resumable
        ? '可恢复：点击「继续」后会重新执行此单元格。'
        : cell.status === 'running'
          ? (cell.phase === 'evaluating' ? '正在评估候选产物。' : '候选正在 Harbor 中执行。')
          : cell.status === 'completed'
            ? (Array.isArray(cell.admission_warnings) && cell.admission_warnings.length
              ? '游戏可以打开游玩；其余问题按提醒记录。'
              : '游戏可以打开游玩。')
            : '尚未执行。';
    const key = `${meta.chip}|${meta.label}|${noteText}`;
    if (statusLine.dataset.rendered !== key) {
      replaceChildren(statusLine, [
        el('span', { class: 'chip ' + meta.chip }, [svgIcon(meta.icon), meta.label]),
        el('span', { class: 'status-note' + (meta.terminal ? ' is-terminal' : meta.resumable ? ' is-resumable' : ''), text: noteText }),
      ]);
      statusLine.dataset.rendered = key;
    }

    const yesNo = (v) => (v === true ? '是' : v === false ? '否' : '--');
    const kv = [
      ['状态', `${meta.label}${cell.phase ? ' · 阶段：' + phaseLabel(cell.phase) : ''}`, false],
      ['成功 / 证据完整', `${yesNo(cell.passed)} / ${yesNo(cell.trusted)}`, true],
      ['可游玩', yesNo(cell.playable), true],
      ['开始', fmtTime(cell.started_at), true],
      ['完成', cell.completed_at ? fmtTime(cell.completed_at) : (cell.status === 'running' ? '运行中' : '--'), true],
      ['耗时', cell.started_at ? fmtDuration(cell.started_at, cell.completed_at || (cell.status === 'running' ? null : cell.started_at)) : '--', true],
    ];
    const kvNode = $('drawer-kv');
    const kvKey = JSON.stringify(kv) + '|' + (cell.run || '') + '|' + (cell.evaluation || '');
    if (kvNode.dataset.rendered !== kvKey) {
      const items = [];
      for (const [k, v, mono] of kv) { items.push(el('dt', { text: k })); items.push(el('dd', { class: mono ? 'mono' : null, text: v })); }
      items.push(el('dt', { text: '运行目录' }));
      items.push(el('dd', { class: 'mono' }, cell.run ? cell.run : '--'));
      items.push(el('dt', { text: '评估报告' }));
      items.push(el('dd', { class: 'mono' }, cell.evaluation ? pathButton(cell.evaluation, 'evaluation/report.json') : '--'));
      replaceChildren(kvNode, items);
      kvNode.dataset.rendered = kvKey;
    }

    const failures = [];
    if (cell.infrastructure_error) failures.push({ text: cell.infrastructure_error, infra: true });
    if (Array.isArray(cell.evidence_failures)) for (const f of cell.evidence_failures) failures.push({ text: String(f), infra: false });
    const failBox = $('drawer-failures');
    const failKey = JSON.stringify(failures);
    if (failBox.dataset.rendered !== failKey) {
      replaceChildren($('drawer-failure-list'), failures.map((f) => el('li', { class: f.infra ? 'is-infra' : null, text: f.text })));
      failBox.hidden = failures.length === 0;
      failBox.dataset.rendered = failKey;
    }

    const warnings = Array.isArray(cell.admission_warnings)
      ? cell.admission_warnings.map(String)
      : [];
    const warningBox = $('drawer-warnings');
    const warningKey = JSON.stringify(warnings);
    if (warningBox.dataset.rendered !== warningKey) {
      replaceChildren(
        $('drawer-warning-list'),
        warnings.map((warning) => el('li', { text: warning })),
      );
      warningBox.hidden = warnings.length === 0;
      warningBox.dataset.rendered = warningKey;
    }

    const files = $('drawer-files');
    const fileKey = (cell.run || '') + '|' + (cell.evaluation || '');
    if (files.dataset.rendered !== fileKey) {
      if (!cell.run) {
        replaceChildren(files, el('p', { class: 'file-list-empty', text: '此单元格尚未产生运行目录。' }));
      } else {
        const root = String(cell.run).replace(/\/+$/, '');
        replaceChildren(files, RUN_FILES.map((f) => {
          const path = root + '/' + f.rel;
          const btn = el('button', { type: 'button', class: 'file-btn', title: path, 'aria-label': `查看 ${f.kind}：${path}` }, [
            svgIcon('i-file-text'),
            el('span', { class: 'file-kind', text: f.kind }),
            el('span', { class: 'mono', text: f.rel }),
          ]);
          btn.addEventListener('click', () => openFile(path));
          return btn;
        }));
      }
      files.dataset.rendered = fileKey;
    }
  }

  // ------------------------------------------------------------------
  // File viewer
  // ------------------------------------------------------------------

  async function openFile(path) {
    const dialog = $('dlg-file');
    app.fileDialogPath = path;
    setText('dlg-file-title', baseName(path));
    setText('dlg-file-path', path);
    $('dlg-file-download').href = '/api/file?path=' + encodeURIComponent(path) + '&download=true';
    const content = $('dlg-file-content');
    content.classList.remove('is-error');
    content.textContent = '读取中…';
    if (!dialog.open) {
      app.lastFocus = document.activeElement;
      dialog.showModal();
    }
    try {
      const response = await fetch('/api/file?path=' + encodeURIComponent(path), { cache: 'no-store' });
      const payload = await response.json().catch(() => null);
      if (app.fileDialogPath !== path) return;
      if (!response.ok) {
        content.classList.add('is-error');
        content.textContent = `无法读取：${payload && payload.detail ? payload.detail : 'HTTP ' + response.status}\n\n文件可能尚不存在（例如尚未进入该阶段），或不在运行记录目录内。`;
        setText('dlg-file-hint', '读取失败。');
        return;
      }
      let text = payload.content || '';
      let hint = `显示文件末尾（最多 200 KB），共 ${text.length.toLocaleString()} 字符。`;
      if (/\.json$/.test(path)) {
        try { text = JSON.stringify(JSON.parse(text), null, 2); hint += ' 已格式化 JSON。'; } catch (_) { hint += ' JSON 不完整或已被截断，按原文显示。'; }
      }
      content.textContent = text || '（空文件）';
      setText('dlg-file-hint', hint);
    } catch (error) {
      if (app.fileDialogPath !== path) return;
      content.classList.add('is-error');
      content.textContent = '读取失败：' + (error && error.message ? error.message : String(error));
    }
  }

  // ------------------------------------------------------------------
  // Actions
  // ------------------------------------------------------------------

  function setBusy(action, busy) {
    app.busy = busy;
    const btn = $('btn-' + action);
    if (btn) btn.classList.toggle('is-busy', busy);
    if (app.state) renderControls(app.state, derive(app.state));
  }

  async function runAction(action, body, successText) {
    if (app.busy) return;
    setBusy(action, true);
    try {
      const result = await postAction(action, body);
      logActivity('ok', successText + (result && result.command ? `（命令：${baseName(result.command)}）` : ''));
      notify('ok', successText);
      if (action === 'pause') app.pauseRequestedAt = new Date().toISOString();
      await fetchState().catch(() => {});
    } catch (error) {
      const message = error && error.message ? error.message : String(error);
      const label = ACTION_LABEL[action] || action;
      logActivity('error', `${label}失败：${message}`);
      notify('error', `${label}请求被拒绝：${message}`, true);
    } finally {
      setBusy(action, false);
    }
  }

  function openStartDialog() {
    const combo = selectedCombo();
    if (!combo) {
      notify('warn', '启动前配置尚未就绪：没有可用的运行配置。');
      return;
    }
    const plan = combo.plan;
    const smoke = combo.smoke;
    setText('dlg-start-season', plan.season || '未知赛季');
    setText('dlg-start-plan', `Plan 由本地冻结配置生成 · ${fmtTime(plan.modified_at)}`);
    setText('dlg-start-smoke', `Harbor 已完成 ${CORE_HARNESSES} 连通性检查，全部通过 · ${fmtTime(smoke.completed_at)}`);
    setText('dlg-start-backend', 'Harbor');
    replaceChildren($('dlg-start-details'), kvItems([
      ['Plan 文件', plan.path, true],
      ['Plan 摘要', plan.digest, true],
      ['Smoke 回执', smoke.path, true],
      ['Smoke 编号', smoke.smoke_id, true],
      ['启动请求', JSON.stringify({ plan: plan.path, smoke_receipt: smoke.path, backend: 'harbor' }), true],
    ]));
    app.lastFocus = document.activeElement;
    $('dlg-start').showModal();
    $('dlg-start-confirm').focus();
  }

  function openInterruptDialog() {
    if (!app.state) return;
    const d = derive(app.state);
    setText('dlg-int-op', d.runner.operation ? (OPERATION_LABEL[d.runner.operation] || d.runner.operation) : '--');
    setText('dlg-int-pid', d.runner.pid ? `${d.runner.pid} / ${d.runner.pgid || '--'}` : '--');
    setText('dlg-int-task', d.currentTask || '--');
    replaceChildren($('dlg-int-text'), ['将向执行进程组发送中断信号（SIGINT）。正在执行的候选会被标记为', el('strong', { text: '已中断' }), '，之后可通过「继续」恢复。若只想在当前任务完成后停止，请改用「暂停」。']);
    const ack = $('dlg-int-ack');
    ack.checked = false;
    $('dlg-interrupt-confirm').disabled = true;
    app.lastFocus = document.activeElement;
    $('dlg-interrupt').showModal();
    ack.focus();
  }

  function updateInvalidateConfirm() {
    const reason = $('dlg-invalidate-reason').value.trim();
    $('dlg-invalidate-confirm').disabled = !reason || !$('dlg-invalidate-ack').checked;
  }

  function openInvalidateDialog() {
    if (!app.state || !app.state.receipt) return;
    const receipt = app.state.receipt;
    setText('dlg-invalidate-id', receipt.matrix_id || '--');
    const status = MATRIX_STATUS[receipt.status];
    setText('dlg-invalidate-status', status ? status.label : (receipt.status || '--'));
    $('dlg-invalidate-reason').value = '';
    $('dlg-invalidate-ack').checked = false;
    updateInvalidateConfirm();
    app.lastFocus = document.activeElement;
    $('dlg-invalidate').showModal();
    $('dlg-invalidate-reason').focus();
  }

  function restoreFocus() {
    const target = app.lastFocus;
    if (target && typeof target.focus === 'function' && document.contains(target)) target.focus();
  }

  // ------------------------------------------------------------------
  // Wiring
  // ------------------------------------------------------------------

  function wire() {
    $('btn-prepare').addEventListener('click', () => {
      app.lastFocus = document.activeElement;
      $('dlg-prepare').showModal();
      $('dlg-prepare-confirm').focus();
    });
    $('btn-start').addEventListener('click', openStartDialog);
    $('btn-pause').addEventListener('click', () => runAction('pause', null, '已请求暂停：执行进程将在下一个任务边界停止。'));
    $('btn-interrupt').addEventListener('click', openInterruptDialog);
    $('btn-resume').addEventListener('click', () => runAction('resume', null, '已请求继续：执行进程正在从正式回执恢复。'));
    $('btn-retry').addEventListener('click', () => runAction('retry', {}, '失败单元格已保留历史记录、重新排队，并开始继续执行 Matrix。'));
    $('btn-invalidate').addEventListener('click', openInvalidateDialog);
    $('btn-refresh').addEventListener('click', () => {
      const btn = $('btn-refresh');
      btn.classList.add('is-busy');
      fetchState().then(() => notify('info', '状态已刷新。')).catch((error) => notify('error', '刷新失败：' + error.message, true)).finally(() => btn.classList.remove('is-busy'));
    });
    $('notice-close').addEventListener('click', () => { $('notice').hidden = true; });

    $('sel-config').addEventListener('change', (event) => {
      app.selectedComboId = event.target.value || null;
      renderStartReadiness();
      if (app.state) applyState(app.state);
    });
    $('start-form').addEventListener('submit', (event) => { event.preventDefault(); openStartDialog(); });
    $('dlg-start-confirm').addEventListener('click', () => {
      const plan = selectedPlan();
      const smoke = selectedSmoke();
      $('dlg-start').close();
      if (!plan || !smoke) return;
      runAction('start', { plan: plan.path, smoke_receipt: smoke.path, backend: 'harbor' }, `已提交启动请求：${plan.season || '未知赛季'} 的运行配置（Plan 生成于 ${fmtTime(plan.modified_at)}，Harbor Smoke 通过于 ${fmtTime(smoke.completed_at)}）。`);
    });
    $('dlg-prepare-confirm').addEventListener('click', () => {
      $('dlg-prepare').close();
      runAction('prepare', null, '已开始准备运行配置；完成后不会自动启动 Matrix。');
    });
    $('dlg-int-ack').addEventListener('change', (event) => { $('dlg-interrupt-confirm').disabled = !event.target.checked; });
    $('dlg-interrupt-confirm').addEventListener('click', () => {
      $('dlg-interrupt').close();
      runAction('interrupt', null, '已向执行进程组发送中断信号。');
    });
    $('dlg-invalidate-reason').addEventListener('input', updateInvalidateConfirm);
    $('dlg-invalidate-ack').addEventListener('change', updateInvalidateConfirm);
    $('dlg-invalidate-confirm').addEventListener('click', () => {
      const reason = $('dlg-invalidate-reason').value.trim();
      if (!reason || !$('dlg-invalidate-ack').checked) return;
      $('dlg-invalidate').close();
      runAction('invalidate', { reason }, '正式 Matrix 已作废；旧记录已保留，现在可以创建新的 Matrix。');
    });

    for (const dialog of document.querySelectorAll('dialog')) {
      dialog.addEventListener('close', restoreFocus);
      dialog.addEventListener('click', (event) => {
        // Click on the backdrop (outside the dialog's content box) closes it.
        const rect = dialog.getBoundingClientRect();
        const inside = event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom;
        if (!inside && event.target === dialog) dialog.close();
      });
      for (const btn of dialog.querySelectorAll('[data-close]')) btn.addEventListener('click', () => dialog.close());
    }
    $('dlg-file-close').addEventListener('click', () => $('dlg-file').close());
    $('dlg-file-refresh').addEventListener('click', () => { if (app.fileDialogPath) openFile(app.fileDialogPath); });
    $('dlg-file-copy').addEventListener('click', async () => {
      if (!app.fileDialogPath) return;
      try {
        await navigator.clipboard.writeText(app.fileDialogPath);
        setText('dlg-file-hint', '路径已复制到剪贴板。');
      } catch (_) {
        setText('dlg-file-hint', '无法访问剪贴板，请手动复制上方路径。');
      }
    });

    for (const id of ['btn-view-plan', 'btn-view-smoke', 'btn-view-receipt', 'btn-view-runner-log']) {
      $(id).addEventListener('click', () => { const path = $(id).dataset.path; if (path) openFile(path); });
    }

    $('matrix-body').addEventListener('keydown', onMatrixKeydown);
    $('drawer-close').addEventListener('click', closeDrawer);
    $('drawer-backdrop').addEventListener('click', closeDrawer);
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !$('drawer').hidden && !document.querySelector('dialog[open]')) {
        event.preventDefault();
        closeDrawer();
      }
    });

    $('cell-filter').addEventListener('click', (event) => {
      const btn = event.target.closest('button[data-filter]');
      if (!btn) return;
      app.filter = btn.dataset.filter;
      for (const other of $('cell-filter').querySelectorAll('button')) {
        const active = other === btn;
        other.classList.toggle('seg-active', active);
        other.setAttribute('aria-selected', active ? 'true' : 'false');
      }
      if (app.state) renderMatrix(derive(app.state));
    });
    $('cell-filter').addEventListener('keydown', (event) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      const tabs = Array.from($('cell-filter').querySelectorAll('button'));
      const index = tabs.indexOf(document.activeElement);
      if (index < 0) return;
      event.preventDefault();
      const next = tabs[(index + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
      next.focus();
      next.click();
    });

    setInterval(() => {
      setText('age-label', app.lastUpdate ? fmtAge(Date.now() - app.lastUpdate) : '--');
      if (app.state && app.state.runner && app.state.runner.active && app.state.runner.started_at) {
        setText('rn-started', `${fmtTime(app.state.runner.started_at)} · 已运行 ${fmtDuration(app.state.runner.started_at)}`);
      }
    }, 1000);

    if (!TOKEN || TOKEN === '__CONTROL_TOKEN__') {
      notify('warn', '未注入控制令牌，操作请求会被服务端拒绝。请通过 `web3dgamebench control` 命令输出的地址访问。', true);
    }
  }

  function boot() {
    wire();
    fetchState().then(() => connectEvents()).catch((error) => {
      setConnection('lost', '离线');
      notify('error', '无法读取 /api/state：' + error.message, true);
      connectEvents();
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
