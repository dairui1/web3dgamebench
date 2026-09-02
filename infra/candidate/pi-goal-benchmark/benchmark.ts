import { createHash, randomUUID } from "node:crypto";
import { lstatSync, readdirSync, readFileSync, readlinkSync } from "node:fs";
import { join, relative } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { defineTool } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { GoalCommandController } from "./commands.js";
import { registerGoalLifecycle } from "./lifecycle.js";
import { GoalRunController, goalRunEventChannel } from "./run-protocol.js";
import { GoalRuntime, transitionGoal } from "./runtime.js";
import { classifyVerificationCommand, verificationDecision } from "./convergence.js";

const ADAPTER_VERSION = "web3dgamebench-pi-adapter-v3";
const UPSTREAM_VERSION = "0.54.4";
const RUNTIME_EVIDENCE_SCHEMA_VERSION = 3;
const TERMINAL = new Set(["complete", "blocked", "paused", "usage_limited", "budget_limited"]);
const SOURCE_EXCLUDES = new Set([".git", ".screens", "dist", "node_modules"]);

interface BuildEvidence {
	command: string;
	sourceSha256: string;
	distSha256: string;
}

interface EvidenceLedger {
	build?: BuildEvidence;
	attempts: Map<string, number>;
	verificationTimer?: ReturnType<typeof setTimeout>;
	completionPrompted?: boolean;
}

function positiveInteger(name: string, fallback: number): number {
	const value = Number.parseInt(process.env[name] ?? "", 10);
	return Number.isSafeInteger(value) && value > 0 ? value : fallback;
}

function sha256File(path: string): string {
	return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function treeSha256(root: string, excluded = new Set<string>()): string {
	const files: Array<{ path: string; symlink: boolean }> = [];
	const visit = (directory: string) => {
		for (const name of readdirSync(directory).sort()) {
			if (excluded.has(name)) continue;
			const path = join(directory, name);
			const metadata = lstatSync(path);
			if (metadata.isDirectory()) visit(path);
			else if (metadata.isFile() || metadata.isSymbolicLink()) {
				files.push({ path, symlink: metadata.isSymbolicLink() });
			}
		}
	};
	visit(root);
	const digest = createHash("sha256");
	for (const { path, symlink } of files) {
		digest.update(relative(root, path));
		digest.update(symlink ? `symlink:${readlinkSync(path)}` : readFileSync(path));
	}
	return digest.digest("hex");
}

function workspaceRevision() {
	const cwd = process.cwd();
	return {
		sourceSha256: treeSha256(cwd, SOURCE_EXCLUDES),
		distSha256: treeSha256(join(cwd, "dist")),
	};
}

function completionEvidenceReady(ledger: EvidenceLedger): boolean {
	return Boolean(ledger.build);
}

function successfulToolResult(event: { isError?: boolean; details?: unknown }) {
	if (event.isError) return false;
	const details = event.details;
	if (!details || typeof details !== "object") return true;
	const exitCode = (details as { exitCode?: unknown }).exitCode;
	return exitCode === undefined || exitCode === 0;
}

function toolResult(text: string, details: object = {}, terminate = false) {
	return {
		content: [{ type: "text" as const, text }],
		details,
		...(terminate ? { terminate: true as const } : {}),
	};
}

function registerBenchmarkTools(pi: ExtensionAPI, runtime: GoalRuntime, ledger: EvidenceLedger) {
	pi.registerTool(
		defineTool({
			name: "benchmark_complete",
			label: "Benchmark Complete",
			description: "End candidate execution after a successful production build is recorded for the current source revision. This does not claim evaluator success.",
			parameters: Type.Object({
				goal_id: Type.String({ minLength: 1, maxLength: 128 }),
				summary: Type.String({ minLength: 1, maxLength: 4000 }),
				build: Type.Object({ command: Type.String({ minLength: 1 }), success: Type.Boolean() }),
				task_sha256: Type.String({ pattern: "^[a-f0-9]{64}$" }),
			}),
			async execute(_id, params, _signal, _update, ctx) {
				const goal = runtime.activeGoal;
				const reject = (reason: string) => toolResult(`benchmark_complete rejected: ${reason}`);
				if (!goal || goal.status !== "active") return reject("no active benchmark goal");
				if (params.goal_id !== goal.id) return reject("stale goal_id");
				const expectedTask = process.env.WEB3DGAMEBENCH_TASK_SHA256;
				const actualTask = sha256File(join(process.cwd(), "TASK.md"));
				if (!expectedTask || params.task_sha256 !== expectedTask || actualTask !== expectedTask) return reject("TASK.md hash is missing or changed");
				const revision = workspaceRevision();
				const build = ledger.build;
				if (!build || !params.build.success || params.build.command !== build.command) return reject("npm run build is not backed by a successful recorded command");
				if (build.sourceSha256 !== revision.sourceSha256 || build.distSha256 !== revision.distSha256) return reject("source or dist changed after the recorded build");
				if (ledger.verificationTimer) clearTimeout(ledger.verificationTimer);
				runtime.clearGoalWaitTimer();
				runtime.activeGoal = transitionGoal(goal, "complete");
				runtime.setCompletionSummary(goal.id, params.summary);
				runtime.recordGoalUsage(runtime.activeGoal, ctx);
				runtime.persistGoal(runtime.activeGoal);
				runtime.clearCompletedGoal(ctx);
				pi.appendEntry("web3dgamebench-lifecycle", {
					schema_version: RUNTIME_EVIDENCE_SCHEMA_VERSION,
					status: "complete",
					adapter_version: ADAPTER_VERSION,
					evidence: { build: build.command, task_sha256: actualTask, ...revision },
				});
				return toolResult("Operational completion evidence accepted. Submission evaluation remains independent.", { status: "complete" }, true);
			},
		}),
	);

	pi.registerTool(
		defineTool({
			name: "benchmark_blocked",
			label: "Benchmark Blocked",
			description: "End only after the same external blocker has recurred for at least three consecutive turns.",
			parameters: Type.Object({
				goal_id: Type.String({ minLength: 1, maxLength: 128 }),
				reason: Type.String({ minLength: 1, maxLength: 1000 }),
				evidence: Type.String({ minLength: 1, maxLength: 4000 }),
				repeated_turns: Type.Integer({ minimum: 3 }),
			}),
			async execute(_id, params, _signal, _update, ctx) {
				const goal = runtime.activeGoal;
				if (!goal || goal.status !== "active" || params.goal_id !== goal.id) return toolResult("benchmark_blocked rejected: no matching active goal");
				const stopped = runtime.stopActiveGoal(ctx, { kind: "blocker_report", expectedGoalId: goal.id, reason: params.reason });
				if (!stopped) return toolResult("benchmark_blocked rejected: goal changed before transition");
				pi.appendEntry("web3dgamebench-lifecycle", { schema_version: RUNTIME_EVIDENCE_SCHEMA_VERSION, status: "blocked", adapter_version: ADAPTER_VERSION, reason: params.reason, evidence: params.evidence, repeated_turns: params.repeated_turns });
				return toolResult(`Benchmark blocked: ${params.reason}`, { status: "blocked" }, true);
			},
		}),
	);
}

function registerEvidenceLedger(pi: ExtensionAPI, ledger: EvidenceLedger) {
	pi.on("tool_result", (event: any) => {
		if (event.toolName !== "bash" || !successfulToolResult(event)) return;
		const command = typeof event.input?.command === "string" ? event.input.command.trim() : "";
		if (!command) return;
		const includesBuild = /(?:^|[;&|]\s*)npm\s+run\s+build(?:\s|$)/u.test(command);
		if (includesBuild) {
			const revision = workspaceRevision();
			ledger.build = { command, ...revision };
			ledger.completionPrompted = false;
			if (ledger.verificationTimer) clearTimeout(ledger.verificationTimer);
			ledger.verificationTimer = undefined;
		}
		if (completionEvidenceReady(ledger) && !ledger.completionPrompted) {
			ledger.completionPrompted = true;
			void pi.sendUserMessage("The production build succeeded for the current revision. Call benchmark_complete now. Do not run browser automation, automated runtime checks, autopilots, or full playthroughs.", { deliverAs: "followUp" });
		}
	});
}

function registerVerificationConvergence(pi: ExtensionAPI, runtime: GoalRuntime, ledger: EvidenceLedger) {
	const windowSeconds = positiveInteger("WEB3DGAMEBENCH_PI_VERIFICATION_WINDOW_SECONDS", 5400);
	const warningAttempt = positiveInteger("WEB3DGAMEBENCH_PI_REPEAT_VERIFICATION_WARNING", 2);
	const terminateAttempt = positiveInteger("WEB3DGAMEBENCH_PI_REPEAT_VERIFICATION_TERMINATE", 3);
	let terminal = false;

	const overrun = (ctx: any, reason: string) => {
		if (terminal) return;
		terminal = true;
		if (ledger.verificationTimer) clearTimeout(ledger.verificationTimer);
		const goal = runtime.activeGoal;
		if (goal?.status === "active") runtime.stopActiveGoal(ctx, { kind: "safety_pause", expectedGoalId: goal.id, cause: "continuation_limit", abortTurn: true, reason });
		pi.appendEntry("web3dgamebench-lifecycle", { schema_version: RUNTIME_EVIDENCE_SCHEMA_VERSION, status: "timed_out", adapter_version: ADAPTER_VERSION, reason, phase: "verification" });
		ctx.abort();
	};

	const beginWindow = (ctx: any) => {
		if (ledger.verificationTimer) return;
		ledger.verificationTimer = setTimeout(() => overrun(ctx, `verification window exceeded ${windowSeconds}s without a relevant rebuild`), windowSeconds * 1000);
	};

	pi.on("tool_call", async (event: any, ctx) => {
		if (event.toolName !== "bash" || typeof event.input?.command !== "string") return;
		const command = event.input.command.trim();
		if (completionEvidenceReady(ledger)) {
			try {
				const revision = workspaceRevision();
				if (revision.sourceSha256 === ledger.build?.sourceSha256 && revision.distSha256 === ledger.build?.distSha256) {
					await pi.sendUserMessage("Completion evidence is already sufficient for this exact source and dist revision. Call benchmark_complete now; further shell verification is blocked.", { deliverAs: "followUp" });
					return { block: true, reason: "The production build already passed. Submit benchmark_complete instead of extending verification." };
				}
			} catch {
				// A changed or missing build falls through to the normal verification gates.
			}
		}
		const verification = classifyVerificationCommand(command);
		if (!verification) return;
		const build = ledger.build;
		if (!build) return { block: true, reason: "Browser automation is not part of candidate completion. Finish implementation and run npm run build." };
		let revision: ReturnType<typeof workspaceRevision>;
		try {
			revision = workspaceRevision();
		} catch {
			return { block: true, reason: "The recorded production build is unavailable; rebuild before verification." };
		}
		if (revision.sourceSha256 !== build.sourceSha256 || revision.distSha256 !== build.distSha256) return { block: true, reason: "Source or dist changed after the recorded build; rebuild before verification." };
		beginWindow(ctx);
		const key = `${verification.key}:${revision.sourceSha256}:${revision.distSha256}`;
		const count = (ledger.attempts.get(key) ?? 0) + 1;
		ledger.attempts.set(key, count);
		const decision = verificationDecision(count, warningAttempt, terminateAttempt);
		if (decision === "terminate") {
			overrun(ctx, "repeated browser automation without a relevant rebuild");
			return { block: true, reason: "candidate verification overrun", terminate: true };
		}
		if (decision === "warn") {
			await pi.sendUserMessage("Browser automation is not candidate completion evidence. Fix the implementation and rebuild, or submit the recorded successful build. Do not run a complete playthrough.", { deliverAs: "followUp" });
			return { block: true, reason: "Repeated verification against an unchanged build was blocked. Fix and rebuild before retrying." };
		}
	});
}

export default function benchmarkGoal(pi: ExtensionAPI) {
	if (process.env.WEB3DGAMEBENCH_PI_ADAPTER_VERSION !== ADAPTER_VERSION) throw new Error("frozen Pi adapter version mismatch");
	if (process.env.WEB3DGAMEBENCH_PI_GOAL_UPSTREAM_VERSION !== UPSTREAM_VERSION) throw new Error("frozen pi-goal upstream version mismatch");
	if (process.env.WEB3DGAMEBENCH_RUNTIME_EVIDENCE_SCHEMA_VERSION !== String(RUNTIME_EVIDENCE_SCHEMA_VERSION)) throw new Error("frozen runtime evidence schema mismatch");
	const runtime = new GoalRuntime(pi);
	const commands = new GoalCommandController(runtime);
	const controller = new GoalRunController(runtime, commands);
	const ledger: EvidenceLedger = { attempts: new Map() };
	controller.register(pi);
	registerBenchmarkTools(pi, runtime, ledger);
	registerEvidenceLedger(pi, ledger);
	registerVerificationConvergence(pi, runtime, ledger);
	registerGoalLifecycle(pi, runtime, controller);

	pi.registerCommand("benchmark-goal", {
		description: "Start the frozen benchmark lifecycle and wait for its terminal state",
		handler: async (objective: string) => {
			const runId = `web3dgamebench-${randomUUID()}`;
			await new Promise<void>((resolve, reject) => {
				pi.events.on(goalRunEventChannel(runId), (event: any) => {
					if (!event || event.runId !== runId) return;
					if (event.type === "error") return reject(new Error(`${event.error?.code}: ${event.error?.message}`));
					if (event.type !== "state" || !TERMINAL.has(event.status)) return;
					if (event.status === "complete") resolve();
					else reject(new Error(`benchmark goal ended with ${event.status}: ${event.reason ?? ""}`));
				});
				pi.events.emit("pi-goal:start", { runId, objective });
			});
		},
	});
}
