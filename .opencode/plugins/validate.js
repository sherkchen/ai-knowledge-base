var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// .opencode/plugins/validate.ts
var validate_exports = {};
__export(validate_exports, {
  ValidatePlugin: () => ValidatePlugin
});
module.exports = __toCommonJS(validate_exports);
var import_path = require("path");
var ValidatePlugin = async ({ directory, $ }) => {
  return {
    "tool.execute.after": async (ctx, _output) => {
      if (ctx.tool !== "write" && ctx.tool !== "edit") return;
      const filePath = ctx.args?.file_path ?? ctx.args?.filePath;
      if (!filePath || typeof filePath !== "string") return;
      if (!filePath.endsWith(".json")) return;
      const isArticle = filePath.startsWith("knowledge/articles/") || filePath.includes("/knowledge/articles/");
      if (!isArticle) return;
      const absoluteFilePath = (0, import_path.resolve)(directory, filePath);
      const scriptPath = (0, import_path.resolve)(directory, "hooks/validate_json.py");
      const result = await $`python3 ${scriptPath} ${absoluteFilePath}`.nothrow();
      if (result.exitCode !== 0) {
        throw new Error(
          `[validate] validation failed for ${filePath}
${result.stdout}
${result.stderr}`
        );
      }
    }
  };
};
// Annotate the CommonJS export names for ESM import in node:
0 && (module.exports = {
  ValidatePlugin
});
