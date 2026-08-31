import type { ChildProcess } from "node:child_process";
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { join } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type JsonObject = Record<string, unknown>;
type CriterionVerdict = "pass" | "partial" | "fail" | "unverified";
type EvidenceBasis = "visual" | "interaction" | "runtime";

type Criterion = {
	id: string;
	weight: number;
	description: string;
	evidence_requirement: "visual" | "interaction" | "either";
};

type ViewportConfig = {
	width: number;
	height: number;
	mobile: boolean;
};

type JudgeBudgets = {
	observations: number;
	input_actions: number;
	wait_actions: number;
	total_wait_ms: number;
	max_wait_ms: number;
	max_input_duration_ms: number;
};

type CdpMessage = {
	id?: number;
	method?: string;
	params?: JsonObject;
	result?: JsonObject;
	error?: { message?: string };
};
type CdpEventHandler = (params: JsonObject) => void | Promise<void>;

const outputRoot = process.env.W3GB_JUDGE_OUTPUT;
const gameUrl = process.env.W3GB_JUDGE_URL;
const chromiumPath = process.env.W3GB_CHROMIUM;
const rubricPath = process.env.W3GB_JUDGE_RUBRIC;

if (!outputRoot || !gameUrl || !chromiumPath || !rubricPath) {
	throw new Error("Judge extension requires W3GB_JUDGE_OUTPUT, W3GB_JUDGE_URL, W3GB_CHROMIUM, and W3GB_JUDGE_RUBRIC");
}
const parsedGameUrl = new URL(gameUrl);
if (!new Set(["http:", "https:"]).has(parsedGameUrl.protocol)) {
	throw new Error("W3GB_JUDGE_URL must use HTTP or HTTPS");
}
const allowedGameOrigin = parsedGameUrl.origin;

const rubric = JSON.parse(readFileSync(rubricPath, "utf8")) as {
	schema_version: number;
	task_id: string;
	minimum_evidence_coverage: number;
	viewports: { desktop: ViewportConfig; phone: ViewportConfig };
	budgets: JudgeBudgets;
	criteria: Criterion[];
};
const budgets = rubric.budgets;
const criteria = new Map(rubric.criteria.map((item) => [item.id, item]));
const evidenceIds = new Set<string>();
const evidenceActions = new Map<string, number>();
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
	private eventHandlers = new Map<string, Set<CdpEventHandler>>();
	private eventError: Error | undefined;

	constructor(private socket: WebSocket) {
		socket.addEventListener("message", (event) => {
			const message = JSON.parse(String(event.data)) as CdpMessage;
			if (message.id !== undefined) {
				const request = this.pending.get(message.id);
				if (!request) return;
				this.pending.delete(message.id);
				if (message.error) request.reject(new Error(message.error.message ?? "CDP request failed"));
				else request.resolve(message.result ?? {});
				return;
			}
			if (!message.method) return;
			for (const handler of this.eventHandlers.get(message.method) ?? []) {
				try {
					Promise.resolve(handler(message.params ?? {})).catch((error: unknown) => {
						this.eventError ??= error instanceof Error ? error : new Error(String(error));
					});
				} catch (error: unknown) {
					this.eventError ??= error instanceof Error ? error : new Error(String(error));
				}
			}
		});
	}

	on(method: string, handler: CdpEventHandler): void {
		const handlers = this.eventHandlers.get(method) ?? new Set<CdpEventHandler>();
		handlers.add(handler);
		this.eventHandlers.set(method, handlers);
	}

	assertNoEventError(): void {
		if (this.eventError) throw this.eventError;
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
let inputActionCount = 0;
let waitActionCount = 0;
let totalWaitMs = 0;
let previousObservationActionCount = 0;
let currentViewport = { ...rubric.viewports.desktop };
let pointerPosition = {
	x: rubric.viewports.desktop.width / 2,
	y: rubric.viewports.desktop.height / 2,
};
let pressedMouseButtons = 0;
let activeTouches = new Map<number, { x: number; y: number; force?: number }>();
let chromiumFrozen = false;
let reportFinished = false;
let mainFrameId: string | undefined;
let navigationPolicyActive = false;
let networkPolicyViolation: Error | undefined;

function isAllowedRequestUrl(url: string, resourceType: string, isTopFrame: boolean): boolean {
	try {
		const parsed = new URL(url);
		if (parsed.protocol === "data:" || parsed.protocol === "blob:") {
			return resourceType !== "Document" && !isTopFrame;
		}
		return parsed.origin === allowedGameOrigin;
	} catch {
		return false;
	}
}

function recordNetworkPolicyViolation(message: string): void {
	networkPolicyViolation ??= new Error(message);
}

function assertBrowserPolicy(): void {
	cdp?.assertNoEventError();
	if (networkPolicyViolation) throw networkPolicyViolation;
}

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
	if (cdp) {
		assertBrowserPolicy();
		return cdp;
	}
	const port = await freePort();
	chromium = spawn(
		chromiumPath,
		[
			"--headless=new",
			`--remote-debugging-port=${port}`,
			`--user-data-dir=${join(outputRoot, "chromium-profile")}`,
			"--remote-allow-origins=*",
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
			"about:blank",
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
	const frameTree = await cdp.send("Page.getFrameTree");
	const rootFrameTree = frameTree.frameTree as JsonObject | undefined;
	const rootFrame = rootFrameTree?.frame as JsonObject | undefined;
	mainFrameId = typeof rootFrame?.id === "string" ? rootFrame.id : undefined;
	cdp.on("Fetch.requestPaused", async (params) => {
		const request = params.request as JsonObject | undefined;
		const requestId = params.requestId;
		const requestUrl = request?.url;
		const resourceType = typeof params.resourceType === "string" ? params.resourceType : "Other";
		const frameId = typeof params.frameId === "string" ? params.frameId : undefined;
		if (typeof requestId !== "string" || typeof requestUrl !== "string") {
			throw new Error("Chromium emitted an invalid intercepted request");
		}
		const isTopFrame = resourceType === "Document" && frameId === mainFrameId;
		if (isAllowedRequestUrl(requestUrl, resourceType, isTopFrame)) {
			await cdp?.send("Fetch.continueRequest", { requestId });
			return;
		}
		recordNetworkPolicyViolation(
			isTopFrame
				? `Cross-origin top-frame navigation blocked: ${requestUrl}`
				: `Cross-origin browser request blocked: ${requestUrl}`,
		);
		await cdp?.send("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" });
	});
	cdp.on("Page.frameNavigated", (params) => {
		const frame = params.frame as JsonObject | undefined;
		if (!frame || typeof frame.id !== "string" || typeof frame.url !== "string" || typeof frame.parentId === "string") return;
		mainFrameId = frame.id;
		if (navigationPolicyActive && !isAllowedRequestUrl(frame.url, "Document", true)) {
			recordNetworkPolicyViolation(`Cross-origin top-frame navigation detected: ${frame.url}`);
		}
	});
	await cdp.send("Fetch.enable", {
		patterns: [{ urlPattern: "*", requestStage: "Request" }],
	});
	await cdp.send("Page.addScriptToEvaluateOnNewDocument", {
		source: `(() => {
			window.__W3GB_JUDGE_ERRORS__ = [];
			addEventListener('error', event => window.__W3GB_JUDGE_ERRORS__.push(String(event.message || event.error || 'page error')));
			addEventListener('unhandledrejection', event => window.__W3GB_JUDGE_ERRORS__.push(String(event.reason || 'unhandled rejection')));
		})();`,
	});
	const desktop = rubric.viewports.desktop;
	await setViewport(desktop.width, desktop.height, desktop.mobile, false);
	navigationPolicyActive = true;
	resumeChromium();
	try {
		await cdp.send("Page.navigate", { url: gameUrl });
		await sleep(2500);
		assertBrowserPolicy();
	} finally {
		freezeChromium();
	}
	return cdp;
}

async function setViewport(width: number, height: number, mobile: boolean, reload = true): Promise<void> {
	const client = cdp ?? (reload ? await browser() : undefined);
	if (!client) return;
	assertBrowserPolicy();
	currentViewport = { width, height, mobile };
	pointerPosition = { x: width / 2, y: height / 2 };
	pressedMouseButtons = 0;
	activeTouches = new Map();
	// Inputs from the previous viewport cannot support interaction claims after reload.
	previousObservationActionCount = inputActionCount;
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
		assertBrowserPolicy();
	} finally {
		freezeChromium();
	}
}

async function evaluate(expression: string): Promise<unknown> {
	const client = await browser();
	assertBrowserPolicy();
	const result = await client.send("Runtime.evaluate", {
		expression,
		returnByValue: true,
		awaitPromise: true,
	});
	assertBrowserPolicy();
	return ((result.result as JsonObject | undefined)?.value ?? null);
}

type KeyDefinition = { key: string; code: string; windowsVirtualKeyCode: number };

const keyMap: Record<string, KeyDefinition> = {
	ArrowUp: { key: "ArrowUp", code: "ArrowUp", windowsVirtualKeyCode: 38 },
	ArrowDown: { key: "ArrowDown", code: "ArrowDown", windowsVirtualKeyCode: 40 },
	ArrowLeft: { key: "ArrowLeft", code: "ArrowLeft", windowsVirtualKeyCode: 37 },
	ArrowRight: { key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39 },
	Space: { key: " ", code: "Space", windowsVirtualKeyCode: 32 },
	ShiftLeft: { key: "Shift", code: "ShiftLeft", windowsVirtualKeyCode: 16 },
	ControlLeft: { key: "Control", code: "ControlLeft", windowsVirtualKeyCode: 17 },
	AltLeft: { key: "Alt", code: "AltLeft", windowsVirtualKeyCode: 18 },
	Tab: { key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 },
	Enter: { key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 },
	Backspace: { key: "Backspace", code: "Backspace", windowsVirtualKeyCode: 8 },
	Delete: { key: "Delete", code: "Delete", windowsVirtualKeyCode: 46 },
	Insert: { key: "Insert", code: "Insert", windowsVirtualKeyCode: 45 },
	Home: { key: "Home", code: "Home", windowsVirtualKeyCode: 36 },
	End: { key: "End", code: "End", windowsVirtualKeyCode: 35 },
	PageUp: { key: "PageUp", code: "PageUp", windowsVirtualKeyCode: 33 },
	PageDown: { key: "PageDown", code: "PageDown", windowsVirtualKeyCode: 34 },
	Comma: { key: ",", code: "Comma", windowsVirtualKeyCode: 188 },
	Period: { key: ".", code: "Period", windowsVirtualKeyCode: 190 },
	Slash: { key: "/", code: "Slash", windowsVirtualKeyCode: 191 },
	Backquote: { key: "`", code: "Backquote", windowsVirtualKeyCode: 192 },
	Escape: { key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 },
};

for (let code = 65; code <= 90; code += 1) {
	const letter = String.fromCharCode(code);
	keyMap[`Key${letter}`] = { key: letter.toLowerCase(), code: `Key${letter}`, windowsVirtualKeyCode: code };
}
for (let digit = 0; digit <= 9; digit += 1) {
	keyMap[`Digit${digit}`] = { key: String(digit), code: `Digit${digit}`, windowsVirtualKeyCode: 48 + digit };
}
for (let index = 1; index <= 12; index += 1) {
	keyMap[`F${index}`] = { key: `F${index}`, code: `F${index}`, windowsVirtualKeyCode: 111 + index };
}

const KeyName = Type.Union(Object.keys(keyMap).map((name) => Type.Literal(name)));
const MouseButton = Type.Union([Type.Literal("left"), Type.Literal("right"), Type.Literal("middle")]);
const TouchPoint = Type.Object({
	id: Type.Optional(Type.Integer({ minimum: 0, maximum: 9 })),
	x: Type.Number(),
	y: Type.Number(),
	x2: Type.Optional(Type.Number()),
	y2: Type.Optional(Type.Number()),
	force: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
});

const mouseButtonMask = { left: 1, right: 2, middle: 4 } as const;
type MouseButtonName = keyof typeof mouseButtonMask;
type TouchInput = { id?: number; x: number; y: number; x2?: number; y2?: number; force?: number };
type ResolvedTouch = { id: number; x: number; y: number; force?: number };

function resolveTouches(
	touches: TouchInput[] | undefined,
	x: number | undefined,
	y: number | undefined,
	x2: number | undefined,
	y2: number | undefined,
	useEnd: boolean,
): ResolvedTouch[] {
	const source: TouchInput[] = touches ?? (
		x === undefined || y === undefined ? [] : [{ x, y, x2, y2 }]
	);
	const resolved = source.map((point, index) => ({
		id: point.id ?? index,
		x: useEnd ? point.x2 ?? point.x : point.x,
		y: useEnd ? point.y2 ?? point.y : point.y,
		...(point.force === undefined ? {} : { force: point.force }),
	}));
	if (new Set(resolved.map((point) => point.id)).size !== resolved.length) {
		throw new Error("touch point IDs must be unique");
	}
	return resolved;
}

function requireInputBudget(): void {
	if (inputActionCount >= budgets.input_actions) throw new Error("Input action limit reached");
}

function budgetDetails(): JsonObject {
	return {
		input_actions_remaining: budgets.input_actions - inputActionCount,
		wait_actions_remaining: budgets.wait_actions - waitActionCount,
		wait_ms_remaining: budgets.total_wait_ms - totalWaitMs,
	};
}

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

function scoreReport(): {
	score: number;
	evidence_coverage: number;
	observed_weight: number;
	unverified_weight: number;
	meets_minimum_evidence_coverage: boolean;
} {
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
	const evidenceCoverage = Math.round((observedWeight / totalWeight) * 1000) / 10;
	return {
		// Unverified criteria earn zero while retaining their weight in the fixed denominator.
		score: Math.round((earnedWeight / totalWeight) * 1000) / 10,
		evidence_coverage: evidenceCoverage,
		observed_weight: observedWeight,
		unverified_weight: totalWeight - observedWeight,
		meets_minimum_evidence_coverage: evidenceCoverage >= rubric.minimum_evidence_coverage,
	};
}

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "game_observe",
		label: "Observe game",
		description: `Capture a screenshot and read-only runtime snapshot. Returns an evidence ID. Budget: ${budgets.observations} observations.`,
		parameters: Type.Object({ note: Type.Optional(Type.String({ maxLength: 300 })) }),
		async execute(_id, params) {
			if (observeCount >= budgets.observations) throw new Error("Observation limit reached");
			observeCount += 1;
			const client = await browser();
			resumeChromium();
			try {
				const snapshot = await evaluate(`(() => ({
					title: document.title,
					url: location.href,
					viewport: { width: innerWidth, height: innerHeight },
					visibleText: (document.body?.innerText || '').slice(0, 5000),
					state: window.__WEB3DGAMEBENCH__ ?? null,
					errors: window.__W3GB_JUDGE_ERRORS__ ?? [],
					resources: performance.getEntriesByType('resource').map(entry => entry.name).slice(-30)
				}))()`);
				const capture = await client.send("Page.captureScreenshot", { format: "jpeg", quality: 82, fromSurface: true });
				assertBrowserPolicy();
				const data = String(capture.data ?? "");
				const evidenceId = `e${String(++evidenceCounter).padStart(3, "0")}`;
				const actionsSincePreviousObservation = inputActionCount - previousObservationActionCount;
				previousObservationActionCount = inputActionCount;
				evidenceIds.add(evidenceId);
				evidenceActions.set(evidenceId, actionsSincePreviousObservation);
				writeFileSync(join(evidenceDir, `${evidenceId}.jpg`), Buffer.from(data, "base64"));
				writeFileSync(
					join(evidenceDir, `${evidenceId}.json`),
					`${JSON.stringify({ evidence_id: evidenceId, note: params.note ?? null, captured_at: new Date().toISOString(), actions_since_previous_observation: actionsSincePreviousObservation, snapshot }, null, 2)}\n`,
				);
				return {
					content: [
						{ type: "text", text: `${evidenceId}\n${JSON.stringify(snapshot, null, 2)}` },
						{ type: "image", data, mimeType: "image/jpeg" },
					],
					details: { evidenceId, actionsSincePreviousObservation, snapshot },
				};
			} finally {
				freezeChromium();
			}
		},
	});

	pi.registerTool({
		name: "game_act",
		label: "Act in game",
		description: `Send bounded keyboard, mouse, pointer-lock-relative, wheel, or persistent multi-touch input. Waits have a separate budget and do not count as interaction evidence. Budgets: ${budgets.input_actions} inputs, ${budgets.wait_actions} waits, ${budgets.total_wait_ms} total wait ms.`,
		parameters: Type.Object({
			kind: Type.Union([
				Type.Literal("keys"),
				Type.Literal("click"),
				Type.Literal("mouse_down"),
				Type.Literal("mouse_up"),
				Type.Literal("drag"),
				Type.Literal("move"),
				Type.Literal("relative_move"),
				Type.Literal("wheel"),
				Type.Literal("touch"),
				Type.Literal("touch_start"),
				Type.Literal("touch_move"),
				Type.Literal("touch_end"),
				Type.Literal("wait"),
			]),
			keys: Type.Optional(Type.Array(KeyName, { maxItems: 6 })),
			button: Type.Optional(MouseButton),
			click_count: Type.Optional(Type.Integer({ minimum: 1, maximum: 2 })),
			duration_ms: Type.Optional(Type.Integer({
				minimum: 50,
				maximum: Math.max(budgets.max_wait_ms, budgets.max_input_duration_ms),
			})),
			x: Type.Optional(Type.Number()),
			y: Type.Optional(Type.Number()),
			x2: Type.Optional(Type.Number()),
			y2: Type.Optional(Type.Number()),
			delta_x: Type.Optional(Type.Number({ minimum: -2000, maximum: 2000 })),
			delta_y: Type.Optional(Type.Number({ minimum: -2000, maximum: 2000 })),
			touches: Type.Optional(Type.Array(TouchPoint, { minItems: 1, maxItems: 5 })),
		}),
		async execute(_id, params) {
			const isWait = params.kind === "wait";
			const duration = params.duration_ms ?? (isWait ? 1000 : 250);
			if (isWait) {
				if (duration > budgets.max_wait_ms) throw new Error("Single wait duration limit reached");
				if (waitActionCount >= budgets.wait_actions) throw new Error("Wait action limit reached");
				if (totalWaitMs + duration > budgets.total_wait_ms) throw new Error("Total wait duration limit reached");
			} else {
				if (duration > budgets.max_input_duration_ms) throw new Error("Input duration limit reached");
				requireInputBudget();
			}
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
					const button = (params.button ?? "left") as MouseButtonName;
					const buttons = pressedMouseButtons | mouseButtonMask[button];
					const clickCount = params.click_count ?? 1;
					pointerPosition = { x: params.x, y: params.y };
					await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: params.x, y: params.y, button, buttons, clickCount });
					await sleep(duration);
					await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: params.x, y: params.y, button, buttons: pressedMouseButtons, clickCount });
				} else if (params.kind === "mouse_down") {
					if (params.x === undefined || params.y === undefined) throw new Error("mouse_down requires x and y");
					const button = (params.button ?? "left") as MouseButtonName;
					pressedMouseButtons |= mouseButtonMask[button];
					pointerPosition = { x: params.x, y: params.y };
					await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: params.x, y: params.y, button, buttons: pressedMouseButtons, clickCount: 1 });
				} else if (params.kind === "mouse_up") {
					const button = (params.button ?? "left") as MouseButtonName;
					const x = params.x ?? pointerPosition.x;
					const y = params.y ?? pointerPosition.y;
					pressedMouseButtons &= ~mouseButtonMask[button];
					pointerPosition = { x, y };
					await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button, buttons: pressedMouseButtons, clickCount: 1 });
				} else if (params.kind === "drag") {
					if ([params.x, params.y, params.x2, params.y2].some((value) => value === undefined)) throw new Error("drag requires x, y, x2, and y2");
					const x = params.x as number;
					const y = params.y as number;
					const x2 = params.x2 as number;
					const y2 = params.y2 as number;
					const button = (params.button ?? "left") as MouseButtonName;
					const buttons = pressedMouseButtons | mouseButtonMask[button];
					await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button, buttons, clickCount: 1 });
					await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: x2, y: y2, button, buttons });
					await sleep(duration);
					await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: x2, y: y2, button, buttons: pressedMouseButtons, clickCount: 1 });
					pointerPosition = { x: x2, y: y2 };
				} else if (params.kind === "move") {
					if (params.x === undefined || params.y === undefined) throw new Error("move requires x and y");
					await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: params.x, y: params.y, button: "none", buttons: pressedMouseButtons });
					pointerPosition = { x: params.x, y: params.y };
					if (params.x2 !== undefined && params.y2 !== undefined) {
						await sleep(duration);
						await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: params.x2, y: params.y2, button: "none", buttons: pressedMouseButtons });
						pointerPosition = { x: params.x2, y: params.y2 };
					}
				} else if (params.kind === "relative_move") {
					const deltaX = params.delta_x ?? 0;
					const deltaY = params.delta_y ?? 0;
					if (deltaX === 0 && deltaY === 0) throw new Error("relative_move requires delta_x or delta_y");
					const x = Math.min(Math.max(pointerPosition.x + deltaX, 1), currentViewport.width - 1);
					const y = Math.min(Math.max(pointerPosition.y + deltaY, 1), currentViewport.height - 1);
					await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none", buttons: pressedMouseButtons });
					pointerPosition = { x, y };
				} else if (params.kind === "wheel") {
					const x = params.x ?? currentViewport.width / 2;
					const y = params.y ?? currentViewport.height / 2;
					await client.send("Input.dispatchMouseEvent", {
						type: "mouseWheel",
						x,
						y,
						deltaX: params.delta_x ?? 0,
						deltaY: params.delta_y ?? 0,
					});
				} else if (params.kind === "touch") {
					if (activeTouches.size) throw new Error("touch requires no persistent active touches");
					const touchPoints = resolveTouches(params.touches as TouchInput[] | undefined, params.x, params.y, params.x2, params.y2, false);
					if (!touchPoints.length) throw new Error("touch requires touches or x and y");
					await client.send("Input.dispatchTouchEvent", {
						type: "touchStart",
						touchPoints,
					});
					const movedTouches = resolveTouches(params.touches as TouchInput[] | undefined, params.x, params.y, params.x2, params.y2, true);
					await client.send("Input.dispatchTouchEvent", {
						type: "touchMove",
						touchPoints: movedTouches,
					});
					await sleep(duration);
					await client.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
				} else if (params.kind === "touch_start") {
					if (activeTouches.size) throw new Error("touch_start requires no active touches");
					const touchPoints = resolveTouches(params.touches as TouchInput[] | undefined, params.x, params.y, params.x2, params.y2, false);
					if (!touchPoints.length) throw new Error("touch_start requires touches or x and y");
					activeTouches = new Map(touchPoints.map((point) => [point.id, point]));
					await client.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints });
				} else if (params.kind === "touch_move") {
					if (!activeTouches.size) throw new Error("touch_move requires active touches");
					const touchPoints = resolveTouches(params.touches as TouchInput[] | undefined, params.x, params.y, params.x2, params.y2, false);
					if (
						touchPoints.length !== activeTouches.size
						|| touchPoints.some((point) => !activeTouches.has(point.id))
					) throw new Error("touch_move must provide every active touch ID");
					activeTouches = new Map(touchPoints.map((point) => [point.id, point]));
					await client.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints });
				} else {
					if (!activeTouches.size) throw new Error("touch_end requires active touches");
					await client.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
					activeTouches.clear();
				}
				if (isWait) {
					waitActionCount += 1;
					totalWaitMs += duration;
				} else {
					inputActionCount += 1;
				}
				assertBrowserPolicy();
			} finally {
				freezeChromium();
			}
			return {
				content: [{ type: "text", text: `Completed ${params.kind} action for ${duration} ms.` }],
				details: { ...params, duration_ms: duration, ...budgetDetails() },
			};
		},
	});

	pi.registerTool({
		name: "game_set_viewport",
		label: "Set viewport",
		description: `Switch between configured desktop (${rubric.viewports.desktop.width} x ${rubric.viewports.desktop.height}) and phone (${rubric.viewports.phone.width} x ${rubric.viewports.phone.height}) viewports. Reloads the game.`,
		parameters: Type.Object({ viewport: Type.Union([Type.Literal("desktop"), Type.Literal("phone")]) }),
		async execute(_id, params) {
			const viewport = rubric.viewports[params.viewport];
			await setViewport(viewport.width, viewport.height, viewport.mobile);
			return { content: [{ type: "text", text: `Viewport is now ${params.viewport}; the game was reloaded.` }], details: currentViewport };
		},
	});

	pi.registerTool({
		name: "game_restart",
		label: "Reload game",
		description: "Reload the current game at the current viewport and wait for it to initialize.",
		parameters: Type.Object({}),
		async execute() {
			requireInputBudget();
			const client = await browser();
			resumeChromium();
			try {
				await client.send("Page.reload", { ignoreCache: true });
				await sleep(1800);
				assertBrowserPolicy();
				pressedMouseButtons = 0;
				activeTouches.clear();
				pointerPosition = {
					x: currentViewport.width / 2,
					y: currentViewport.height / 2,
				};
				inputActionCount += 1;
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
			evidence_basis: Type.Array(
				Type.Union([Type.Literal("visual"), Type.Literal("interaction"), Type.Literal("runtime")]),
				{ maxItems: 3 },
			),
			reason: Type.String({ minLength: 1, maxLength: 1200 }),
		}),
		async execute(_id, params) {
			assertBrowserPolicy();
			const criterion = criteria.get(params.criterion_id);
			if (!criterion) throw new Error(`Unknown criterion: ${params.criterion_id}`);
			if (findings.has(params.criterion_id)) throw new Error(`Criterion already recorded: ${params.criterion_id}`);
			if (params.verdict !== "unverified" && !params.evidence_ids.length) throw new Error("Observed verdicts require evidence");
			for (const evidenceId of params.evidence_ids) {
				if (!evidenceIds.has(evidenceId)) throw new Error(`Unknown evidence ID: ${evidenceId}`);
			}
			const basis = new Set<EvidenceBasis>(params.evidence_basis as EvidenceBasis[]);
			if (params.verdict !== "unverified") {
				if (!basis.has("visual") && !basis.has("interaction")) {
					throw new Error("Runtime state cannot be the sole basis for an observed verdict");
				}
				if (criterion.evidence_requirement === "visual" && !basis.has("visual")) {
					throw new Error(`${criterion.id} requires visible screenshot evidence`);
				}
				if (criterion.evidence_requirement === "interaction" && !basis.has("interaction")) {
					throw new Error(`${criterion.id} requires controlled interaction evidence`);
				}
				if (
					basis.has("interaction")
					&& !params.evidence_ids.some((evidenceId) => (evidenceActions.get(evidenceId) ?? 0) > 0)
				) {
					throw new Error("Interaction evidence must cite an observation captured after controlled input");
				}
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
			assertBrowserPolicy();
			if (reportFinished) throw new Error("Judge report is already complete");
			const missing = rubric.criteria.map((item) => item.id).filter((id) => !findings.has(id));
			if (missing.length) throw new Error(`Record every criterion first. Missing: ${missing.join(", ")}`);
			const scoring = scoreReport();
			const report = {
				schema_version: 2,
				task_id: rubric.task_id,
				status: scoring.meets_minimum_evidence_coverage ? "complete" : "insufficient-evidence",
				provisional_score: scoring.score,
				evidence_coverage: scoring.evidence_coverage,
				minimum_evidence_coverage: rubric.minimum_evidence_coverage,
				meets_minimum_evidence_coverage: scoring.meets_minimum_evidence_coverage,
				viewports: rubric.viewports,
				tool_budget: budgets,
				tool_usage: {
					observations: observeCount,
					input_actions: inputActionCount,
					wait_actions: waitActionCount,
					total_wait_ms: totalWaitMs,
				},
				scoring: {
					denominator_weight: 100,
					observed_weight: scoring.observed_weight,
					unverified_weight: scoring.unverified_weight,
					unverified_is_zero: true,
				},
				criteria: rubric.criteria.map((criterion) => ({ ...criterion, ...findings.get(criterion.id) })),
				summary: params.summary,
				strengths: params.strengths,
				weaknesses: params.weaknesses,
				finished_at: new Date().toISOString(),
			};
			writeFileSync(
				join(outputRoot, "judge-report.json"),
				`${JSON.stringify(report, null, 2)}\n`,
				{ encoding: "utf8", flag: "wx" },
			);
			reportFinished = true;
			return {
				content: [{
					type: "text",
					text: `Judge report ${report.status}. Provisional score ${scoring.score}/100 with unverified at zero; evidence coverage ${scoring.evidence_coverage}% (minimum ${rubric.minimum_evidence_coverage}%).`,
				}],
				details: report,
			};
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
