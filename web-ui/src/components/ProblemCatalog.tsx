import { useEffect, useMemo, useState } from "react";
import type {
  GeometryContext,
  GeometryExampleIndexItem,
  GeometrySpec,
  ProblemCatalog as ProblemCatalogData,
  ProblemUseCase,
} from "../types";

type Props = {
  disabled: boolean;
  onGeometryContextChange: (context?: GeometryContext) => void;
  onPromptChange: (prompt: string) => void;
};

type CatalogData = {
  catalog: ProblemCatalogData;
  geometryFiles: Map<string, string>;
};

export function ProblemCatalog({
  disabled,
  onGeometryContextChange,
  onPromptChange,
}: Props) {
  const [data, setData] = useState<CatalogData | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [category, setCategory] = useState("all");
  const [error, setError] = useState("");
  const [isSelecting, setIsSelecting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadCatalog()
      .then((loaded) => {
        if (!cancelled) {
          setData(loaded);
          setError("");
        }
      })
      .catch((loadError: Error) => {
        if (!cancelled) {
          setError(loadError.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const categories = useMemo(
    () => [...new Set((data?.catalog.use_cases || []).map((item) => item.category))],
    [data],
  );
  const visibleUseCases = (data?.catalog.use_cases || []).filter(
    (item) => category === "all" || item.category === category,
  );
  const supportedCount = (data?.catalog.use_cases || []).filter(
    (item) => item.status === "immediate",
  ).length;

  async function selectUseCase(useCase: ProblemUseCase) {
    if (disabled || isSelecting || useCase.status !== "immediate" || !data) {
      return;
    }
    setIsSelecting(true);
    setError("");
    try {
      if (useCase.geometry_id) {
        const specPath = data.geometryFiles.get(useCase.geometry_id);
        if (!specPath) {
          throw new Error(`Geometry '${useCase.geometry_id}' is missing from the catalog.`);
        }
        const response = await fetch(`/geometries/${specPath}`, { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`Geometry request failed: ${response.status}`);
        }
        const spec = (await response.json()) as GeometrySpec;
        onGeometryContextChange({
          source: "standard",
          id: useCase.geometry_id,
          name: metadataText(spec, "title") || useCase.geometry_id,
          spec,
        });
      } else {
        onGeometryContextChange(undefined);
      }
      onPromptChange(useCase.prompt);
      setIsOpen(false);
    } catch (selectionError) {
      setError((selectionError as Error).message);
    } finally {
      setIsSelecting(false);
    }
  }

  return (
    <div className="problemCatalogControl">
      <button
        className="problemCatalogToggle"
        disabled={disabled}
        onClick={() => setIsOpen((value) => !value)}
        type="button"
      >
        Problem catalog
        {data ? <span>{supportedCount} ready / {data.catalog.use_cases.length} total</span> : null}
      </button>

      {isOpen ? (
        <section className="problemCatalogPanel">
          <header>
            <div>
              <strong>AES problem catalog</strong>
              <small>Select a ready use case, then edit its prompt before sending.</small>
            </div>
            <select
              aria-label="Filter problem catalog by category"
              onChange={(event) => setCategory(event.target.value)}
              value={category}
            >
              <option value="all">All families</option>
              {categories.map((item) => <option key={item} value={item}>{displayCategory(item)}</option>)}
            </select>
          </header>
          <div className="problemCatalogList">
            {visibleUseCases.map((useCase) => {
              const ready = useCase.status === "immediate";
              return (
                <button
                  className={`problemCatalogItem ${ready ? "ready" : "planned"}`}
                  disabled={!ready || disabled || isSelecting}
                  key={useCase.id}
                  onClick={() => void selectUseCase(useCase)}
                  title={
                    ready
                      ? "Load this editable prompt and its standard geometry"
                      : `Planned: ${useCase.required_capabilities.join(", ")}`
                  }
                  type="button"
                >
                  <span className="problemNumber">{useCase.number}</span>
                  <span className="problemCatalogText">
                    <strong>{useCase.title}</strong>
                    <code>{useCase.equation}</code>
                    {!ready ? <small>Planned: {supportLabel(useCase.status)}</small> : null}
                  </span>
                  <span className={`supportBadge ${useCase.status}`}>
                    {ready ? "Ready" : "Roadmap"}
                  </span>
                </button>
              );
            })}
          </div>
          {error ? <div className="viewerError">{error}</div> : null}
        </section>
      ) : error ? <div className="catalogInlineError">{error}</div> : null}
    </div>
  );
}

async function loadCatalog(): Promise<CatalogData> {
  const [catalogResponse, geometryResponse] = await Promise.all([
    fetch("/use-cases/catalog.json", { cache: "no-store" }),
    fetch("/geometries/index.json", { cache: "no-store" }),
  ]);
  if (!catalogResponse.ok) {
    throw new Error(`Problem catalog request failed: ${catalogResponse.status}`);
  }
  if (!geometryResponse.ok) {
    throw new Error(`Geometry catalog request failed: ${geometryResponse.status}`);
  }
  const catalog = (await catalogResponse.json()) as ProblemCatalogData;
  const geometryIndex = (await geometryResponse.json()) as GeometryExampleIndexItem[];
  if (catalog.schema_version !== "1.0" || !Array.isArray(catalog.use_cases)) {
    throw new Error("Problem catalog has an unsupported schema.");
  }
  return {
    catalog,
    geometryFiles: new Map(geometryIndex.map((item) => [item.id, item.spec])),
  };
}

function metadataText(spec: GeometrySpec, key: string) {
  const value = spec.metadata?.[key];
  return typeof value === "string" ? value : "";
}

function displayCategory(value: string) {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character: string) => character.toUpperCase());
}

function supportLabel(value: ProblemUseCase["status"]) {
  return value === "compiler_extension" ? "compiler extension" : "advanced backend";
}
