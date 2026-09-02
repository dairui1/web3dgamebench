export interface VerificationCommand {
	key: string;
	viewport: string | null;
}

export function classifyVerificationCommand(command: string): VerificationCommand | null;
export function verificationDecision(
	attempt: number,
	warningAttempt: number,
	terminateAttempt: number,
): "allow" | "warn" | "terminate";
