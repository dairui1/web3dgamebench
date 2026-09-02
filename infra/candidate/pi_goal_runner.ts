import { randomUUID } from "node:crypto";

const BRIDGE_VERSION = "web3dgamebench-pi-goal-bridge-v1";
const EVIDENCE_SCHEMA_VERSION = 4;
const TERMINAL = new Set([
	"complete",
	"blocked",
	"paused",
	"usage_limited",
	"budget_limited",
	"cleared",
]);

export default function benchmarkGoalRunner(pi: any) {
	if (process.env.WEB3DGAMEBENCH_PI_ADAPTER_VERSION !== BRIDGE_VERSION) {
		throw new Error("frozen Pi Goal bridge version mismatch");
	}
	if (
		process.env.WEB3DGAMEBENCH_RUNTIME_EVIDENCE_SCHEMA_VERSION !==
		String(EVIDENCE_SCHEMA_VERSION)
	) {
		throw new Error("frozen runtime evidence schema mismatch");
	}

	pi.registerCommand("benchmark-goal", {
		description: "Run upstream pi-goal non-interactively and wait for its terminal state",
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

					const status = event.status === "complete" ? "complete" : "blocked";
					pi.appendEntry("web3dgamebench-lifecycle", {
						schema_version: EVIDENCE_SCHEMA_VERSION,
						status,
						source: "upstream-pi-goal-bridge",
						bridge_version: BRIDGE_VERSION,
						upstream_status: event.status,
						reason: event.reason ?? null,
					});
					if (status === "complete") resolve();
					else reject(new Error(`managed Goal ended with ${event.status}: ${event.reason ?? ""}`));
				});
				pi.events.emit("pi-goal:start", { runId, objective });
			});
		},
	});
}
