/* Web3DGameBench Matrix control console — client logic (no external assets, localhost only). */
(function () {
  'use strict';

  const TOKEN = (document.querySelector('meta[name="control-token"]') || {}).content || '';
  const $ = (id) => document.getElementById(id);

  // ------------------------------------------------------------------
  // Static vocab
  // ------------------------------------------------------------------

  const CELL_STATUS = {
    pending: { label: '待执行', icon: 'i-circle', cls: 'cell-pending', kind: 'pending', chip: 'chip-neutral' },
    running: { label: '运行中', icon: 'i-loader', cls: 'cell-running', kind: 'running', chip: 'chip-cyan', spin: true },
    completed: { label: '完成 · trusted', icon: 'i-check', cls: 'cell-completed', kind: 'completed', chip: 'chip-green' },
    'candidate-failure': { label: 'candidate 失败', icon: 'i-x', cls: 'cell-candidate-failure', kind: 'failed', chip: 'chip-red', terminal: true },
    'evidence-failure': { label: 'evidence 失败', icon: 'i-alert-triangle', cls: 'cell-evidence-failure', kind: 'failed', chip: 'chip-red', terminal: true },
    'infrastructure-error': { label: '基础设施错误', icon: 'i-alert-octagon', cls: 'cell-infrastructure-error', kind: 'resumable', chip: 'chip-amber', resumable: true },
    interrupted: { label: '已中断', icon: 'i-pause-circle', cls: 'cell-interrupted', kind: 'resumable', chip: 'chip-amber', resumable: true },
  };
  const UNKNOWN_STATUS = { label: '未知状态', icon: 'i-info', cls: 'cell-pending', kind: 'pending', chip: 'chip-neutral' };

  const MATRIX_STATUS = {
    running: { label: '执行中', chip: 'chip-cyan' },
    incomplete: { label: '未完成（停在 task barrier）', chip: 'chip-amber' },
    interrupted: { label: '已中断', chip: 'chip-amber' },
    complete: { label: '已完成 · 已封存', chip: 'chip-green' },
    invalidated: { label: '已作废 (invalidated)', chip: 'chip-red' },
  };

  const RUNNER_STATUS = {
    idle: { label: '空闲', chip: 'chip-neutral' },
    running: { label: '运行中', chip: 'chip-cyan' },
    exited: { label: '已退出', chip: 'chip-neutral' },
  };

  const OPERATION_LABEL = {
    'matrix-start': '启动 Matrix',
    'matrix-resume': '继续 Matrix',
    calibration: '校准门禁',
  };

  // Calibration gate vocabulary. Task order, profile and season mirror configs/calibration.toml;
  // the receipt stays authoritative and any extra task it reports is appended to the rows.
  const CALIBRATION_TASKS = ['canyon-strike', 'bombsite-retake', 'first-night'];
  const CALIBRATION_PROFILE = 'pi-deepseek-v4-flash';
  const CALIBRATION_SEASON = 'season-1';
  const CALIBRATION_STATUS = {
    running: { label: '运行中', chip: 'chip-cyan' },
    passed: { label: '已通过', chip: 'chip-green' },
    failed: { label: '未通过', chip: 'chip-red' },
    interrupted: { label: '已中断', chip: 'chip-amber' },
  };
  const CALIBRATION_CHECKS = [
    { key: 'trusted_terminal', label: '可信终态', title: 'manifest status 为 candidate-complete，且 goal 被观测为 complete' },
    { key: 'task_brief_preserved', label: 'brief 保留', title: 'prompt.task_brief_preserved 为 true' },
    { key: 'completion_evidence', label: '完成证据', title: '上游 goal complete，且 runner evaluator 独立构建成功并绑定 source/dist digest' },
    { key: 'bounded_verification', label: '验证有界', title: 'failure_scope 不是 candidate-verification-overrun' },
    { key: 'evaluator_trusted', label: 'evaluator 可信', title: 'evaluation report 的 trusted 为 true' },
    { key: 'evaluator_not_below_baseline', label: '≥ baseline', title: 'evaluator passed_checks 不低于 baseline 要求' },
  ];
  const BASELINE_KIND = {
    'conservative-full-admission': '保守全量',
  };
  const CALIB_ROW = {
    passed: { label: '通过', chip: 'chip-green', icon: 'i-check' },
    failed: { label: '未通过', chip: 'chip-red', icon: 'i-x' },
    running: { label: '运行中', chip: 'chip-cyan', icon: 'i-loader', spin: true },
    pending: { label: '待执行', chip: 'chip-neutral', icon: 'i-circle' },
    skipped: { label: '未执行', chip: 'chip-amber', icon: 'i-pause-circle' },
    stale: { label: '未完成 · runner 已退出', chip: 'chip-amber', icon: 'i-alert-triangle' },
  };

  const RUN_FILES = [
    { rel: 'manifest.json', kind: 'candidate manifest' },
    { rel: 'events.jsonl', kind: 'candidate 事件流' },
    { rel: 'stderr.log', kind: 'candidate stderr' },
    { rel: 'final.txt', kind: 'candidate 最终输出' },
    { rel: 'evaluation/report.json', kind: 'evaluation 报告' },
    { rel: 'evaluation/evaluator.stdout.log', kind: 'evaluator stdout' },
    { rel: 'evaluation/evaluator.stderr.log', kind: 'evaluator stderr' },
    { rel: 'evaluation/build.stdout.log', kind: 'build stdout' },
    { rel: 'evaluation/build.stderr.log', kind: 'build stderr' },
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
    calibPlansSignature: '',
    calibTableKey: '',
    cellButtons: new Map(),
    pauseRequestedAt: null,
    lastRunnerKey: null,
    lastMatrixStatus: null,
    lastCalibrationKey: null,
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
    const cells = receipt && Array.isArray(receipt.cells) ? receipt.cells : [];
    const tasks = [];
    const profiles = [];
    const grid = new Map();
    const counts = { total: cells.length, pending: 0, running: 0, completed: 0, candidate: 0, evidence: 0, infra: 0, interrupted: 0, trusted: 0, evaluating: 0 };
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
    const calibration = state.calibration && typeof state.calibration === 'object' ? state.calibration : null;
    const calibrating = active && runner.operation === 'calibration';
    const calibTasks = calibrationTaskList(calibration);
    const calibResults = calibrationResults(calibration);
    const calibNext = calibration && calibration.status === 'running'
      ? (calibTasks.find((t) => !calibResults.some((r) => r.task === t)) || null)
      : null;

    let currentTask = runningTasks.length ? runningTasks.join(', ') : null;
    if (!currentTask && active) {
      const next = tasks.find((t) => (grid.size && cells.some((c) => c.task === t && (c.status === 'pending' || statusMeta(c.status).resumable))));
      currentTask = next ? next + '（准备中）' : null;
    }
    if (calibrating) currentTask = calibNext ? calibNext + '（校准）' : null;

    let phase;
    if (calibrating) {
      phase = calibration && calibration.status === 'running'
        ? `校准门禁执行中 · 已完成 ${calibResults.length}/${calibTasks.length} task`
        : '校准 runner 启动中（尚未写入 receipt）';
    } else if (active) {
      if (counts.evaluating > 0 && counts.running === counts.evaluating) phase = '评估中 (evaluating)';
      else if (counts.evaluating > 0) phase = 'candidate 执行 + 评估中';
      else if (counts.running > 0) phase = 'candidate 执行中';
      else phase = 'runner 启动 / 校验 frozen inputs';
      if (app.pauseRequestedAt) phase += ' · 已请求 pause，将在下一个 task barrier 停止';
    } else if (!receipt) {
      phase = canonical ? 'canonical receipt 不可读' : '未启动';
    } else {
      switch (receipt.status) {
        case 'complete': phase = 'Matrix 已完成'; break;
        case 'incomplete': phase = '已在 task barrier 停止，等待 resume'; break;
        case 'interrupted': phase = '已中断，等待 resume'; break;
        case 'invalidated': phase = 'receipt 已作废'; break;
        case 'running': phase = 'runner 未运行（receipt 仍标记 running，可 resume）'; break;
        default: phase = receipt.status || '--';
      }
    }

    return {
      receipt, cells, tasks, profiles, grid, counts, runner, active, canonical, currentTask, phase, taskState, runningTasks,
      calibration, calibrating, calibTasks, calibResults, calibNext,
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
    // Plan selectors are filled before the controls so start gating sees the current selection.
    renderCalibration(state, d);
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
        const label = OPERATION_LABEL[d.runner.operation] || d.runner.operation || 'runner';
        logActivity(code === 0 ? 'ok' : 'warn', `${label} 进程已退出${code === null || code === undefined ? '' : `（returncode ${code}）`}${d.runner.exit_reason ? '：' + d.runner.exit_reason : ''}`);
        app.pauseRequestedAt = null;
      } else if (d.runner.status === 'running') {
        logActivity('info', `${OPERATION_LABEL[d.runner.operation] || d.runner.operation || 'runner'} 进程已启动（pid ${d.runner.pid}）`);
      }
    }
    app.lastRunnerKey = runnerKey;
    if (!d.active) app.pauseRequestedAt = null;

    const matrixStatus = d.receipt ? d.receipt.status : null;
    if (app.lastMatrixStatus !== null && matrixStatus !== app.lastMatrixStatus && matrixStatus) {
      const meta = MATRIX_STATUS[matrixStatus];
      logActivity('info', `Matrix receipt 状态变为 ${meta ? meta.label : matrixStatus}`);
    }
    app.lastMatrixStatus = matrixStatus;

    const gate = d.calibration;
    const calKey = gate ? `${gate.calibration_id}|${gate.status}|${d.calibResults.length}` : 'none';
    if (app.lastCalibrationKey !== null && calKey !== app.lastCalibrationKey && gate) {
      const [prevId, prevStatus, prevCount] = app.lastCalibrationKey.split('|');
      const last = d.calibResults[d.calibResults.length - 1];
      if (prevId === gate.calibration_id && Number(prevCount) < d.calibResults.length && last) {
        const ev = last.evaluator && typeof last.evaluator === 'object' ? last.evaluator : null;
        logActivity(last.status === 'passed' ? 'ok' : 'warn', `校准 task ${last.task} ${last.status === 'passed' ? '通过' : '未通过'}（evaluator ${ev ? `${ev.passed_checks}/${ev.total_checks}` : '--'}${last.status === 'passed' ? '' : '；未通过：' + failedCheckLabels(last).join('、')}）`);
      }
      if (gate.status !== prevStatus || prevId !== gate.calibration_id) {
        if (gate.status === 'passed') logActivity('ok', `校准 ${gate.calibration_id} 已通过（${d.calibResults.length}/${d.calibTasks.length} task，watchdog 通过），Matrix 门禁已解锁。`);
        else if (gate.status === 'failed') logActivity('warn', `校准 ${gate.calibration_id} 未通过：${calibrationFailureDetail(gate) || '原因未记录'}`);
        else if (gate.status === 'interrupted') logActivity('warn', `校准 ${gate.calibration_id} 已中断（完成 ${d.calibResults.length}/${d.calibTasks.length} task），需重新校准。`);
        else if (gate.status === 'running') logActivity('info', `校准 ${gate.calibration_id} 已开始（${gate.profile || CALIBRATION_PROFILE}，串行 ${d.calibTasks.length} task，${gate.backend || 'harbor'}）。`);
      }
    }
    app.lastCalibrationKey = calKey;
  }

  function renderTop(state) {
    setText('server-time', fmtClock(state.server_time));
  }

  function renderControls(state, d) {
    const controls = state.controls || {};
    const buttons = {
      start: $('btn-start'),
      pause: $('btn-pause'),
      interrupt: $('btn-interrupt'),
      resume: $('btn-resume'),
    };
    const gate = gateStatus(state, selectedPlan() || selectedCalibPlan());
    buttons.start.disabled = app.busy || controls.can_start !== true || !gate.ok;
    buttons.pause.disabled = app.busy || controls.can_pause !== true;
    buttons.interrupt.disabled = app.busy || controls.can_interrupt !== true;
    buttons.resume.disabled = app.busy || controls.can_resume !== true;
    $('btn-calibrate').disabled = app.busy || controls.can_calibrate !== true || !selectedCalibPlan();

    const runnerMeta = RUNNER_STATUS[d.runner.status] || { label: d.runner.status || '--', chip: 'chip-neutral' };
    let runnerLabel = 'runner ' + runnerMeta.label;
    let runnerChip = runnerMeta.chip;
    if (d.runner.status === 'running' && !d.active) { runnerLabel = 'runner 进程丢失'; runnerChip = 'chip-red'; }
    if (d.active && d.runner.operation) runnerLabel += ' · ' + (OPERATION_LABEL[d.runner.operation] || d.runner.operation);
    setChip($('runner-chip'), runnerChip, runnerLabel);

    let hint;
    const receiptStatus = d.receipt ? d.receipt.status : null;
    if (d.calibrating) {
      hint = `校准门禁正在串行执行（已完成 ${d.calibResults.length}/${d.calibTasks.length} task${d.calibNext ? '，当前 ' + d.calibNext : ''}）。「暂停」不适用于校准；「中断」会向进程组发送 SIGINT，receipt 将标记为 interrupted，需重新校准。`;
    } else if (d.active) {
      hint = controls.can_pause
        ? 'Matrix 正在执行。「暂停」会在下一个 task barrier 优雅停止；「中断」立即向进程组发送 SIGINT。'
        : 'runner 正在运行，当前 receipt 状态不接受 pause，仅可立即中断。';
      if (app.pauseRequestedAt) hint = `已于 ${fmtTime(app.pauseRequestedAt)} 请求 pause，runner 将在当前 task 完成后停止。仍可立即中断。`;
    } else if (!d.canonical) {
      if (gate.ok && controls.can_start) hint = '校准门禁已通过并与所选 plan 一致。选择 smoke receipt 后点击「启动」创建 canonical Matrix。';
      else if (gate.ok) hint = '校准门禁已通过，但服务端当前不允许启动 Matrix。';
      else hint = '启动已锁定：' + gate.reason;
    } else if (controls.can_resume) {
      hint = `canonical Matrix 处于「${(MATRIX_STATUS[receiptStatus] || { label: receiptStatus }).label}」，可通过「继续」从 receipt 恢复未完成的 cell。`;
    } else if (receiptStatus === 'complete') {
      hint = 'canonical Matrix 已完成并封存，没有可执行的操作。';
    } else if (receiptStatus === 'invalidated') {
      hint = 'canonical receipt 已作废，控制面不提供进一步操作。';
    } else if (!d.receipt) {
      hint = 'canonical 记录存在，但 receipt 无法加载或校验失败，请人工检查。';
    } else {
      hint = '当前没有可用操作。';
    }
    setText('controls-hint', hint);
  }

  function renderStartPanel(state, d) {
    const panel = $('start-panel');
    const controls = state.controls || {};
    const show = controls.can_start === true;
    if (panel.hidden === show) panel.hidden = !show;
    if (!show) return;

    const options = state.options || { plans: [], smokes: [] };
    const plans = Array.isArray(options.plans) ? options.plans : [];
    const smokes = Array.isArray(options.smokes) ? options.smokes : [];
    const signature = plans.map((p) => p.path + '|' + p.modified_at).join(';') + '##' + smokes.map((s) => s.path + '|' + s.status + '|' + s.completed_at).join(';');
    if (signature !== app.optionsSignature) {
      app.optionsSignature = signature;
      const planSel = $('sel-plan');
      const smokeSel = $('sel-smoke');
      const prevPlan = planSel.value || $('sel-calib-plan').value;
      const prevSmoke = smokeSel.value;
      fillPlanSelect(planSel, plans);
      replaceChildren(smokeSel, smokes.length ? smokes.map((s) => el('option', {
        value: s.path,
        text: `${s.name}  ·  ${s.status || '?'}  ·  ${s.backend || '?'}  ·  ${shortDigest(s.plan_digest)}`,
      })) : [el('option', { value: '', text: '（runs/smoke 下没有可用 receipt）' })]);
      const wantedPlan = plans.some((p) => p.path === prevPlan) ? prevPlan : preferredPlanPath(state, plans);
      if (wantedPlan) planSel.value = wantedPlan;
      syncPlanSelects(planSel.value);
      if (smokes.some((s) => s.path === prevSmoke)) smokeSel.value = prevSmoke;
      else pickMatchingSmoke();
      smokeSel.disabled = !smokes.length;
    }
    renderStartMeta();
  }

  function selectedPlan() {
    const path = $('sel-plan').value;
    const plans = (app.state && app.state.options && app.state.options.plans) || [];
    return plans.find((p) => p.path === path) || null;
  }

  function selectedSmoke() {
    const path = $('sel-smoke').value;
    const smokes = (app.state && app.state.options && app.state.options.smokes) || [];
    return smokes.find((s) => s.path === path) || null;
  }

  function pickMatchingSmoke() {
    const plan = selectedPlan();
    const smokes = (app.state && app.state.options && app.state.options.smokes) || [];
    if (!plan) return;
    const match = smokes.find((s) => s.plan_digest === plan.digest && s.status === 'passed' && (s.backend || 'harbor') === 'harbor')
      || smokes.find((s) => s.plan_digest === plan.digest);
    if (match) $('sel-smoke').value = match.path;
  }

  function renderStartMeta() {
    const plan = selectedPlan();
    const smoke = selectedSmoke();
    setText('plan-meta', plan ? `${plan.plan_id || '--'} · 修改于 ${fmtTime(plan.modified_at)}` : '--');
    setText('smoke-meta', smoke ? `${smoke.smoke_id || '--'} · 完成于 ${fmtTime(smoke.completed_at)}` : '--');
    const warnings = [];
    const gate = gateStatus(app.state, plan);
    if (!gate.ok) warnings.push('校准门禁：' + gate.reason);
    if (plan && smoke && smoke.plan_digest && plan.digest && smoke.plan_digest !== plan.digest) {
      warnings.push('所选 smoke receipt 的 plan digest 与所选 plan 不一致，启动时的 Harbor 校验会拒绝。');
    }
    if (smoke && smoke.status && smoke.status !== 'passed') {
      warnings.push(`所选 smoke receipt 状态为 ${smoke.status}，只有 passed 的 receipt 才能用于启动。`);
    }
    if (smoke && smoke.backend && smoke.backend !== 'harbor') {
      warnings.push(`所选 smoke receipt 的 backend 为 ${smoke.backend}，控制面仅接受 harbor。`);
    }
    const box = $('start-warning');
    if (warnings.length) {
      $('start-warning-text').textContent = warnings.join(' ');
      box.hidden = false;
    } else {
      box.hidden = true;
    }
  }

  function renderOverview(state, d) {
    const receipt = d.receipt;
    const canonical = d.canonical;
    const receiptMatches = !!(receipt && canonical && receipt.matrix_id === canonical.matrix_id);

    let chipCls = 'chip-neutral';
    let chipText = '无 canonical Matrix';
    if (canonical && receiptMatches) {
      const meta = MATRIX_STATUS[receipt.status] || { label: receipt.status, chip: 'chip-neutral' };
      chipCls = meta.chip; chipText = 'canonical · ' + meta.label;
    } else if (canonical) {
      chipCls = 'chip-red'; chipText = 'canonical receipt 不可读';
    } else if (receipt) {
      const meta = MATRIX_STATUS[receipt.status] || { label: receipt.status, chip: 'chip-neutral' };
      chipCls = receipt.status === 'invalidated' ? 'chip-red' : 'chip-amber';
      chipText = '历史 receipt · ' + meta.label;
    }
    setChip($('matrix-chip'), chipCls, chipText);

    const banner = $('canonical-banner');
    let bannerCls = null; let bannerIcon = 'i-info'; let bannerText = '';
    if (canonical && !receipt) {
      bannerCls = 'banner-red'; bannerIcon = 'i-alert-octagon';
      bannerText = `canonical 记录指向 ${canonical.receipt || '（未知路径）'}，但该 receipt 无法加载或 digest 校验失败。请人工检查后再操作。`;
    } else if (canonical && !receiptMatches) {
      bannerCls = 'banner-red'; bannerIcon = 'i-alert-octagon';
      bannerText = `canonical 记录（${canonical.matrix_id}）指向的 receipt 无法加载；下方显示的是另一个历史 receipt ${receipt.matrix_id || ''}，仅供参考。`;
    } else if (!canonical && receipt) {
      bannerCls = receipt.status === 'invalidated' ? 'banner-red' : 'banner-amber';
      bannerIcon = 'i-alert-triangle';
      bannerText = receipt.status === 'invalidated'
        ? `下方显示的历史 receipt（${receipt.matrix_id || ''}）已被作废 (invalidated)，不是 canonical Matrix；本季尚无 canonical 声明。`
        : `下方显示的是历史 receipt（${receipt.matrix_id || ''}），不是 canonical Matrix；本季尚无 canonical 声明。`;
    } else if (receiptMatches && receipt.status === 'invalidated') {
      bannerCls = 'banner-red'; bannerIcon = 'i-alert-octagon';
      bannerText = 'canonical receipt 已被作废 (invalidated)。';
    } else if (receiptMatches && receipt.status === 'complete') {
      bannerCls = 'banner-green'; bannerIcon = 'i-lock';
      bannerText = `canonical Matrix 已完成并封存（${fmtTime(receipt.completed_at)}）。`;
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
    setText('st-trusted', has ? c.trusted : '--');
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
    setText('kv-task', d.currentTask || (receipt && receipt.execution_window && receipt.execution_window.stopped_at_task_barrier ? `停在 barrier：${receipt.execution_window.stopped_at_task_barrier}` : '--'));
    const statusNode = $('kv-status');
    if (receipt) {
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
    setText('kv-matrix-id', receipt ? receipt.matrix_id : (canonical ? canonical.matrix_id : '--'));
    setText('kv-season', receipt ? receipt.season : (canonical ? canonical.season : '--'));
    setText('kv-times', receipt ? `${fmtTime(receipt.created_at)} / ${fmtTime(receipt.updated_at)}` : '--');

    let windowText = '--';
    if (receipt && receipt.execution_window && typeof receipt.execution_window === 'object') {
      const w = receipt.execution_window;
      const parts = [];
      if (w.stop_after_task) parts.push(`stop-after ${w.stop_after_task}`);
      if (w.pause_requested_at) parts.push(`pause 请求于 ${fmtTime(w.pause_requested_at)}`);
      if (w.stopped_at_task_barrier) parts.push(`已停在 barrier ${w.stopped_at_task_barrier}`);
      if (w.stopped_at) parts.push(`停止于 ${fmtTime(w.stopped_at)}`);
      windowText = parts.length ? parts.join(' · ') : '（无约束）';
    } else if (receipt) {
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
    setText('matrix-dims', hasCells ? `${d.tasks.length} task × ${d.profiles.length} profile · ${d.cells.length} cell` : 'task × profile');
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

      const headRow = el('tr', null, [el('th', { class: 'corner', scope: 'col', text: 'task \\ profile' })]);
      for (const profile of d.profiles) {
        const info = profileInfo[profile] || {};
        const title = [profile, info.harness ? 'harness: ' + info.harness : null, info.model ? 'model: ' + info.model : null, info.effort ? 'effort: ' + info.effort : null].filter(Boolean).join('\n');
        headRow.appendChild(el('th', { scope: 'col', title }, [
          el('div', { class: 'col-head' }, [
            el('span', { class: 'col-main', text: profile }),
            el('span', { class: 'col-sub', text: info.harness || (profile.split('-')[0] || '') }),
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
      let tag = '';
      if (cell.status === 'running') tag = cell.phase === 'evaluating' ? 'eval' : 'run';
      else if (cell.status === 'completed') tag = 'ok';
      else if (cell.status === 'candidate-failure') tag = 'cand';
      else if (cell.status === 'evidence-failure') tag = 'evid';
      else if (cell.status === 'infrastructure-error') tag = 'infra';
      else if (cell.status === 'interrupted') tag = 'int';
      else tag = attemptsMatter ? 'a' + cell.attempt : '·';
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
      const label = `${cell.task} × ${cell.profile}${attemptsMatter ? ' · attempt ' + cell.attempt : ''}：${meta.label}${cell.phase ? '（' + cell.phase + '）' : ''}${meta.terminal ? '（终态）' : ''}`;
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

    const planPath = plan ? plan.path : null;
    const smokePath = smoke ? smoke.receipt : null;

    updatePathCell('pv-plan', planPath, planPath ? baseName(planPath) : null);
    setText('pv-plan-digest', receipt ? shortDigest(receipt.plan_digest) : '--');
    updatePathCell('pv-smoke', smokePath, smokePath ? `${parentName(smokePath)}/${baseName(smokePath)}` : null);
    setText('pv-smoke-id', smoke ? smoke.smoke_id : '--');
    setText('pv-backend', receipt ? receipt.backend : '--');
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
      text = `${image.name || image.reference || 'candidate'} · ${shortDigest(image.id || image.digest)}`;
      const smokeImage = smokeData && smokeData.candidate_image;
      if (smokeImage && smokeImage.id && image.id && smokeImage.id !== image.id) text += ' · ⚠ smoke image 不一致';
    } else if (smokeData && smokeData.candidate_image && typeof smokeData.candidate_image === 'object') {
      text = `${smokeData.candidate_image.name || 'candidate'} · ${shortDigest(smokeData.candidate_image.id)}（来自 smoke）`;
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
    if (r.status === 'running' && !d.active) { label = '进程丢失（记录为 running，但 pid 不存在）'; chip = 'chip-red'; }
    if (r.status === 'exited') {
      if (r.returncode === 0) { label = '正常退出'; chip = 'chip-green'; }
      else if (r.returncode === null || r.returncode === undefined) { label = '异常退出（' + (r.exit_reason || '原因未知') + '）'; chip = 'chip-red'; }
      else if (r.returncode === 130 || r.returncode === -2) { label = `被 SIGINT 中断（returncode ${r.returncode}）`; chip = 'chip-amber'; }
      else { label = `退出 returncode ${r.returncode}`; chip = 'chip-red'; }
    }
    const wanted = chip + '|' + label;
    if (node.dataset.rendered !== wanted) {
      replaceChildren(node, el('span', { class: 'chip ' + chip, text: label }));
      node.dataset.rendered = wanted;
    }
    setText('rn-op', r.operation ? `${OPERATION_LABEL[r.operation] || r.operation} (${r.operation})` : '--');
    setText('rn-pid', r.pid ? `${r.pid} / ${r.pgid || '--'}` : '--');
    setText('rn-started', r.started_at ? `${fmtTime(r.started_at)}${d.active ? ' · 已运行 ' + fmtDuration(r.started_at) : ''}` : '--');
    setText('rn-exited', r.exited_at ? fmtTime(r.exited_at) : (d.active ? '运行中' : '--'));
    updatePathCell('rn-log', r.log || null, r.log ? baseName(r.log) : null);
    $('btn-view-runner-log').disabled = !r.log;
    $('btn-view-runner-log').dataset.path = r.log || '';
  }

  // ------------------------------------------------------------------
  // Calibration gate
  // ------------------------------------------------------------------

  function calibrationResults(gate) {
    return gate && Array.isArray(gate.tasks)
      ? gate.tasks.filter((t) => t && typeof t === 'object' && typeof t.task === 'string')
      : [];
  }

  function calibrationTaskList(gate) {
    const tasks = CALIBRATION_TASKS.slice();
    for (const result of calibrationResults(gate)) if (!tasks.includes(result.task)) tasks.push(result.task);
    return tasks;
  }

  function failedCheckLabels(result) {
    const checks = result && result.checks && typeof result.checks === 'object' ? result.checks : {};
    const labels = [];
    for (const check of CALIBRATION_CHECKS) if (checks[check.key] !== true) labels.push(check.label);
    for (const key of Object.keys(checks)) {
      if (!CALIBRATION_CHECKS.some((c) => c.key === key) && checks[key] !== true) labels.push(key);
    }
    return labels;
  }

  function calibrationFailureDetail(gate) {
    const tasks = calibrationTaskList(gate);
    const results = calibrationResults(gate);
    const parts = [];
    if (gate.watchdog && gate.watchdog.passed !== true) {
      parts.push('watchdog 未通过' + (gate.watchdog.reason ? '（' + gate.watchdog.reason + '）' : ''));
    }
    const failed = results.filter((r) => r.status !== 'passed').map((r) => `${r.task}[${failedCheckLabels(r).join('、') || '未知'}]`);
    if (failed.length) parts.push('task 未通过：' + failed.join('，'));
    const missing = tasks.filter((t) => !results.some((r) => r.task === t));
    if (missing.length) parts.push('task 未执行：' + missing.join('，'));
    return parts.join('；');
  }

  // Precise reason why Matrix start is (or is not) unlocked for the given plan.
  function gateStatus(state, plan) {
    const gate = state && state.calibration && typeof state.calibration === 'object' ? state.calibration : null;
    const runner = (state && state.runner) || {};
    const active = runner.active === true;
    const calibrating = active && runner.operation === 'calibration';
    if (!gate) {
      return {
        ok: false,
        level: 'amber',
        reason: calibrating ? '校准正在启动，尚未写入 receipt。' : '尚无校准 receipt。请先在「校准门禁」面板选择 plan 并运行 3-task 校准。',
      };
    }
    const id = gate.calibration_id || '（无 id）';
    const tasks = calibrationTaskList(gate);
    const done = calibrationResults(gate).length;
    if (gate.status === 'running') {
      return calibrating
        ? { ok: false, level: 'cyan', reason: `校准 ${id} 正在执行（已完成 ${done}/${tasks.length} task），完成前不能启动 Matrix。` }
        : { ok: false, level: 'amber', reason: `校准 ${id} 记录为 running，但 runner 已退出（完成 ${done}/${tasks.length} task）；该 receipt 未闭合，需重新校准。` };
    }
    if (gate.status === 'failed') {
      const detail = calibrationFailureDetail(gate);
      return { ok: false, level: 'red', reason: `校准 ${id} 未通过${detail ? '：' + detail : ''}。请修复后重新校准。` };
    }
    if (gate.status === 'interrupted') {
      return { ok: false, level: 'amber', reason: `校准 ${id} 已被中断（完成 ${done}/${tasks.length} task），需重新运行完整校准。` };
    }
    if (gate.status !== 'passed') {
      return { ok: false, level: 'red', reason: `校准 ${id} 状态为 ${gate.status || '未知'}，不能作为门禁。` };
    }
    if (!plan) {
      return { ok: false, level: 'amber', reason: `校准 ${id} 已通过，但尚未选择 plan；请选择 digest 为 ${shortDigest(gate.plan_digest_sha256)} 的 plan。` };
    }
    if (!plan.digest || plan.digest !== gate.plan_digest_sha256) {
      return {
        ok: false,
        level: 'red',
        reason: `校准 ${id} 通过的 plan digest ${shortDigest(gate.plan_digest_sha256)}（${baseName(gate.plan)}）与所选 plan ${plan.name}（${shortDigest(plan.digest)}）不一致；请改选 ${baseName(gate.plan)}，或对所选 plan 重新校准。`,
      };
    }
    return { ok: true, level: 'green', reason: `校准 ${id} 已通过，plan digest ${shortDigest(gate.plan_digest_sha256)} 与所选 plan ${plan.name} 一致。` };
  }

  function selectedCalibPlan() {
    const path = $('sel-calib-plan').value;
    const plans = (app.state && app.state.options && app.state.options.plans) || [];
    return plans.find((p) => p.path === path) || null;
  }

  function preferredPlanPath(state, plans) {
    const gate = state && state.calibration;
    if (!gate || gate.status !== 'passed') return null;
    const match = plans.find((p) => p.digest && p.digest === gate.plan_digest_sha256);
    return match ? match.path : null;
  }

  function fillPlanSelect(select, plans) {
    replaceChildren(select, plans.length ? plans.map((p) => el('option', {
      value: p.path,
      text: `${p.name}  ·  ${p.season || '?'}  ·  ${shortDigest(p.digest)}`,
    })) : [el('option', { value: '', text: '（runs/plans 下没有可用 plan）' })]);
    select.disabled = !plans.length;
  }

  // The calibration selector and the Matrix start selector always describe the same plan.
  function syncPlanSelects(path) {
    if (!path) return;
    for (const id of ['sel-plan', 'sel-calib-plan']) {
      const select = $(id);
      if (select.value === path) continue;
      if (Array.from(select.options).some((o) => o.value === path)) select.value = path;
    }
  }

  function renderCalibration(state, d) {
    const controls = state.controls || {};
    const gate = d.calibration;
    const plans = state.options && Array.isArray(state.options.plans) ? state.options.plans : [];
    const signature = plans.map((p) => p.path + '|' + p.modified_at).join(';');
    if (signature !== app.calibPlansSignature) {
      app.calibPlansSignature = signature;
      const select = $('sel-calib-plan');
      const previous = select.value || $('sel-plan').value;
      fillPlanSelect(select, plans);
      const wanted = plans.some((p) => p.path === previous) ? previous : preferredPlanPath(state, plans);
      if (wanted) select.value = wanted;
    }
    const plan = selectedCalibPlan();
    setText('calib-plan-meta', plan ? `${plan.plan_id || '--'} · ${plan.season || '?'} · digest ${shortDigest(plan.digest)} · 修改于 ${fmtTime(plan.modified_at)}` : '--');

    let chipCls = 'chip-neutral';
    let chipText = '无校准 receipt';
    if (gate) {
      const meta = CALIBRATION_STATUS[gate.status] || { label: gate.status || '未知', chip: 'chip-neutral' };
      chipCls = meta.chip;
      chipText = `${meta.label} · ${d.calibResults.length}/${d.calibTasks.length} task`;
      if (gate.status === 'running' && !d.calibrating) {
        chipCls = 'chip-amber';
        chipText = `未闭合 · ${d.calibResults.length}/${d.calibTasks.length} task`;
      }
    }
    setChip($('calib-chip'), chipCls, chipText);

    const gs = gateStatus(state, plan);
    const banner = $('calib-banner');
    const bannerCls = { green: 'banner-green', cyan: 'banner-cyan', amber: 'banner-amber', red: 'banner-red' }[gs.level] || '';
    const bannerIcon = { green: 'i-check', cyan: 'i-loader', amber: 'i-alert-triangle', red: 'i-alert-octagon' }[gs.level] || 'i-info';
    const bannerClass = ('banner ' + bannerCls).trim();
    if (banner.className !== bannerClass) banner.className = bannerClass;
    const iconNode = $('calib-banner-icon');
    if (iconNode.getAttribute('href') !== '#' + bannerIcon) iconNode.setAttribute('href', '#' + bannerIcon);
    setText('calib-banner-text', (gs.ok ? 'Matrix 启动已解锁：' : 'Matrix 启动已锁定：') + gs.reason);
    if (banner.hidden) banner.hidden = false;

    let hint;
    if (d.calibrating) hint = `校准正在串行执行（${gate && gate.profile ? gate.profile : CALIBRATION_PROFILE}，Harbor）。如需停止，请在「操作」中「中断」；receipt 将标记为 interrupted。`;
    else if (d.active) hint = `runner 正在执行「${OPERATION_LABEL[d.runner.operation] || d.runner.operation || '其他操作'}」，校准不可用。`;
    else if (d.canonical) hint = '本季已存在 canonical Matrix，校准已冻结；以下为历史门禁 receipt，仅供追溯。';
    else if (!plans.length) hint = 'runs/plans 下没有可用 plan，无法校准。';
    else if (controls.can_calibrate === true) {
      hint = gate && gate.status === 'passed'
        ? '门禁已有通过的 receipt。再次校准会用新的 receipt 替换门禁指针（需二次确认）。'
        : '选择 plan 后点击「启动校准」（需二次确认）。校准通过后，只有同一 plan 才能启动 Matrix。';
    } else hint = '当前不允许校准。';
    setText('calib-hint', hint);

    setText('cb-id', gate ? gate.calibration_id : '--');
    const gatePlan = gate && typeof gate.plan === 'string' ? gate.plan : null;
    updatePathCell('cb-plan', gatePlan, gatePlan ? baseName(gatePlan) : null);
    let digestText = '--';
    if (gate) {
      digestText = shortDigest(gate.plan_digest_sha256);
      if (plan && plan.digest) digestText += plan.digest === gate.plan_digest_sha256 ? ' · 与所选 plan 一致' : ' · 与所选 plan 不一致';
    }
    setText('cb-digest', digestText);
    setText('cb-profile', gate ? `${gate.profile || '--'} / ${gate.backend || '--'}${gate.canonical === false ? ' · 非 canonical' : ''}` : '--');

    const watchdogNode = $('cb-watchdog');
    let wdCls = null;
    let wdText = '--';
    if (gate && gate.watchdog && typeof gate.watchdog === 'object') {
      if (gate.watchdog.passed === true) {
        wdCls = 'chip-green';
        const code = gate.watchdog.exit_code;
        wdText = `已通过 · 进程组可被 SIGTERM 抢占${code === undefined || code === null ? '' : '（exit ' + code + '）'}`;
      } else {
        wdCls = 'chip-red';
        wdText = `未通过：${gate.watchdog.reason || '原因未知'}`;
      }
    } else if (gate) {
      wdCls = 'chip-amber';
      wdText = '未记录';
    }
    const wdKey = (wdCls || '') + '|' + wdText;
    if (watchdogNode.dataset.rendered !== wdKey) {
      replaceChildren(watchdogNode, wdCls ? el('span', { class: 'chip ' + wdCls, text: wdText }) : '--');
      watchdogNode.dataset.rendered = wdKey;
    }

    let finished = '--';
    if (gate && gate.completed_at) finished = fmtTime(gate.completed_at);
    else if (gate && gate.status === 'running') finished = d.calibrating ? '运行中 · 已运行 ' + fmtDuration(gate.started_at) : '未闭合';
    setText('cb-times', gate ? `${fmtTime(gate.started_at)} / ${finished}` : '--');
    updatePathCell('cb-receipt', gate && gate.path ? gate.path : null, gate && gate.path ? `${parentName(gate.path)}/${baseName(gate.path)}` : null);

    const tableKey = JSON.stringify([gate ? gate.calibration_id : null, gate ? gate.status : null, d.calibResults.length, d.calibrating, d.calibNext, d.calibTasks]);
    if (tableKey !== app.calibTableKey) {
      app.calibTableKey = tableKey;
      replaceChildren($('calib-body'), d.calibTasks.map((task) => calibrationRow(task, d)));
    }
  }

  function calibrationRow(task, d) {
    const result = d.calibResults.find((r) => r.task === task) || null;
    let rowState;
    if (result) rowState = result.status === 'passed' ? 'passed' : 'failed';
    else if (!d.calibration) rowState = 'pending';
    else if (d.calibration.status === 'running') rowState = d.calibrating ? (d.calibNext === task ? 'running' : 'pending') : 'stale';
    else rowState = 'skipped';
    const meta = CALIB_ROW[rowState];
    const order = CALIBRATION_TASKS.indexOf(task);

    const statusChip = el('span', { class: 'chip ' + meta.chip }, [svgIcon(meta.icon, meta.spin ? 'icon-spin' : null), meta.label]);

    let checksCell;
    if (result) {
      const checks = result.checks && typeof result.checks === 'object' ? result.checks : {};
      const items = CALIBRATION_CHECKS.map((c) => {
        const ok = checks[c.key] === true;
        return el('span', { class: 'chk ' + (ok ? 'chk-ok' : 'chk-fail'), title: `${c.key}：${ok ? '通过' : '未通过'}\n${c.title}` }, [svgIcon(ok ? 'i-check' : 'i-x'), c.label]);
      });
      for (const key of Object.keys(checks)) {
        if (CALIBRATION_CHECKS.some((c) => c.key === key)) continue;
        const ok = checks[key] === true;
        items.push(el('span', { class: 'chk ' + (ok ? 'chk-ok' : 'chk-fail'), title: key }, [svgIcon(ok ? 'i-check' : 'i-x'), key]));
      }
      const okCount = items.filter((n) => n.classList.contains('chk-ok')).length;
      checksCell = el('div', { class: 'chk-list', 'aria-label': `${okCount}/${items.length} 项检查通过` }, items);
    } else {
      checksCell = document.createTextNode('--');
    }

    let scoreCell;
    if (result) {
      const ev = result.evaluator && typeof result.evaluator === 'object' ? result.evaluator : {};
      const bl = result.baseline && typeof result.baseline === 'object' ? result.baseline : {};
      const below = !!(result.checks && result.checks.evaluator_not_below_baseline === false);
      const required = bl.required_passed_checks === undefined || bl.required_passed_checks === null ? '?' : bl.required_passed_checks;
      const kind = BASELINE_KIND[bl.kind] || bl.kind || '未知基线';
      const title = [
        `baseline kind: ${bl.kind || '--'}`,
        bl.reference ? `reference: ${bl.reference}` : null,
        bl.passed_checks !== undefined ? `baseline ${bl.passed_checks}/${bl.total_checks}` : null,
        `evaluator trusted: ${ev.trusted === true ? 'yes' : 'no'} · passed: ${ev.passed === true ? 'yes' : 'no'}`,
      ].filter(Boolean).join('\n');
      const fmt = (v) => (v === undefined || v === null ? '--' : String(v));
      scoreCell = el('div', { class: 'score' + (below ? ' is-below' : ''), title }, [
        el('span', { class: 'score-main', text: `${fmt(ev.passed_checks)}/${fmt(ev.total_checks)}` }),
        el('span', { class: 'score-baseline', text: ` vs ≥${required} · ${kind}` }),
        ev.trusted === true ? null : el('span', { class: 'score-flag', text: ' · 未 trusted' }),
      ]);
    } else {
      scoreCell = document.createTextNode('--');
    }

    let artifactCell;
    if (result) {
      const run = typeof result.run === 'string' ? result.run.replace(/\/+$/, '') : null;
      const files = [
        { label: 'manifest', path: result.manifest || (run ? run + '/manifest.json' : null), kind: 'candidate manifest' },
        { label: 'events', path: result.trace || (run ? run + '/events.jsonl' : null), kind: 'candidate 事件流' },
        { label: 'stderr', path: run ? run + '/stderr.log' : null, kind: 'candidate stderr' },
        { label: 'report', path: result.evaluation || null, kind: 'evaluation 报告' },
      ];
      artifactCell = el('div', { class: 'calib-artifacts' }, files.map((f) => {
        const btn = el('button', {
          type: 'button',
          class: 'btn btn-sm',
          disabled: !f.path,
          title: f.path ? `查看 ${f.kind}：${f.path}` : `${f.kind} 尚未生成`,
          'aria-label': f.path ? `查看 ${task} 的 ${f.kind}` : `${task} 的 ${f.kind} 尚未生成`,
        }, [svgIcon('i-file-text'), f.label]);
        if (f.path) btn.addEventListener('click', () => openFile(f.path));
        return btn;
      }));
    } else {
      artifactCell = document.createTextNode('--');
    }

    return el('tr', { class: 'calib-row is-' + rowState, 'data-task': task }, [
      el('td', { class: 'task mono', 'data-label': 'task' }, [el('span', { class: 'task-order', text: (order >= 0 ? order + 1 : '+') + '. ' }), task]),
      el('td', { 'data-label': '状态' }, statusChip),
      el('td', { 'data-label': '检查' }, checksCell),
      el('td', { 'data-label': 'evaluator' }, scoreCell),
      el('td', { 'data-label': 'artifact' }, artifactCell),
    ]);
  }

  function openCalibrateDialog() {
    const plan = selectedCalibPlan();
    if (!plan) {
      notify('warn', '请先选择校准 plan。');
      return;
    }
    const gate = app.state && app.state.calibration && typeof app.state.calibration === 'object' ? app.state.calibration : null;
    setText('dlg-calib-plan', plan.path);
    setText('dlg-calib-digest', plan.digest || '--');
    setText('dlg-calib-season', `${plan.season || '--'}${plan.season && plan.season !== CALIBRATION_SEASON ? `（与校准配置 ${CALIBRATION_SEASON} 不一致，服务端会拒绝）` : ''}`);
    setText('dlg-calib-tasks', CALIBRATION_TASKS.join(' → '));
    setText('dlg-calib-profile', CALIBRATION_PROFILE);
    setText('dlg-calib-backend', 'harbor');
    if (gate) {
      const meta = CALIBRATION_STATUS[gate.status] || { label: gate.status || '未知' };
      const same = !!(plan.digest && plan.digest === gate.plan_digest_sha256);
      setText('dlg-calib-current', `${gate.calibration_id || '--'} · ${meta.label} · digest ${shortDigest(gate.plan_digest_sha256)}${same ? '（同一 plan）' : '（不同 plan）'} → 将被替换`);
    } else {
      setText('dlg-calib-current', '无（首次校准）');
    }
    const ack = $('dlg-calib-ack');
    ack.checked = false;
    $('dlg-calibrate-confirm').disabled = true;
    app.lastFocus = document.activeElement;
    $('dlg-calibrate').showModal();
    ack.focus();
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
    setText('drawer-sub', `task ${cell.task} · profile ${cell.profile}${info && info.model ? ' · ' + info.model : ''}${info && info.harness ? ' · ' + info.harness : ''} · attempt ${cell.attempt || 1}`);

    const statusLine = $('drawer-status');
    const noteText = meta.terminal
      ? '终态：candidate/evidence 失败由 Matrix 记录为最终结果，不会重试。'
      : meta.resumable
        ? '可恢复：resume 时会重新执行此 cell。'
        : cell.status === 'running'
          ? (cell.phase === 'evaluating' ? '正在评估（evaluating）。' : 'candidate 正在 Harbor 中执行。')
          : cell.status === 'completed'
            ? 'trusted 结果已记录。'
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
      ['status', `${cell.status}${cell.phase ? ' · phase ' + cell.phase : ''}`],
      ['passed / trusted', `${yesNo(cell.passed)} / ${yesNo(cell.trusted)}`],
      ['playable', yesNo(cell.playable)],
      ['开始', fmtTime(cell.started_at)],
      ['完成', cell.completed_at ? fmtTime(cell.completed_at) : (cell.status === 'running' ? '运行中' : '--')],
      ['耗时', cell.started_at ? fmtDuration(cell.started_at, cell.completed_at || (cell.status === 'running' ? null : cell.started_at)) : '--'],
    ];
    const kvNode = $('drawer-kv');
    const kvKey = JSON.stringify(kv) + '|' + (cell.run || '') + '|' + (cell.evaluation || '');
    if (kvNode.dataset.rendered !== kvKey) {
      const items = [];
      for (const [k, v] of kv) { items.push(el('dt', { text: k })); items.push(el('dd', { class: 'mono', text: v })); }
      items.push(el('dt', { text: 'run 目录' }));
      items.push(el('dd', { class: 'mono' }, cell.run ? cell.run : '--'));
      items.push(el('dt', { text: 'evaluation' }));
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

    const files = $('drawer-files');
    const fileKey = (cell.run || '') + '|' + (cell.evaluation || '');
    if (files.dataset.rendered !== fileKey) {
      if (!cell.run) {
        replaceChildren(files, el('p', { class: 'file-list-empty', text: '此 cell 尚未产生 run 目录。' }));
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
        content.textContent = `无法读取：${payload && payload.detail ? payload.detail : 'HTTP ' + response.status}\n\n文件可能尚不存在（例如尚未进入该阶段），或不在 runs 目录内。`;
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
      logActivity('ok', successText + (result && result.command ? `（command: ${baseName(result.command)}）` : ''));
      notify('ok', successText);
      if (action === 'pause') app.pauseRequestedAt = new Date().toISOString();
      await fetchState().catch(() => {});
    } catch (error) {
      const message = error && error.message ? error.message : String(error);
      logActivity('error', `${action} 失败：${message}`);
      notify('error', `${action} 被拒绝：${message}`, true);
    } finally {
      setBusy(action, false);
    }
  }

  function openStartDialog() {
    const plan = selectedPlan();
    const smoke = selectedSmoke();
    if (!plan || !smoke) {
      notify('warn', '请先选择 plan 与 smoke receipt。');
      return;
    }
    const gs = gateStatus(app.state, plan);
    if (!gs.ok) {
      notify('warn', '启动已锁定：' + gs.reason, true);
      return;
    }
    const gate = app.state.calibration;
    setText('dlg-start-plan', plan.path);
    setText('dlg-start-digest', plan.digest || '--');
    setText('dlg-start-smoke', smoke.path);
    setText('dlg-start-smoke-status', `${smoke.status || '--'} · backend ${smoke.backend || '--'} · plan digest ${shortDigest(smoke.plan_digest)}${smoke.plan_digest && plan.digest && smoke.plan_digest !== plan.digest ? '（与 plan 不一致）' : ''}`);
    setText('dlg-start-gate', `${gate.calibration_id || '--'} · ${(CALIBRATION_STATUS[gate.status] || { label: gate.status }).label} · digest ${shortDigest(gate.plan_digest_sha256)} · 与 plan 一致`);
    setText('dlg-start-backend', 'harbor');
    app.lastFocus = document.activeElement;
    $('dlg-start').showModal();
    $('dlg-start-confirm').focus();
  }

  function openInterruptDialog() {
    if (!app.state) return;
    const d = derive(app.state);
    setText('dlg-int-op', d.runner.operation ? `${OPERATION_LABEL[d.runner.operation] || d.runner.operation} (${d.runner.operation})` : '--');
    setText('dlg-int-pid', d.runner.pid ? `${d.runner.pid} / ${d.runner.pgid || '--'}` : '--');
    setText('dlg-int-task', d.currentTask || '--');
    replaceChildren($('dlg-int-text'), d.calibrating
      ? ['将向校准进程组发送 SIGINT。校准 receipt 会被标记为 ', el('strong', { text: 'interrupted' }), '，门禁不会通过；之后需要重新运行完整的 3-task 校准。「暂停」不适用于校准。']
      : ['将向 runner 进程组发送 SIGINT。正在执行的 candidate 会被标记为 ', el('strong', { text: 'interrupted' }), '，之后可通过「继续」恢复。若只想在当前 task 完成后停止，请改用「暂停」。']);
    const ack = $('dlg-int-ack');
    ack.checked = false;
    $('dlg-interrupt-confirm').disabled = true;
    app.lastFocus = document.activeElement;
    $('dlg-interrupt').showModal();
    ack.focus();
  }

  function restoreFocus() {
    const target = app.lastFocus;
    if (target && typeof target.focus === 'function' && document.contains(target)) target.focus();
  }

  // ------------------------------------------------------------------
  // Wiring
  // ------------------------------------------------------------------

  function wire() {
    $('btn-start').addEventListener('click', openStartDialog);
    $('btn-pause').addEventListener('click', () => runAction('pause', null, '已请求 pause：runner 将在下一个 task barrier 停止。'));
    $('btn-interrupt').addEventListener('click', openInterruptDialog);
    $('btn-resume').addEventListener('click', () => runAction('resume', null, '已请求 resume：runner 正在从 canonical receipt 恢复。'));
    $('btn-refresh').addEventListener('click', () => {
      const btn = $('btn-refresh');
      btn.classList.add('is-busy');
      fetchState().then(() => notify('info', '状态已刷新。')).catch((error) => notify('error', '刷新失败：' + error.message, true)).finally(() => btn.classList.remove('is-busy'));
    });
    $('notice-close').addEventListener('click', () => { $('notice').hidden = true; });

    const onPlanChange = (sourceId) => {
      syncPlanSelects($(sourceId).value);
      pickMatchingSmoke();
      if (app.state) applyState(app.state); else renderStartMeta();
    };
    $('sel-plan').addEventListener('change', () => onPlanChange('sel-plan'));
    $('sel-calib-plan').addEventListener('change', () => onPlanChange('sel-calib-plan'));
    $('sel-smoke').addEventListener('change', renderStartMeta);
    $('start-form').addEventListener('submit', (event) => { event.preventDefault(); openStartDialog(); });
    $('calib-form').addEventListener('submit', (event) => {
      event.preventDefault();
      if (!$('btn-calibrate').disabled) openCalibrateDialog();
    });

    $('dlg-calib-ack').addEventListener('change', (event) => { $('dlg-calibrate-confirm').disabled = !event.target.checked; });
    $('dlg-calibrate-confirm').addEventListener('click', () => {
      const plan = selectedCalibPlan();
      $('dlg-calibrate').close();
      if (!plan) return;
      runAction('calibrate', { plan: plan.path, backend: 'harbor' }, `已提交校准请求：${baseName(plan.path)}（${CALIBRATION_PROFILE} × ${CALIBRATION_TASKS.length} task，harbor，非 canonical）。`);
    });

    $('dlg-start-confirm').addEventListener('click', () => {
      const plan = selectedPlan();
      const smoke = selectedSmoke();
      $('dlg-start').close();
      if (!plan || !smoke) return;
      runAction('start', { plan: plan.path, smoke_receipt: smoke.path, backend: 'harbor' }, `已提交启动请求：${baseName(plan.path)} + ${parentName(smoke.path)}（harbor）。`);
    });
    $('dlg-int-ack').addEventListener('change', (event) => { $('dlg-interrupt-confirm').disabled = !event.target.checked; });
    $('dlg-interrupt-confirm').addEventListener('click', () => {
      $('dlg-interrupt').close();
      runAction('interrupt', null, '已向 runner 进程组发送 SIGINT。');
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
      notify('warn', '未注入控制 token，操作请求会被服务端拒绝。请通过 `web3dgamebench control` 提供的地址访问。', true);
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
