import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { findEventIndex, formatTraceTime } from '../public/replay.js';

test('trace time formatting handles long runs', () => {
  assert.equal(formatTraceTime(0), '0:00');
  assert.equal(formatTraceTime(65), '1:05');
  assert.equal(formatTraceTime(3964), '1:06:04');
});

test('scrubbing selects the latest event at the requested time', () => {
  const events = [{ atSeconds: 0 }, { atSeconds: 10 }, { atSeconds: 42 }];
  assert.equal(findEventIndex(events, 0), 0);
  assert.equal(findEventIndex(events, 41), 1);
  assert.equal(findEventIndex(events, 99), 2);
});

test('published replay files have the timeline contract', async () => {
  const catalog = JSON.parse(await readFile(new URL('../public/data/catalog.json', import.meta.url), 'utf8'));
  for (const task of catalog.tasks) {
    for (const submission of task.submissions) {
      if (!submission.traceId) continue;
      const replay = JSON.parse(await readFile(new URL(`../public/data/traces/${submission.traceId}.json`, import.meta.url), 'utf8'));
      assert.equal(replay.id, submission.traceId);
      assert.ok(replay.events.length > 0);
      assert.ok(replay.events.every((event) => Number.isFinite(event.atSeconds)));
      assert.ok(replay.events.every((event) => event.atSeconds <= replay.durationSeconds));
    }
  }
});
