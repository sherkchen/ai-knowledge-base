import type { Plugin } from "@opencode-ai/plugin";
import { resolve } from "path";

export const ValidatePlugin: Plugin = async ({ directory, $ }) => {
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

      const absoluteFilePath = resolve(directory, filePath);
      const scriptPath = resolve(directory, "hooks/validate_json.py");
      const result =
        await $`python3 ${scriptPath} ${absoluteFilePath}`.nothrow();

      if (result.exitCode !== 0) {
        throw new Error(
          `[validate] validation failed for ${filePath}\n${result.stdout}\n${result.stderr}`
        );
      }
    },
  };
};
