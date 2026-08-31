import type { ChildProcess } from "node:child_process";
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { join } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type JsonObject = Record<string, unknown>;
type CriterionVerdict = "pass" | "partial" | "fail" | "unverified";

type Criterion = {
	id: string;
	weight: number;
	description: string;
};

type CdpMessage = {
	id?: number;
	method?: string;
	params?: JsonObject;
	result?: JsonObject;
	error?: { message?: string };
};

const outputRoot = process.env.W3GB_JUDGE_OUTPUT;
const gameUrl = process.env.W3GB_JUDGE_URL;
const chromiumPath = process.env.W3GB_CHROMIUM;
const rubricPath = process.env.W3GB_JUDGE_RUBRIC;

if (!outputRoot || !gameUrl || !chromiumPath || !rubricPath) {
	throw new Error("Judge extension requires W3GB_JUDGE_OUTPUT, W3GB_JUDGE_URL, W3GB_CHROMIUM, and W3GB_JUDGE_RUBRIC");
}

const rubric = JSON.parse(readFileSync(rubricPath, "utf8")) as {
	schema_version: number;
	task_id: string;
	criteria: Criterion[];
};
const criteria = new Map(rubric.criteria.map((item) => [item.id, item]));
const evidenceIds = new Set<string>();
const findings = new Map<string, JsonObject>();
const evidenceDir = join(outputRoot, "evidence");
mkdirSync(evidenceDir, { recursive: true });

const sleep = (milliseconds: number) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function freePort(): Promise<number> {
	return new Promise((resolve, reject) => {
		const server = createServer();
		server.once("error", reject);
		server.listen(0, "127.0.0.1", () => {
			const address = server.address();
			if (!address || typeof address === "string") {
				server.close();
				reject(new Error("Could not allocate a Chromium debugging port"));
				return;
			}
			server.close(() => resolve(address.port));
		});
	});
}

class CdpClient {
	private nextId = 1;
	private pending = new Map<number, { resolve: (value: JsonObject) => void; reject: (error: Error) => void }>();

	constructor(private socket: WebSocket) {
		socket.addEventListener("message", (event) => {
			const message = JSON.parse(String(event.data)) as CdpMessage;
			if (!message.id) return;
			const request = this.pending.get(message.id);
			if (!request) return;
			this.pending.delete(message.id);
			if (message.error) request.reject(new Error(message.error.message ?? "CDP request failed"));
			else request.resolve(message.result ?? {});
		});
	}

	async send(method: string, params: JsonObject = {}): Promise<JsonObject> {
		const id = this.nextId++;
		return new Promise((resolve, reject) => {
			this.pending.set(id, { resolve, reject });
			this.socket.send(JSON.stringify({ id, method, params }));
		});
	}

	close(): void {
		this.socket.close();
	}
}

let chromium: ChildProcess | undefined;
let cdp: CdpClient | undefined;
let evidenceCounter = 0;
let observeCount = 0;
let actionCount = 0;
let currentViewport = { width: 1440, height: 900, mobile: false };
let chromiumFrozen = false;

function signalChromium(signal: NodeJS.Signals): void {
	if (!chromium?.pid) return;
	try {
		process.kill(-chromium.pid, signal);
	} catch {
		if (signal !== "SIGKILL") throw new Error(`Could not signal Chromium process group with ${signal}`);
	}
}

function resumeChromium(): void {
	if (!chromiumFrozen) return;
	signalChromium("SIGCONT");
	chromiumFrozen = false;
}

function freezeChromium(): void {
	if (chromiumFrozen || !chromium?.pid) return;
	signalChromium("SIGSTOP");
	chromiumFrozen = true;
}

async function connectWebSocket(url: string): Promise<WebSocket> {
	return new Promise((resolve, reject) => {
		const socket = new WebSocket(url);
		socket.addEventListener("open", () => resolve(socket), { once: true });
		socket.addEventListener("error", () => reject(new Error("Could not connect to Chromium CDP")), { once: true });
	});
}

async function browser(): Promise<CdpClient> {
	if (cdp) return cdp;
	const port = await freePort();
	chromium = spawn(
		chromiumPath,
		[
			"--headless=new",
			`--remote-debugging-port=${port}`,
			`--user-data-dir=${join(outputRoot, "chromium-profile")}`,
			"--remote-allow-origins=*",
			"--no-sandbox",
			"--use-gl=angle",
			"--use-angle=swiftshader",
			"--enable-unsafe-swiftshader",
			"--disable-background-networking",
			"--disable-default-apps",
			"--disable-extensions",
			"--disable-sync",
			"--no-first-run",
			"--mute-audio",
			"--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
			gameUrl,
		],
		{ stdio: "ignore", detached: true },
	);
	if (chromium.pid) writeFileSync(join(outputRoot, "chromium.pid"), `${chromium.pid}\n`);

	let target: { type?: string; webSocketDebuggerUrl?: string } | undefined;
	for (let attempt = 0; attempt < 100; attempt += 1) {
		try {
			const response = await fetch(`http://127.0.0.1:${port}/json/list`);
			const targets = (await response.json()) as Array<{ type?: string; webSocketDebuggerUrl?: string }>;
			target = targets.find((item) => item.type === "page" && item.webSocketDebuggerUrl);
			if (target) break;
		} catch {
			// Chromium is still starting.
		}
		await sleep(100);
	}
	if (!target?.webSocketDebuggerUrl) throw new Error("Chromium did not expose a page target");

	cdp = new CdpClient(await connectWebSocket(target.webSocketDebuggerUrl));
	await cdp.send("Page.enable");
	await cdp.send("Runtime.enable");
	await cdp.send("Network.enable");
	await cdp.send("Page.addScriptToEvaluateOnNewDocument", {
		source: `(() => {
			window.__W3GB_JUDGE_ERRORS__ = [];
			addEventListener('error', event => window.__W3GB_JUDGE_ERRORS__.push(String(event.message || event.error || 'page error')));
			addEventListener('unhandledrejection', event => window.__W3GB_JUDGE_ERRORS__.push(String(event.reason || 'unhandled rejection')));
		})();`,
	});
	await setViewport(1440, 900, false, false);
	resumeChromium();
	try {
		await cdp.send("Page.reload", { ignoreCache: true });
		await sleep(2500);
	} finally {
		freezeChromium();
	}
	return cdp;
}

async function setViewport(width: number, height: number, mobile: boolean, reload = true): Promise<void> {
	const client = cdp ?? (reload ? await browser() : undefined);
	if (!client) return;
	currentViewport = { width, height, mobile };
	resumeChromium();
	try {
		await client.send("Emulation.setDeviceMetricsOverride", {
			width,
			height,
			deviceScaleFactor: 1,
			mobile,
		});
		await client.send("Emulation.setTouchEmulationEnabled", { enabled: mobile, maxTouchPoints: mobile ? 5 : 1 });
		if (reload) {
			await client.send("Page.reload", { ignoreCache: true });
			await sleep(1800);
		}
	} finally {
		freezeChromium();
	}
}

async function evaluate(expression: string): Promise<unknown> {
	const client = await browser();
	const result = await client.send("Runtime.evaluate", {
		expression,
		returnByValue: true,
		awaitPromise: true,
	});
	return ((result.result as JsonObject | undefined)?.value ?? null);
}

const keyMap: Record<string, { key: string; code: string; windowsVirtualKeyCode: number }> = {
	ArrowUp: { key: "ArrowUp", code: "ArrowUp", windowsVirtualKeyCode: 38 },
	ArrowDown: { key: "ArrowDown", code: "ArrowDown", windowsVirtualKeyCode: 40 },
	ArrowLeft: { key: "ArrowLeft", code: "ArrowLeft", windowsVirtualKeyCode: 37 },
	ArrowRight: { key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39 },
	KeyW: { key: "w", code: "KeyW", windowsVirtualKeyCode: 87 },
	KeyA: { key: "a", code: "KeyA", windowsVirtualKeyCode: 65 },
	KeyS: { key: "s", code: "KeyS", windowsVirtualKeyCode: 83 },
	KeyD: { key: "d", code: "KeyD", windowsVirtualKeyCode: 68 },
	KeyX: { key: "x", code: "KeyX", windowsVirtualKeyCode: 88 },
	KeyP: { key: "p", code: "KeyP", windowsVirtualKeyCode: 80 },
	KeyR: { key: "r", code: "KeyR", windowsVirtualKeyCode: 82 },
	Space: { key: " ", code: "Space", windowsVirtualKeyCode: 32 },
	ShiftLeft: { key: "Shift", code: "ShiftLeft", windowsVirtualKeyCode: 16 },
	Escape: { key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 },
};

const KeyName = Type.Union(Object.keys(keyMap).map((name) => Type.Literal(name)));

async function dispatchKeys(keys: string[], durationMs: number): Promise<void> {
	const client = await browser();
	const pressed: string[] = [];
	try {
		for (const name of keys) {
			const key = keyMap[name];
			if (!key) throw new Error(`Unsupported key: ${name}`);
			await client.send("Input.dispatchKeyEvent", { type: "keyDown", ...key });
			pressed.push(name);
		}
		await sleep(durationMs);
	} finally {
		for (const name of pressed.reverse()) {
			await client.send("Input.dispatchKeyEvent", { type: "keyUp", ...keyMap[name] });
		}
	}
}

function scoreReport(): { score: number | null; evidence_coverage: number } {
	let observedWeight = 0;
	let earnedWeight = 0;
	const totalWeight = rubric.criteria.reduce((sum, item) => sum + item.weight, 0);
	for (const criterion of rubric.criteria) {
		const finding = findings.get(criterion.id);
		const verdict = finding?.verdict as CriterionVerdict | undefined;
		if (!verdict || verdict === "unverified") continue;
		observedWeight += criterion.weight;
		earnedWeight += criterion.weight * (verdict === "pass" ? 1 : verdict === "partial" ? 0.5 : 0);
	}
	return {
		score: observedWeight ? Math.round((earnedWeight / observedWeight) * 1000) / 10 : null,
		evidence_coverage: Math.round((observedWeight / totalWeight) * 1000) / 10,
	};
}

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "game_observe",
		label: "Observe game",
		description: "Capture the current game screenshot and a read-only runtime snapshot. Returns an evidence ID.",
		parameters: Type.Object({ note: Type.Optional(Type.String({ maxLength: 300 })) }),
		async execute(_id, params) {
			if (++observeCount > 30) throw new Error("Observation limit reached");
			const client = await browser();
			resumeChromium();
			try {
				const snapshot = await evaluate(`(() => ({
				title: document.title,
				url: location.href,
				viewport: { width: innerWidth, height: innerHeight },
				visibleText: (document.body?.innerText || '').slice(0, 5000),
				state: window.__WEB3DGAMEBENCH__ ?? window.__AETHERPLAY__ ?? null,
				errors: window.__W3GB_JUDGE_ERRORS__ ?? [],
				resources: performance.getEntriesByType('resource').map(entry => entry.name).slice(-30)
			}))()`);
				const capture = await client.send("Page.captureScreenshot", { format: "jpeg", quality: 82, fromSurface: true });
				const data = String(capture.data ?? "");
				const evidenceId = `e${String(++evidenceCounter).padStart(3, "0")}`;
				evidenceIds.add(evidenceId);
				writeFileSync(join(evidenceDir, `${evidenceId}.jpg`), Buffer.from(data, "base64"));
				writeFileSync(
					join(evidenceDir, `${evidenceId}.json`),
					`${JSON.stringify({ evidence_id: evidenceId, note: params.note ?? null, captured_at: new Date().toISOString(), snapshot }, null, 2)}\n`,
				);
				return {
					content: [
						{ type: "text", text: `${evidenceId}\n${JSON.stringify(snapshot, null, 2)}` },
						{ type: "image", data, mimeType: "image/jpeg" },
					],
					details: { evidenceId, snapshot },
				};
			} finally {
				freezeChromium();
			}
		},
	});

	pi.registerTool({
		name: "game_act",
		label: "Act in game",
		description: "Send a bounded keyboard, pointer, touch, or wait action to the game.",
		parameters: Type.Object({
			kind: Type.Union([Type.Literal("keys"), Type.Literal("click"), Type.Literal("drag"), Type.Literal("touch"), Type.Literal("wait")]),
			keys: Type.Optional(Type.Array(KeyName, { maxItems: 4 })),
			duration_ms: Type.Optional(Type.Integer({ minimum: 50, maximum: 5000 })),
			x: Type.Optional(Type.Number()),
			y: Type.Optional(Type.Number()),
			x2: Type.Optional(Type.Number()),
			y2: Type.Optional(Type.Number()),
		}),
		async execute(_id, params) {
			if (++actionCount > 60) throw new Error("Action limit reached");
			const duration = Math.min(Math.max(params.duration_ms ?? 250, 50), 5000);
			const client = await browser();
			resumeChromium();
			try {
				if (params.kind === "keys") {
					if (!params.keys?.length) throw new Error("keys action requires at least one key");
					await dispatchKeys(params.keys, duration);
				} else if (params.kind === "wait") {
					await sleep(duration);
				} else if (params.kind === "click") {
					if (params.x === undefined || params.y === undefined) throw new Error("click requires x and y");
					await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: params.x, y: params.y, button: "left", clickCount: 1 });
					await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: params.x, y: params.y, button: "left", clickCount: 1 });
				} else if (params.kind === "drag") {
					if ([params.x, params.y, params.x2, params.y2].some((value) => value === undefined)) throw new Error("drag requires x, y, x2, and y2");
					await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: params.x, y: params.y, button: "left", clickCount: 1 });
					await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: params.x2, y: params.y2, button: "left", buttons: 1 });
					await sleep(duration);
					await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: params.x2, y: params.y2, button: "left", clickCount: 1 });
				} else {
					if (params.x === undefined || params.y === undefined) throw new Error("touch requires x and y");
					const x2 = params.x2 ?? params.x;
					const y2 = params.y2 ?? params.y;
					await client.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: params.x, y: params.y }] });
					await client.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: x2, y: y2 }] });
					await sleep(duration);
					await client.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
				}
			} finally {
				freezeChromium();
			}
			return { content: [{ type: "text", text: `Completed ${params.kind} action for ${duration} ms.` }], details: { ...params, duration_ms: duration } };
		},
	});

	pi.registerTool({
		name: "game_set_viewport",
		label: "Set viewport",
		description: "Switch between the frozen desktop and phone viewports. Reloads the game.",
		parameters: Type.Object({ viewport: Type.Union([Type.Literal("desktop"), Type.Literal("phone")]) }),
		async execute(_id, params) {
			if (params.viewport === "phone") await setViewport(390, 844, true);
			else await setViewport(1440, 900, false);
			return { content: [{ type: "text", text: `Viewport is now ${params.viewport}; the game was reloaded.` }], details: currentViewport };
		},
	});

	pi.registerTool({
		name: "game_restart",
		label: "Reload game",
		description: "Reload the current game at the current viewport and wait for it to initialize.",
		parameters: Type.Object({}),
		async execute() {
			const client = await browser();
			resumeChromium();
			try {
				await client.send("Page.reload", { ignoreCache: true });
				await sleep(1800);
			} finally {
				freezeChromium();
			}
			return { content: [{ type: "text", text: "Game reloaded." }], details: currentViewport };
		},
	});

	pi.registerTool({
		name: "judge_record_criterion",
		label: "Record criterion",
		description: "Record one evidence-grounded rubric verdict. A criterion can only be recorded once.",
		parameters: Type.Object({
			criterion_id: Type.String(),
			verdict: Type.Union([Type.Literal("pass"), Type.Literal("partial"), Type.Literal("fail"), Type.Literal("unverified")]),
			confidence: Type.Number({ minimum: 0, maximum: 1 }),
			evidence_ids: Type.Array(Type.String(), { maxItems: 10 }),
			reason: Type.String({ minLength: 1, maxLength: 1200 }),
		}),
		async execute(_id, params) {
			if (!criteria.has(params.criterion_id)) throw new Error(`Unknown criterion: ${params.criterion_id}`);
			if (findings.has(params.criterion_id)) throw new Error(`Criterion already recorded: ${params.criterion_id}`);
			if (params.verdict !== "unverified" && !params.evidence_ids.length) throw new Error("Observed verdicts require evidence");
			for (const evidenceId of params.evidence_ids) {
				if (!evidenceIds.has(evidenceId)) throw new Error(`Unknown evidence ID: ${evidenceId}`);
			}
			const finding = { ...params, recorded_at: new Date().toISOString() };
			findings.set(params.criterion_id, finding);
			return { content: [{ type: "text", text: `Recorded ${params.criterion_id}: ${params.verdict}` }], details: finding };
		},
	});

	pi.registerTool({
		name: "judge_finish",
		label: "Finish judge run",
		description: "Write the final structured playtest report after every criterion has been recorded.",
		parameters: Type.Object({
			summary: Type.String({ minLength: 1, maxLength: 2000 }),
			strengths: Type.Array(Type.String({ maxLength: 500 }), { maxItems: 8 }),
			weaknesses: Type.Array(Type.String({ maxLength: 500 }), { maxItems: 8 }),
		}),
		async execute(_id, params) {
			const missing = rubric.criteria.map((item) => item.id).filter((id) => !findings.has(id));
			if (missing.length) throw new Error(`Record every criterion first. Missing: ${missing.join(", ")}`);
			const scoring = scoreReport();
			const report = {
				schema_version: 1,
				task_id: rubric.task_id,
				status: "complete",
				provisional_score: scoring.score,
				evidence_coverage: scoring.evidence_coverage,
				criteria: rubric.criteria.map((criterion) => ({ ...criterion, ...findings.get(criterion.id) })),
				summary: params.summary,
				strengths: params.strengths,
				weaknesses: params.weaknesses,
				finished_at: new Date().toISOString(),
			};
			writeFileSync(join(outputRoot, "judge-report.json"), `${JSON.stringify(report, null, 2)}\n`);
			return { content: [{ type: "text", text: `Judge report complete. Provisional score ${scoring.score}; evidence coverage ${scoring.evidence_coverage}%.` }], details: report };
		},
	});

	pi.on("session_shutdown", async () => {
		resumeChromium();
		cdp?.close();
		cdp = undefined;
		if (chromium && !chromium.killed) signalChromium("SIGKILL");
		chromium = undefined;
	});
}
