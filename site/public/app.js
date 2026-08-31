import { formatMessage } from './i18n.js';
import { createReplayViewer, formatTraceTime } from './replay.js';

const views = [...document.querySelectorAll('[data-view]')];
const navLinks = [...document.querySelectorAll('[data-route]')];
const stage = document.querySelector('#game-stage');
const activeGame = document.querySelector('#active-game');
let language = localStorage.getItem('web3dgamebench-language')
  || localStorage.getItem('aetherplay-language')
  || (navigator.language.toLowerCase().startsWith('zh') ? 'zh' : 'en');
let catalogData = null;
let leaderboardData = null;
let currentPair = null;
let played = { left: false, right: false };
let activeSide = null;
let replayMode = false;

const t = (key, values) => formatMessage(language, key, values);
const localized = (object, key) => language === 'zh' && object?.[`${key}Zh`] ? object[`${key}Zh`] : object?.[key] || '';
const replayViewer = createReplayViewer({
  translate: (key, values) => t(key, values),
  onTitle: (title) => { document.title = title; },
});

function applyTranslations() {
  document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en';
  document.querySelector('meta[name="description"]').content = t('pageDescription');
  document.querySelectorAll('[data-i18n]').forEach((element) => { element.textContent = t(element.dataset.i18n); });
  document.querySelectorAll('[data-i18n-title]').forEach((element) => { element.title = t(element.dataset.i18nTitle); });
  document.querySelectorAll('[data-i18n-aria]').forEach((element) => { element.setAttribute('aria-label', t(element.dataset.i18nAria)); });
  document.querySelectorAll('[data-i18n-placeholder]').forEach((element) => { element.placeholder = t(element.dataset.i18nPlaceholder); });
  document.querySelectorAll('[data-language]').forEach((button) => { button.setAttribute('aria-pressed', String(button.dataset.language === language)); });
  if (catalogData) {
    renderCatalog();
    renderTraceIndex();
  }
  if (currentPair) {
    renderArenaTask();
    syncSequence();
  }
  if (leaderboardData) renderLeaderboard();
  if (activeSide) updateStageLabels();
  replayViewer.refreshLanguage();
}

function setLanguage(next) {
  if (!['en', 'zh'].includes(next)) return;
  language = next;
  localStorage.setItem('web3dgamebench-language', language);
  applyTranslations();
}

function route() {
  const replayMatch = location.pathname.match(/^\/replay\/([^/]+)\/?$/);
  const hashRoute = location.hash.replace('#', '');
  const selected = hashRoute || (replayMatch ? 'replay' : 'catalog');
  const valid = views.some((view) => view.dataset.view === selected) ? selected : 'catalog';
  views.forEach((view) => { view.hidden = view.dataset.view !== valid; });
  navLinks.forEach((link) => link.classList.toggle('active', link.dataset.route === (valid === 'replay' ? 'traces' : valid)));
  if (valid !== 'arena') closeStage();
  if (valid !== 'replay') replayViewer.stop();
  if (valid === 'arena') loadPair();
  if (valid === 'leaderboard') loadLeaderboard();
  if (valid === 'replay' && replayMatch) replayViewer.load(decodeURIComponent(replayMatch[1]));
  if (valid !== 'replay') document.title = 'Web3DGameBench';
  scrollTo({ top: 0, behavior: 'instant' });
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || `Request failed: ${response.status}`);
  return response.json();
}

function taskBrief(task, compact = false) {
  const evaluation = task.evaluation || {};
  const checklist = evaluation.checklist || [];
  return `
    <div class="brief-heading">
      <div><span class="brief-kicker">${escapeHtml(localized(task, 'genre'))}</span><h3>${escapeHtml(localized(task, 'title'))}</h3></div>
      <p>${escapeHtml(localized(task, 'summary'))}</p>
    </div>
    <div class="brief-goal"><strong>${t('objective')}</strong><p>${escapeHtml(localized(evaluation, 'objective'))}</p></div>
    ${compact ? '' : `<div class="brief-columns"><div><strong>${t('completionChecklist')}</strong><ul>${checklist.map((item) => `<li>${escapeHtml(localized(item, 'text'))}</li>`).join('')}</ul></div><div><strong>${t('controls')}</strong><p>${escapeHtml(localized(evaluation, 'controls'))}</p></div></div>`}
  `;
}

async function loadCatalog() {
  catalogData = await api('/api/catalog');
  renderCatalog();
  renderTraceIndex();
}

function renderCatalog() {
  const submissions = catalogData.tasks.reduce((sum, task) => sum + task.submissions.length, 0);
  document.querySelector('#season-chip').textContent = catalogData.season.status === 'public-voting' ? t('publicVoting') : catalogData.season.status.replace('-', ' ');
  document.querySelector('#catalog-count').textContent = t('catalogCount', { tasks: catalogData.tasks.length, submissions });
  document.querySelector('#game-grid').innerHTML = catalogData.tasks.map((task, index) => `
    <article class="game-card">
      <div class="meta"><span>${t('task')} ${String(index + 1).padStart(2, '0')}</span><span>${escapeHtml(localized(task, 'genre'))}</span></div>
      <h3>${escapeHtml(localized(task, 'title'))}</h3>
      <p>${escapeHtml(localized(task, 'summary'))}</p>
      <details class="catalog-brief"><summary>${t('evaluationBrief')}</summary>${taskBrief(task, false)}</details>
      ${task.submissions.length ? `<div class="build-list">${task.submissions.map((item) => `<div class="build-row"><div><strong>${escapeHtml(item.model)}</strong><small>${escapeHtml(item.harness)}${item.runStatus === 'timeout' ? ` · ${t('timeoutBuild')}` : ''}</small></div><div class="build-actions">${item.replayUrl ? `<a class="secondary-action" href="${escapeHtml(item.replayUrl)}">${t('replay')}</a>` : ''}<a href="${escapeHtml(item.playUrl)}" target="_blank" rel="noopener">${t('play')}</a></div></div>`).join('')}</div>` : ''}
      <div class="card-foot"><span>${t('playableBuilds', { count: task.submissions.length })}</span><a href="/#arena">${t('compare')} →</a></div>
    </article>
  `).join('');
}

function renderTraceIndex() {
  if (!catalogData) return;
  const root = document.querySelector('#trace-index');
  const tasks = catalogData.tasks.map((task) => {
    const traces = task.submissions.filter((submission) => submission.replayUrl && submission.traceSummary);
    return `
      <section class="trace-index-group">
        <header><div><span>${escapeHtml(localized(task, 'genre'))}</span><h2>${escapeHtml(localized(task, 'title'))}</h2></div><strong>${t('traceRuns', { count: traces.length })}</strong></header>
        <div class="trace-index-list">
          ${traces.map((submission, index) => `
            <a class="trace-index-row" href="${escapeHtml(submission.replayUrl)}">
              <span class="trace-index-number">${String(index + 1).padStart(2, '0')}</span>
              <span class="trace-index-agent"><strong>${escapeHtml(submission.model)}</strong><small>${escapeHtml(submission.harness)}</small></span>
              <span>${t('traceDurationShort', { time: formatTraceTime(submission.traceSummary.durationSeconds) })}</span>
              <span>${t('traceEventsShort', { count: submission.traceSummary.eventCount })}</span>
              <b>${t('replay')} →</b>
            </a>
          `).join('') || `<div class="empty-state">${t('traceNotFound')}</div>`}
        </div>
      </section>
    `;
  });
  root.innerHTML = tasks.join('');
}

async function loadPair(force = false) {
  if (currentPair && !force) return;
  closeStage();
  const empty = document.querySelector('#arena-empty');
  const match = document.querySelector('#arena-match');
  try {
    const pair = await api('/api/arena/pair');
    if (!pair.ready) {
      empty.hidden = false;
      match.hidden = true;
      empty.textContent = t('arenaUnavailable');
      return;
    }
    currentPair = pair;
    played = { left: false, right: false };
    empty.hidden = true;
    match.hidden = false;
    document.querySelector('#vote-comment').value = '';
    renderArenaTask();
    syncSequence();
  } catch (error) {
    empty.hidden = false;
    match.hidden = true;
    empty.textContent = error.message;
  }
}

function renderArenaTask() {
  document.querySelector('#arena-task').textContent = localized(currentPair.task, 'title');
  document.querySelector('#arena-brief').innerHTML = taskBrief(currentPair.task, false);
}

function syncSequence() {
  const complete = played.left && played.right;
  document.querySelector('#sequence-launch').hidden = complete;
  document.querySelector('#vote-review').hidden = !complete;
  const steps = [...document.querySelectorAll('.sequence-steps span')];
  steps[0].classList.toggle('complete', played.left);
  steps[0].classList.toggle('active', !played.left);
  steps[1].classList.toggle('active', played.left && !played.right);
  document.querySelector('#begin-sequence').textContent = played.left ? t('playB') : t('beginSequence');
}

function updateStageLabels() {
  const gameKey = activeSide === 'left' ? 'gameA' : 'gameB';
  const step = activeSide === 'left' ? 1 : 2;
  document.querySelector('#stage-label').textContent = t(gameKey);
  document.querySelector('#stage-progress').textContent = t('gameProgress', { game: t(gameKey), step });
  document.querySelector('#finish-stage').textContent = replayMode ? t('finishReplay') : t(activeSide === 'left' ? 'finishA' : 'finishB');
  activeGame.title = t(gameKey);
}

function playSide(side, replay = false) {
  if (!currentPair || !['left', 'right'].includes(side)) return;
  activeSide = side;
  replayMode = replay;
  updateStageLabels();
  activeGame.src = currentPair[side].playUrl;
  stage.hidden = false;
  document.body.classList.add('stage-open');
}

function closeStage() {
  activeGame.src = 'about:blank';
  stage.hidden = true;
  document.body.classList.remove('stage-open');
  activeSide = null;
  replayMode = false;
}

function finishStage() {
  if (!activeSide) return;
  const finishedSide = activeSide;
  const wasReplay = replayMode;
  played[finishedSide] = true;
  closeStage();
  if (!wasReplay && finishedSide === 'left') {
    syncSequence();
    playSide('right');
    return;
  }
  syncSequence();
  document.querySelector('#vote-review').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

async function submitVote(choice) {
  if (!currentPair || !played.left || !played.right) return;
  const buttons = [...document.querySelectorAll('[data-choice]')];
  buttons.forEach((button) => { button.disabled = true; });
  try {
    await api('/api/votes', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        taskId: currentPair.task.id,
        leftId: currentPair.left.id,
        rightId: currentPair.right.id,
        choice,
        comment: document.querySelector('#vote-comment').value,
      }),
    });
    currentPair = null;
    leaderboardData = null;
    await loadPair(true);
  } catch (error) {
    alert(error.message);
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}

async function loadLeaderboard() {
  const root = document.querySelector('#leaderboard-list');
  root.innerHTML = `<p>${t('loadingRatings')}</p>`;
  try {
    leaderboardData = await api('/api/leaderboard');
    renderLeaderboard();
  } catch (error) {
    root.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
  }
}

function renderLeaderboard() {
  document.querySelector('#leaderboard-list').innerHTML = leaderboardData.tasks.map((task) => `
    <section class="board">
      <div class="board-head"><h2>${escapeHtml(localized(task.task, 'title'))}</h2><span>${t('preferenceVotes', { count: task.votes })}</span></div>
      ${task.ratings.length ? `<table class="board-table"><thead><tr><th>${t('rank')}</th><th>${t('system')}</th><th>${t('rating')}</th><th>${t('comparisons')}</th><th>${t('record')}</th></tr></thead><tbody>${task.ratings.map((row, index) => `<tr><td>${index + 1}</td><td>${escapeHtml(row.submission?.model || row.submissionId)} <small>${escapeHtml(row.submission?.harness || '')}${row.submission?.runStatus === 'timeout' ? ` · ${t('timeoutShort')}` : ''}</small></td><td>${row.rating}</td><td>${row.comparisons}</td><td>${language === 'zh' ? `${row.wins}胜 · ${row.losses}负 · ${row.ties}平` : `${row.wins}W · ${row.losses}L · ${row.ties}T`}</td></tr>`).join('')}</tbody></table>` : `<div class="empty-state">${t('emptyRatings')}</div>`}
    </section>
  `).join('');
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character]);
}

addEventListener('hashchange', route);
addEventListener('keydown', (event) => { if (event.key === 'Escape' && activeSide) closeStage(); });
document.querySelectorAll('[data-language]').forEach((button) => button.addEventListener('click', () => setLanguage(button.dataset.language)));
document.querySelector('#reload-pair').addEventListener('click', () => { currentPair = null; loadPair(true); });
document.querySelector('#begin-sequence').addEventListener('click', () => playSide(played.left ? 'right' : 'left'));
document.querySelector('#finish-stage').addEventListener('click', finishStage);
document.querySelector('#exit-stage').addEventListener('click', closeStage);
document.querySelectorAll('[data-replay]').forEach((button) => button.addEventListener('click', () => playSide(button.dataset.replay, true)));
document.querySelectorAll('[data-choice]').forEach((button) => button.addEventListener('click', () => submitVote(button.dataset.choice)));
applyTranslations();
loadCatalog().catch((error) => { document.querySelector('#game-grid').innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`; });
route();
