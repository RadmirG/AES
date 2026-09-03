declare module "katex" {
  type KatexOptions = {
    displayMode?: boolean;
    throwOnError?: boolean;
    strict?: boolean | "ignore" | "warn" | "error";
    trust?: boolean;
  };

  const katex: {
    renderToString(source: string, options?: KatexOptions): string;
  };

  export default katex;
}
