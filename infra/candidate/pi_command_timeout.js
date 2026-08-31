import { createBashTool } from "./dist/index.js";

const FALLBACK_TIMEOUT_SECONDS = 1200;

function configuredTimeout() {
  const value = Number.parseInt(
    process.env.WEB3DGAMEBENCH_COMMAND_TIMEOUT_SECONDS ?? "",
    10,
  );
  return Number.isFinite(value) && value > 0 ? value : FALLBACK_TIMEOUT_SECONDS;
}

export default function registerCommandTimeout(pi) {
  const maximum = configuredTimeout();
  const bashTool = createBashTool(process.cwd());

  pi.registerTool({
    ...bashTool,
    description: `${bashTool.description} The harness limits each command to ${maximum} seconds; this does not limit the overall task.`,
    execute: async (id, params, signal, onUpdate) => {
      const requested = params.timeout;
      const timeout =
        typeof requested === "number" ? Math.min(requested, maximum) : maximum;
      return bashTool.execute(id, { ...params, timeout }, signal, onUpdate);
    },
  });
}
