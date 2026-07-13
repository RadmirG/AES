import "@kitware/vtk.js/Rendering/Profiles/Geometry";
import vtkActor from "@kitware/vtk.js/Rendering/Core/Actor";
import vtkMapper from "@kitware/vtk.js/Rendering/Core/Mapper";
import vtkFullScreenRenderWindow from "@kitware/vtk.js/Rendering/Misc/FullScreenRenderWindow";
import vtkXMLPolyDataReader from "@kitware/vtk.js/IO/XML/XMLPolyDataReader";
import { useEffect, useMemo, useRef, useState } from "react";
import type { AesArtifact, AesViewerManifest } from "../types";

type Props = {
  manifest: AesViewerManifest;
};

export function VtkResultViewer({ manifest }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [message, setMessage] = useState("");

  const dataset = useMemo(
    () => firstFetchableDataset(manifest.datasets.vtkjs_readable || []),
    [manifest],
  );

  useEffect(() => {
    if (!containerRef.current || !dataset) {
      return;
    }

    const renderWindow = vtkFullScreenRenderWindow.newInstance({
      container: containerRef.current,
      containerStyle: {
        height: "100%",
        width: "100%",
        position: "relative",
      },
      background: [0.02, 0.04, 0.1],
    });

    async function loadDataset() {
      try {
        const response = await fetch(dataset.url);
        if (!response.ok) {
          throw new Error(`Dataset request failed: ${response.status}`);
        }
        const buffer = await response.arrayBuffer();
        const reader = readerFor(dataset.artifact.name);
        if (!reader) {
          throw new Error(`Unsupported VTK.js dataset type: ${dataset.artifact.name}`);
        }
        reader.parseAsArrayBuffer(buffer);

        const mapper = vtkMapper.newInstance();
        mapper.setInputData(reader.getOutputData(0));
        const actor = vtkActor.newInstance();
        actor.setMapper(mapper);

        const renderer = renderWindow.getRenderer();
        renderer.addActor(actor);
        renderer.resetCamera();
        renderWindow.getRenderWindow().render();
        setMessage("");
      } catch (error) {
        setMessage((error as Error).message);
      }
    }

    loadDataset();

    return () => {
      renderWindow.delete();
    };
  }, [dataset]);

  if (!dataset) {
    return (
      <div className="viewerPlaceholder">
        <strong>No browser-fetchable VTK.js dataset yet</strong>
        <p>
          AES has diagnostics and preview artifacts. Interactive FEM rendering
          starts when a `.vtp` artifact is served over HTTP. Support for
          `.vtu` and `.vtkjs` conversion is planned in the next visualization
          postprocess step.
        </p>
      </div>
    );
  }

  return (
    <div className="vtkHost">
      <div ref={containerRef} className="vtkContainer" />
      {message ? <div className="viewerError">{message}</div> : null}
    </div>
  );
}

function firstFetchableDataset(artifacts: AesArtifact[]) {
  for (const artifact of artifacts) {
    if (!canReadDataset(artifact.name)) {
      continue;
    }
    const url = artifact.public_url || fetchableUrl(artifact.uri);
    if (url) {
      return { artifact, url };
    }
  }
  return null;
}

function fetchableUrl(uri: string) {
  if (uri.startsWith("http://") || uri.startsWith("https://") || uri.startsWith("/")) {
    return uri;
  }
  return "";
}

function readerFor(name: string) {
  if (canReadDataset(name)) {
    return vtkXMLPolyDataReader.newInstance();
  }
  return null;
}

function canReadDataset(name: string) {
  return name.toLowerCase().endsWith(".vtp");
}
