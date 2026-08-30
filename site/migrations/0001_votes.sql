CREATE TABLE IF NOT EXISTS votes (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  session_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  left_id TEXT NOT NULL,
  right_id TEXT NOT NULL,
  choice TEXT NOT NULL CHECK(choice IN ('left', 'right', 'tie', 'broken_left', 'broken_right')),
  comment TEXT NOT NULL DEFAULT '',
  user_agent_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS votes_task_created ON votes(task_id, created_at);
CREATE INDEX IF NOT EXISTS votes_session_pair ON votes(session_id, task_id, left_id, right_id);
