import { randomUUID } from "node:crypto";

const TERMINAL = new Set([
	"complete",
	"blocked",
	"paused",
	"usage_limited",
	"budget_limited",
	"cleared",
]);

export default function benchmarkGoalRunner(pi: any) {
	pi.registerCommand("benchmark-goal", {
		description: "Run one managed pi-goal lifecycle and wait for its terminal state",
		handler: async (objective: string) => {
			const runId = `web3dgamebench-${randomUUID()}`;
			await new Promise<void>((resolve, reject) => {
				pi.events.on(`pi-goal:event:${runId}`, (event: any) => {
					if (!event || event.runId !== runId) return;
					if (event.type === "error") {
						reject(new Error(`${event.error?.code}: ${event.error?.message}`));
						return;
					}
					if (event.type !== "state" || !TERMINAL.has(event.status)) return;
					if (event.status === "complete") resolve();
					else reject(new Error(`managed Goal ended with ${event.status}: ${event.reason ?? ""}`));
				});
				pi.events.emit("pi-goal:start", { runId, objective });
			});
		},
	});
}
