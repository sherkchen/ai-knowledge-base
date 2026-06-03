import type { Plugin } from "@opencode-ai/plugin";

export const ValidatePlugin: Plugin = async ({ $ }) => {
  return {
    "tool.execute.after": async (ctx, _output) => {
      if (ctx.tool !== "write" && ctx.tool !== "edit") return;

      const filePath: string | undefined =
        ctx.args?.file_path ?? ctx.args?.filePath;

      if (!filePath || typeof filePath !== "string") return;

      if (!filePath.endsWith(".json")) return;

      const isArticle =
        filePath.startsWith("knowledge/articles/") ||
        filePath.includes("/knowledge/articles/");

      if (!isArticle) return;

      try {
        const result =
          await $`python3 hooks/validate_json.py ${filePath}`.nothrow();
        if (result.exitCode !== 0) {
          console.warn(
            `[validate] validation failed for ${filePath} (exit ${result.exitCode})\n${result.text()}`
          );
        }
      } catch (err) {
        console.warn(`[validate] unexpected error for ${filePath}:`, err);
      }
    },
  };
};
