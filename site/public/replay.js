export function formatTraceTime(seconds) {
  const safe = Math.max(0, Number(seconds) || 0);
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const remainder = Math.floor(safe % 60);
  return hours
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
    : `${minutes}:${String(remainder).padStart(2, '0')}`;
}

export function findEventIndex(events, seconds) {
  if (!events.length) return -1;
  let low = 0;
  let high = events.length - 1;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (events[middle].atSeconds <= seconds) low = middle + 1;
    else high = middle - 1;
  }
  return Math.max(0, high);
}

const escapeHtml = (value) => String(value ?? '').replace(
  /[&<>'"]/g,
  (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character],
);

const FILTERS = {
  all: () => true,
  agent: (event) => ['message', 'thought', 'plan'].includes(event.kind),
  tools: (event) => ['tool', 'change'].includes(event.kind),
  errors: (event) => event.status === 'error',
};

export function createReplayViewer({ translate, onTitle }) {
  const player = document.querySelector('#trace-player');
  const loading = document.querySelector('#trace-loading');
  const range = document.querySelector('#trace-range');
  const list = document.querySelector('#trace-event-list');
  const detail = document.querySelector('#trace-detail');
  let data = null;
  let traceId = null;
  let filter = 'all';
  let currentIndex = -1;
  let position = 0;
  let speed = 60;
  let playing = false;
  let frameId = null;
  let previousFrame = null;

  const t = (key, values) => translate(key, values);

  function filteredIndexes() {
    if (!data) return [];
    return data.events
      .map((event, index) => ({ event, index }))
      .filter(({ event }) => FILTERS[filter](event))
      .map(({ index }) => index);
  }

  function stop() {
    playing = false;
    previousFrame = null;
    if (frameId !== null) cancelAnimationFrame(frameId);
    frameId = null;
    const button = document.querySelector('#trace-play');
    button.textContent = '▶';
    button.title = t('tracePlay');
    button.setAttribute('aria-label', t('tracePlay'));
  }

  function tick(now) {
    if (!playing || !data) return;
    if (previousFrame !== null) {
      position = Math.min(data.durationSeconds, position + ((now - previousFrame) / 1000) * speed);
      syncPosition(true);
      if (position >= data.durationSeconds) {
        stop();
        return;
      }
    }
    previousFrame = now;
    frameId = requestAnimationFrame(tick);
  }

  function togglePlay() {
    if (!data) return;
    if (playing) {
      stop();
      return;
    }
    if (position >= data.durationSeconds) position = 0;
    playing = true;
    const button = document.querySelector('#trace-play');
    button.textContent = '▮▮';
    button.title = t('tracePause');
    button.setAttribute('aria-label', t('tracePause'));
    frameId = requestAnimationFrame(tick);
  }

  function renderDetail(index) {
    const event = data?.events[index];
    if (!event) return;
    const output = event.output
      ? `<section><h3>${t('traceOutput')}</h3><pre>${escapeHtml(event.output)}</pre></section>`
      : '';
    detail.innerHTML = `
      <header class="trace-detail-head">
        <div><span class="trace-kind trace-kind-${escapeHtml(event.kind)}">${escapeHtml(t(`traceKind_${event.kind}`))}</span><span class="trace-phase">${escapeHtml(t(`tracePhase_${event.chapter}`))}</span></div>
        <time>${formatTraceTime(event.atSeconds)}</time>
      </header>
      <h2>${escapeHtml(event.title)}</h2>
      ${event.detail ? `<section><h3>${t('traceDetails')}</h3><pre>${escapeHtml(event.detail)}</pre></section>` : ''}
      ${output}
    `;
  }

  function activateRow(index, scroll) {
    list.querySelector('.active')?.classList.remove('active');
    const row = list.querySelector(`[data-event-index="${index}"]`);
    row?.classList.add('active');
    if (scroll && row) {
      const top = row.offsetTop - list.offsetTop;
      const bottom = top + row.offsetHeight;
      if (top < list.scrollTop) list.scrollTop = top;
      else if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight;
    }
  }

  function syncPosition(scroll = false) {
    if (!data) return;
    range.value = String(position);
    document.querySelector('#trace-current-time').textContent = formatTraceTime(position);
    const index = findEventIndex(data.events, position);
    if (index !== currentIndex) {
      currentIndex = index;
      renderDetail(index);
      activateRow(index, scroll);
    }
  }

  function seekEvent(index) {
    if (!data || index < 0 || index >= data.events.length) return;
    position = data.events[index].atSeconds;
    currentIndex = index;
    range.value = String(position);
    document.querySelector('#trace-current-time').textContent = formatTraceTime(position);
    renderDetail(index);
    activateRow(index, true);
  }

  function step(direction) {
    const indexes = filteredIndexes();
    if (!indexes.length) return;
    const current = indexes.findIndex((index) => index >= currentIndex);
    const next = Math.max(0, Math.min(indexes.length - 1, current + direction));
    seekEvent(indexes[next]);
  }

  function renderList() {
    if (!data) return;
    const indexes = filteredIndexes();
    list.innerHTML = indexes.length
      ? indexes.map((index) => {
        const event = data.events[index];
        return `
          <button type="button" class="trace-event-row${index === currentIndex ? ' active' : ''}" data-event-index="${index}">
            <span class="trace-event-time">${formatTraceTime(event.atSeconds)}</span>
            <span class="trace-event-copy"><strong>${escapeHtml(event.title)}</strong><small>${escapeHtml(t(`traceKind_${event.kind}`))} · ${escapeHtml(t(`tracePhase_${event.chapter}`))}</small></span>
            <i class="trace-event-status ${event.status === 'error' ? 'error' : ''}" aria-hidden="true"></i>
          </button>
        `;
      }).join('')
      : `<div class="trace-filter-empty">${t('traceNoEvents')}</div>`;
    list.querySelectorAll('[data-event-index]').forEach((button) => {
      button.addEventListener('click', () => seekEvent(Number(button.dataset.eventIndex)));
    });
  }

  function renderChapters() {
    const root = document.querySelector('#trace-chapters');
    root.innerHTML = data.chapters.map((chapter) => {
      const width = Math.max(0.35, ((chapter.endSeconds - chapter.startSeconds) / data.durationSeconds) * 100);
      return `<button type="button" class="trace-chapter phase-${escapeHtml(chapter.label)}" style="width:${width}%" data-chapter-event="${chapter.startEvent}" title="${escapeHtml(t(`tracePhase_${chapter.label}`))}"><span>${escapeHtml(t(`tracePhase_${chapter.label}`))}</span></button>`;
    }).join('');
    root.querySelectorAll('[data-chapter-event]').forEach((button) => {
      button.addEventListener('click', () => seekEvent(Number(button.dataset.chapterEvent)));
    });
  }

  function renderSummary() {
    const usage = data.summary.usage || {};
    const totalTokens = Number(usage.inputTokens || 0) + Number(usage.outputTokens || 0);
    const checks = data.evaluation?.checks || [];
    const passedChecks = checks.filter((check) => check.passed).length;
    document.querySelector('#trace-title').textContent = data.profile.model;
    document.querySelector('#trace-subtitle').textContent = `${data.task.id} · ${data.profile.harness} · ${data.runId}`;
    document.querySelector('#trace-summary').innerHTML = `
      <div><strong>${formatTraceTime(data.durationSeconds)}</strong><span>${t('traceDuration')}</span></div>
      <div><strong>${data.summary.eventCount}</strong><span>${t('traceEvents')}</span></div>
      <div><strong>${data.summary.toolCalls}</strong><span>${t('traceToolCalls')}</span></div>
      <div><strong>${totalTokens ? totalTokens.toLocaleString() : '—'}</strong><span>${t('traceTokens')}</span></div>
      <div class="${data.summary.errors ? 'has-errors' : ''}"><strong>${data.summary.errors}</strong><span>${t('traceErrors')}</span></div>
      <div class="${data.evaluation?.passed ? 'passed' : 'has-errors'}"><strong>${checks.length ? `${passedChecks}/${checks.length}` : (data.evaluation?.passed ? t('tracePassed') : '—')}</strong><span>${t('traceChecks')}</span></div>
    `;
    range.max = String(data.durationSeconds);
    document.querySelector('#trace-total-time').textContent = formatTraceTime(data.durationSeconds);
    onTitle(`${data.profile.model} · Trace Replay`);
  }

  function renderAll() {
    if (!data) return;
    renderSummary();
    renderChapters();
    renderList();
    renderDetail(Math.max(0, currentIndex));
    document.querySelectorAll('[data-trace-filter]').forEach((button) => {
      button.textContent = t(`traceFilter_${button.dataset.traceFilter}`);
    });
    document.querySelector('#trace-play').title = t(playing ? 'tracePause' : 'tracePlay');
  }

  async function load(id) {
    if (id === traceId && data) return;
    stop();
    traceId = id;
    data = null;
    currentIndex = -1;
    position = 0;
    player.hidden = true;
    loading.hidden = false;
    loading.textContent = t('traceLoading');
    try {
      const response = await fetch(`/data/traces/${encodeURIComponent(id)}.json`);
      const contentType = response.headers.get('content-type') || '';
      if (!response.ok || !contentType.includes('application/json')) {
        throw new Error(response.status === 404 || !contentType.includes('application/json') ? t('traceNotFound') : `Request failed: ${response.status}`);
      }
      data = await response.json();
      renderAll();
      seekEvent(0);
      loading.hidden = true;
      player.hidden = false;
    } catch (error) {
      loading.textContent = error.message;
    }
  }

  document.querySelector('#trace-play').addEventListener('click', togglePlay);
  document.querySelector('#trace-previous').addEventListener('click', () => step(-1));
  document.querySelector('#trace-next').addEventListener('click', () => step(1));
  range.addEventListener('input', () => {
    position = Number(range.value);
    syncPosition(false);
  });
  document.querySelectorAll('[data-trace-speed]').forEach((button) => {
    button.addEventListener('click', () => {
      speed = Number(button.dataset.traceSpeed);
      document.querySelectorAll('[data-trace-speed]').forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
    });
  });
  document.querySelectorAll('[data-trace-filter]').forEach((button) => {
    button.addEventListener('click', () => {
      filter = button.dataset.traceFilter;
      document.querySelectorAll('[data-trace-filter]').forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
      renderList();
    });
  });

  function keyboard(event) {
    if (!data || document.querySelector('[data-view="replay"]')?.hidden) return;
    if (event.target instanceof HTMLInputElement && event.target !== range) return;
    if (event.code === 'Space') {
      event.preventDefault();
      togglePlay();
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault();
      step(-1);
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      step(1);
    } else if (event.key === 'Home') {
      event.preventDefault();
      seekEvent(0);
    } else if (event.key === 'End') {
      event.preventDefault();
      seekEvent(data.events.length - 1);
    }
  }
  addEventListener('keydown', keyboard);

  return {
    load,
    stop,
    refreshLanguage: renderAll,
  };
}
