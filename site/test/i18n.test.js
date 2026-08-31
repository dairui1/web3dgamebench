import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { formatMessage, messages } from '../public/i18n.js';

test('English and Chinese cover the same interface messages', () => {
  assert.deepEqual(Object.keys(messages.zh).sort(), Object.keys(messages.en).sort());
  assert.equal(formatMessage('zh', 'playableBuilds', { count: 6 }), '6 个可玩版本');
  assert.equal(formatMessage('en', 'gameProgress', { game: 'Game B', step: 2 }), 'Game B · 2 of 2');
});

test('published tasks include bilingual evaluation guidance', async () => {
  const catalog = JSON.parse(await readFile(new URL('../public/data/catalog.json', import.meta.url), 'utf8'));
  for (const task of catalog.tasks) {
    assert.ok(task.titleZh);
    assert.ok(task.summaryZh);
    assert.ok(task.genreZh);
    assert.ok(task.evaluation.objectiveZh);
    assert.ok(task.evaluation.controlsZh);
    assert.ok(task.evaluation.checklist.length >= 3);
    assert.ok(task.evaluation.checklist.every((item) => item.text && item.textZh));
  }
});
