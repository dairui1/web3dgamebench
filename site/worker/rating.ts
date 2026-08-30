export type Preference = { left_id: string; right_id: string; choice: string };

export type RatingRow = {
  submissionId: string;
  rating: number;
  comparisons: number;
  wins: number;
  losses: number;
  ties: number;
};

export function bradleyTerry(ids: string[], votes: Preference[]): RatingRow[] {
  const active = new Set(ids);
  const usable = votes.filter(
    (vote) =>
      active.has(vote.left_id) &&
      active.has(vote.right_id) &&
      vote.left_id !== vote.right_id &&
      ['left', 'right', 'tie'].includes(vote.choice),
  );
  const strength = Object.fromEntries(ids.map((id) => [id, 1]));
  const wins = Object.fromEntries(ids.map((id) => [id, 0]));
  const comparisons = Object.fromEntries(ids.map((id) => [id, 0]));
  const losses = Object.fromEntries(ids.map((id) => [id, 0]));
  const ties = Object.fromEntries(ids.map((id) => [id, 0]));

  for (const vote of usable) {
    comparisons[vote.left_id] += 1;
    comparisons[vote.right_id] += 1;
    if (vote.choice === 'left') {
      wins[vote.left_id] += 1;
      losses[vote.right_id] += 1;
    } else if (vote.choice === 'right') {
      wins[vote.right_id] += 1;
      losses[vote.left_id] += 1;
    } else {
      wins[vote.left_id] += 0.5;
      wins[vote.right_id] += 0.5;
      ties[vote.left_id] += 1;
      ties[vote.right_id] += 1;
    }
  }

  for (let iteration = 0; iteration < 80; iteration += 1) {
    const next: Record<string, number> = {};
    for (const id of ids) {
      let denominator = 0;
      for (const vote of usable) {
        if (vote.left_id === id) {
          denominator += 1 / Math.max(strength[id] + strength[vote.right_id], 1e-9);
        } else if (vote.right_id === id) {
          denominator += 1 / Math.max(strength[id] + strength[vote.left_id], 1e-9);
        }
      }
      next[id] = denominator > 0 ? Math.max(wins[id], 0.05) / denominator : 1;
    }
    const logMean = ids.reduce((sum, id) => sum + Math.log(Math.max(next[id], 1e-9)), 0) / Math.max(ids.length, 1);
    for (const id of ids) strength[id] = next[id] / Math.exp(logMean);
  }

  return ids
    .map((id) => ({
      submissionId: id,
      rating: Math.round(1500 + 400 * Math.log(Math.max(strength[id], 1e-9))),
      comparisons: comparisons[id],
      wins: wins[id] - ties[id] * 0.5,
      losses: losses[id],
      ties: ties[id],
    }))
    .sort((a, b) => b.rating - a.rating || b.comparisons - a.comparisons);
}
