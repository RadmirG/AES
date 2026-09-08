import { readFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import ts from "typescript";

const require = createRequire(import.meta.url);

// Transpile components in memory; tests never generate or alter application files.
export function loadComponent(path, stubs = {}, cache = new Map()) {
  const filename = resolve(path);
  if (cache.has(filename)) return cache.get(filename);
  const exports = {};
  cache.set(filename, exports);
  const source = readFileSync(filename, "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
    target: ts.ScriptTarget.ES2022, esModuleInterop: true,
  } });
  const load = (id) => {
    if (Object.hasOwn(stubs, id)) return stubs[id];
    if (!id.startsWith(".")) return require(id);
    const base = resolve(dirname(filename), id);
    const local = [base, `${base}.ts`, `${base}.tsx`].find(existsSync);
    return loadComponent(local, stubs, cache);
  };
  new Function("require", "exports", outputText)(load, exports);
  return exports;
}
