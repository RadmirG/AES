import { aesApiBaseUrl } from "./config";
import type { AesArtifact, AesResult, ToolResult } from "./types";

export function latestArtifactStore(aesResult?: AesResult) {
  const results = aesResult?.tool_results || [];
  for (let index = results.length - 1; index >= 0; index -= 1) {
    const result = results[index];
    if (result.tool_name === "artifact_store") {
      return result;
    }
  }
  return undefined;
}

export function manifestFromArtifactStore(tool?: ToolResult) {
  const manifest = tool?.output?.manifest;
  return isRecord(manifest) ? manifest : undefined;
}

export function artifactsFromResult(aesResult?: AesResult): AesArtifact[] {
  const manifest = manifestFromArtifactStore(latestArtifactStore(aesResult));
  const artifacts = manifest?.artifacts;
  return Array.isArray(artifacts) ? (artifacts as AesArtifact[]) : [];
}

export function publicArtifactUrl(artifact: AesArtifact) {
  if (artifact.public_url) {
    return artifact.public_url;
  }
  if (artifact.uri?.startsWith("http://") || artifact.uri?.startsWith("https://")) {
    return artifact.uri;
  }
  const match = artifact.uri?.match(/^aes:\/\/artifacts\/([^/]+)\/(.+)$/);
  if (!match) {
    return "";
  }
  return `${aesApiBaseUrl}/artifacts/${match[1]}/${match[2]}`;
}

export function findArtifact(artifacts: AesArtifact[], name: string) {
  return artifacts.find((artifact) => artifact.name === name);
}

export function resultLinks(aesResult?: AesResult) {
  const artifacts = artifactsFromResult(aesResult);
  return [
    "viewer.html",
    "preview.svg",
    "viewer_manifest.json",
    "diagnostics.json",
    "solve.py",
    "stdout.txt",
  ]
    .map((name) => {
      const artifact = findArtifact(artifacts, name);
      const url = artifact ? publicArtifactUrl(artifact) : "";
      return artifact && url ? { name, artifact, url } : null;
    })
    .filter(Boolean) as Array<{ name: string; artifact: AesArtifact; url: string }>;
}

export function visualizationManifestUrl(aesResult?: AesResult) {
  return resultLinks(aesResult).find((link) => link.name === "viewer_manifest.json")?.url || "";
}

export function previewUrl(aesResult?: AesResult) {
  return resultLinks(aesResult).find((link) => link.name === "preview.svg")?.url || "";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

