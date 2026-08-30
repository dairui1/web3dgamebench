import { bradleyTerry, type Preference } from './rating';

interface Env {
  DB: D1Database;
  ASSETS: Fetcher;
}

type Submission = {
  id: string;
  taskId: string;
  profileId: string;
  harness: string;
  model: string;
  playUrl: string;
  status: string;
  runStatus?: string;
};

type Catalog = { tasks: Array<{ id: string; title: string; submissions: Submission[] }> };

const json = (body: unknown, status = 200, headers: HeadersInit = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', ...headers },
  });

async function catalog(env: Env): Promise<Catalog> {
  const response = await env.ASSETS.fetch('https://assets.local/data/catalog.json');
  if (!response.ok) throw new Error('catalog unavailable');
  return response.json<Catalog>();
}

function sessionId(request: Request): { value: string; fresh: boolean } {
  const match = request.headers.get('cookie')?.match(/(?:^|;\s*)ap_session=([a-zA-Z0-9-]+)/);
  return match ? { value: match[1], fresh: false } : { value: crypto.randomUUID(), fresh: true };
}

function cookie(value: string): string {
  return `ap_session=${value}; Path=/; Max-Age=31536000; HttpOnly; Secure; SameSite=Lax`;
}

function originAllowed(request: Request): boolean {
  const origin = request.headers.get('origin');
  if (!origin) return true;
  const url = new URL(origin);
  return url.host === new URL(request.url).host;
}

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function arenaPair(request: Request, env: Env): Promise<Response> {
  const data = await catalog(env);
  const url = new URL(request.url);
  const requestedTask = url.searchParams.get('task');
  const eligible = data.tasks.filter((task) => task.submissions.filter((item) => item.status === 'published').length >= 2);
  const task = eligible.find((item) => item.id === requestedTask) ?? eligible[0];
  if (!task) return json({ ready: false, reason: 'The first complete matrix has not been published yet.' });
  const submissions = task.submissions.filter((item) => item.status === 'published');
  const counts = await env.DB.prepare(
    'SELECT left_id, right_id, COUNT(*) AS count FROM votes WHERE task_id = ? GROUP BY left_id, right_id',
  ).bind(task.id).all<{ left_id: string; right_id: string; count: number }>();
  const countMap = new Map(counts.results.map((row) => [`${row.left_id}:${row.right_id}`, row.count]));
  const pairs: Array<[Submission, Submission, number]> = [];
  for (let i = 0; i < submissions.length; i += 1) {
    for (let j = i + 1; j < submissions.length; j += 1) {
      const [a, b] = Math.random() > 0.5 ? [submissions[i], submissions[j]] : [submissions[j], submissions[i]];
      const count = (countMap.get(`${a.id}:${b.id}`) ?? 0) + (countMap.get(`${b.id}:${a.id}`) ?? 0);
      pairs.push([a, b, count]);
    }
  }
  pairs.sort((a, b) => a[2] - b[2] || Math.random() - 0.5);
  const selected = pairs[0];
  const session = sessionId(request);
  return json(
    { ready: true, task: { id: task.id, title: task.title }, left: blind(selected[0]), right: blind(selected[1]) },
    200,
    session.fresh ? { 'set-cookie': cookie(session.value) } : {},
  );
}

function blind(submission: Submission) {
  return { id: submission.id, playUrl: submission.playUrl };
}

async function vote(request: Request, env: Env): Promise<Response> {
  if (!originAllowed(request)) return json({ error: 'origin rejected' }, 403);
  const body: Record<string, unknown> = await request.json<Record<string, unknown>>().catch(() => ({}));
  const taskId = String(body.taskId ?? '');
  const leftId = String(body.leftId ?? '');
  const rightId = String(body.rightId ?? '');
  const choice = String(body.choice ?? '');
  const comment = String(body.comment ?? '').trim().slice(0, 500);
  if (!['left', 'right', 'tie', 'broken_left', 'broken_right'].includes(choice)) return json({ error: 'invalid choice' }, 400);
  const data = await catalog(env);
  const task = data.tasks.find((item) => item.id === taskId);
  const ids = new Set(task?.submissions.filter((item) => item.status === 'published').map((item) => item.id));
  if (!task || leftId === rightId || !ids.has(leftId) || !ids.has(rightId)) return json({ error: 'invalid pair' }, 400);
  const session = sessionId(request);
  const userAgentHash = await sha256(request.headers.get('user-agent') ?? 'unknown');
  await env.DB.prepare(
    'INSERT INTO votes (id, created_at, session_id, task_id, left_id, right_id, choice, comment, user_agent_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind(crypto.randomUUID(), new Date().toISOString(), session.value, taskId, leftId, rightId, choice, comment, userAgentHash).run();
  return json({ ok: true }, 201, session.fresh ? { 'set-cookie': cookie(session.value) } : {});
}

async function leaderboard(env: Env): Promise<Response> {
  const data = await catalog(env);
  const output = [];
  for (const task of data.tasks) {
    const submissions = task.submissions.filter((item) => item.status === 'published');
    if (!submissions.length) {
      output.push({ task: { id: task.id, title: task.title }, ratings: [], votes: 0 });
      continue;
    }
    const result = await env.DB.prepare(
      "SELECT left_id, right_id, choice FROM votes WHERE task_id = ? AND choice IN ('left', 'right', 'tie')",
    ).bind(task.id).all<Preference>();
    const ratings = bradleyTerry(submissions.map((item) => item.id), result.results).map((rating) => ({
      ...rating,
      submission: submissions.find((item) => item.id === rating.submissionId),
    }));
    output.push({ task: { id: task.id, title: task.title }, ratings, votes: result.results.length });
  }
  return json({ tasks: output });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    try {
      if (request.method === 'GET' && url.pathname === '/api/catalog') return json(await catalog(env));
      if (request.method === 'GET' && url.pathname === '/api/arena/pair') return arenaPair(request, env);
      if (request.method === 'POST' && url.pathname === '/api/votes') return vote(request, env);
      if (request.method === 'GET' && url.pathname === '/api/leaderboard') return leaderboard(env);
      if (url.pathname.startsWith('/api/')) return json({ error: 'not found' }, 404);
      return env.ASSETS.fetch(request);
    } catch (error) {
      return json({ error: error instanceof Error ? error.message : 'unexpected error' }, 500);
    }
  },
};
