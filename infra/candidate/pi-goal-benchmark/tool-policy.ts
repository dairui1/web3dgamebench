import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export const GOAL_COMPLETE_TOOL = "benchmark_complete";
export const GOAL_BLOCKED_TOOL = "benchmark_blocked";
export const GOAL_WAIT_TOOL = "benchmark_wait";
export const GOAL_TOOL_NAMES = [GOAL_COMPLETE_TOOL, GOAL_BLOCKED_TOOL] as const;
const REQUIRED_GOAL_TOOL_NAMES = [GOAL_COMPLETE_TOOL, GOAL_BLOCKED_TOOL] as const;

export function goalToolsAvailable(pi: Pick<ExtensionAPI, "getActiveTools">) {
	const active = new Set(pi.getActiveTools());
	return REQUIRED_GOAL_TOOL_NAMES.every((name) => active.has(name));
}

export function assertGoalToolsAvailable(pi: Pick<ExtensionAPI, "getActiveTools">) {
	if (goalToolsAvailable(pi)) return;
	throw new Error(
		"benchmark_complete and benchmark_blocked are unavailable from the frozen benchmark tool allowlist.",
	);
}
