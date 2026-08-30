const views = [...document.querySelectorAll('[data-view]')];
const navLinks = [...document.querySelectorAll('[data-route]')];
let currentPair = null;

function route() {
  const selected = location.hash.replace('#', '') || 'catalog';
  const valid = views.some((view) => view.dataset.view === selected) ? selected : 'catalog';
  views.forEach((view) => { view.hidden = view.dataset.view !== valid; });
  navLinks.forEach((link) => link.classList.toggle('active', link.dataset.route === valid));
  if (valid === 'arena') loadPair();
  if (valid === 'leaderboard') loadLeaderboard();
  scrollTo({ top: 0, behavior: 'instant' });
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || `Request failed: ${response.status}`);
  return response.json();
}

async function loadCatalog() {
  const data = await api('/api/catalog');
  document.querySelector('#season-chip').textContent = data.season.status.replace('-', ' ');
  document.querySelector('#catalog-count').textContent = `${data.tasks.length} task · ${data.tasks.reduce((sum, task) => sum + task.submissions.length, 0)} submissions`;
  const grid = document.querySelector('#game-grid');
  grid.innerHTML = data.tasks.map((task, index) => `
    <article class="game-card">
      <div class="meta"><span>Task ${String(index + 1).padStart(2, '0')}</span><span>${escapeHtml(task.genre)}</span></div>
      <h3>${escapeHtml(task.title)}</h3>
      <p>${escapeHtml(task.summary)}</p>
      <div class="card-foot"><span>${task.submissions.length} playable builds</span><a href="#arena">Compare →</a></div>
    </article>
  `).join('');
}

async function loadPair(force = false) {
  if (currentPair && !force) return;
  const empty = document.querySelector('#arena-empty');
  const match = document.querySelector('#arena-match');
  try {
    const pair = await api('/api/arena/pair');
    if (!pair.ready) {
      empty.hidden = false;
      match.hidden = true;
      empty.textContent = pair.reason;
      return;
    }
    currentPair = pair;
    empty.hidden = true;
    match.hidden = false;
    document.querySelector('#arena-task').textContent = pair.task.title;
    document.querySelector('#left-game').src = pair.left.playUrl;
    document.querySelector('#right-game').src = pair.right.playUrl;
    document.querySelector('#vote-comment').value = '';
  } catch (error) {
    empty.hidden = false;
    match.hidden = true;
    empty.textContent = error.message;
  }
}

async function submitVote(choice) {
  if (!currentPair) return;
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
    await loadPair(true);
  } catch (error) {
    alert(error.message);
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}

async function loadLeaderboard() {
  const root = document.querySelector('#leaderboard-list');
  root.innerHTML = '<p>Loading ratings...</p>';
  try {
    const data = await api('/api/leaderboard');
    root.innerHTML = data.tasks.map((task) => `
      <section class="board">
        <div class="board-head"><h2>${escapeHtml(task.task.title)}</h2><span>${task.votes} preference votes</span></div>
        ${task.ratings.length ? `<table class="board-table"><thead><tr><th>Rank</th><th>System</th><th>Rating</th><th>Comparisons</th><th>Record</th></tr></thead><tbody>${task.ratings.map((row, index) => `<tr><td>${index + 1}</td><td>${escapeHtml(row.submission?.model || row.submissionId)} <small>${escapeHtml(row.submission?.harness || '')}</small></td><td>${row.rating}</td><td>${row.comparisons}</td><td>${row.wins}W · ${row.losses}L · ${row.ties}T</td></tr>`).join('')}</tbody></table>` : '<div class="empty-state">Ratings appear after the closed pilot matrix is published and blind play begins.</div>'}
      </section>
    `).join('');
  } catch (error) {
    root.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
  }
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character]);
}

addEventListener('hashchange', route);
document.querySelector('#reload-pair').addEventListener('click', () => { currentPair = null; loadPair(true); });
document.querySelectorAll('[data-choice]').forEach((button) => button.addEventListener('click', () => submitVote(button.dataset.choice)));
loadCatalog().catch((error) => { document.querySelector('#game-grid').innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`; });
route();
