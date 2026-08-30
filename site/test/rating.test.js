import assert from 'node:assert/strict';
import test from 'node:test';

// Keep this small JS mirror as a deployment-independent contract check.
function fit(ids, votes) {
  const wins = Object.fromEntries(ids.map((id) => [id, 0]));
  const strength = Object.fromEntries(ids.map((id) => [id, 1]));
  for (const vote of votes) {
    if (vote.choice === 'left') wins[vote.left_id] += 1;
    if (vote.choice === 'right') wins[vote.right_id] += 1;
  }
  for (let iteration = 0; iteration < 40; iteration += 1) {
    for (const id of ids) {
      let denominator = 0;
      for (const vote of votes) {
        const opponent = vote.left_id === id ? vote.right_id : vote.right_id === id ? vote.left_id : null;
        if (opponent) denominator += 1 / (strength[id] + strength[opponent]);
      }
      if (denominator) strength[id] = Math.max(wins[id], 0.05) / denominator;
    }
  }
  return strength;
}

test('repeated wins rank the winner above the loser', () => {
  const strength = fit(['a', 'b'], Array.from({ length: 8 }, () => ({ left_id: 'a', right_id: 'b', choice: 'left' })));
  assert.ok(strength.a > strength.b);
});
