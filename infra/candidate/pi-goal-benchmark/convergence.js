const STRICT_SMOKE = /^\s*(?:cd\s+\/workspace\s*&&\s*)?web3dgamebench-smoke\s+--viewport\s+(1440x900|390x844)\s*$/u;
const BROWSER_SCRIPT = /(?:playwright|puppeteer|browser[-_ ]?test|full[-_ ]?playthrough|autopilot)/iu;

export function classifyVerificationCommand(command) {
	const smoke = STRICT_SMOKE.exec(command);
	if (smoke) return { key: `smoke:${smoke[1]}`, viewport: smoke[1] };
	const segments = command.split(/&&|\|\||[;|]/u).map((segment) => segment.trim());
	for (const segment of segments) {
		if (/^(?:\S*\/)?chromium(?:\s|$)/u.test(segment) && !/^\S*chromium\s+--version(?:\s|$)/u.test(segment)) {
			return { key: "unbounded", viewport: null };
		}
		if (/^(?:npx|npm\s+exec|node|bun|deno|python3?)\b/iu.test(segment) && BROWSER_SCRIPT.test(segment)) {
			return { key: "unbounded", viewport: null };
		}
		if (/^(?:\.\/|\/)[^\s]*(?:browser[-_ ]?test|full[-_ ]?playthrough|autopilot)/iu.test(segment)) {
			return { key: "unbounded", viewport: null };
		}
	}
	return null;
}

export function verificationDecision(attempt, warningAttempt, terminateAttempt) {
	if (attempt >= terminateAttempt) return "terminate";
	if (attempt >= warningAttempt) return "warn";
	return "allow";
}
