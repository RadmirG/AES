import "@kitware/vtk.js/Rendering/Profiles/Geometry";
import vtkActor from "@kitware/vtk.js/Rendering/Core/Actor";
import vtkCellPicker from "@kitware/vtk.js/Rendering/Core/CellPicker";
import vtkMapper from "@kitware/vtk.js/Rendering/Core/Mapper";
import vtkFullScreenRenderWindow from "@kitware/vtk.js/Rendering/Misc/FullScreenRenderWindow";
import vtkXMLPolyDataReader from "@kitware/vtk.js/IO/XML/XMLPolyDataReader";
import { useEffect, useRef, useState } from "react";
import { buildGeometrySurfaces } from "../geometryPolyData";
import type { GeometrySpec } from "../types";

type Props = {
  geometry: GeometrySpec | null;
  uploadedVtp: ArrayBuffer | null;
  uploadedName: string;
};

type ActorEntry = {
  actor: ReturnType<typeof vtkActor.newInstance>;
  color: [number, number, number];
  kind: "surface" | "line";
  name: string;
};

export function GeometryVtkViewer({ geometry, uploadedVtp, uploadedName }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [selectedRegion, setSelectedRegion] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    const container = containerRef.current;
    if (!container || (!geometry && !uploadedVtp)) {
      return;
    }

    container.replaceChildren();
    const renderWindow = vtkFullScreenRenderWindow.newInstance({
      container,
      containerStyle: {
        height: "100%",
        width: "100%",
        position: "relative",
      },
      background: [0.95, 0.97, 0.99],
    });
    const renderer = renderWindow.getRenderer();
    const actors: ActorEntry[] = [];
    setSelectedRegion("");

    try {
      if (uploadedVtp) {
        const reader = vtkXMLPolyDataReader.newInstance();
        reader.parseAsArrayBuffer(uploadedVtp);
        const mapper = vtkMapper.newInstance();
        mapper.setInputData(reader.getOutputData(0));
        const actor = vtkActor.newInstance();
        actor.setMapper(mapper);
        actor.getProperty().setColor(0.13, 0.64, 0.54);
        actor.getProperty().setEdgeVisibility(true);
        actor.getProperty().setEdgeColor(0.18, 0.25, 0.34);
        renderer.addActor(actor);
        actors.push({ actor, color: [0.13, 0.64, 0.54], kind: "surface", name: uploadedName });
      } else if (geometry) {
        for (const item of buildGeometrySurfaces(geometry)) {
          const mapper = vtkMapper.newInstance();
          mapper.setInputData(item.data);
          const actor = vtkActor.newInstance();
          actor.setMapper(mapper);
          actor.getProperty().setColor(...item.color);
          if (item.kind === "line") {
            actor.getProperty().setLineWidth(5);
          } else {
            actor.getProperty().setEdgeVisibility(true);
            actor.getProperty().setEdgeColor(0.27, 0.34, 0.43);
            actor.getProperty().setOpacity(0.9);
          }
          renderer.addActor(actor);
          actors.push({ actor, color: item.color, kind: item.kind, name: item.name });
        }
      }

      const picker = vtkCellPicker.newInstance();
      picker.setPickFromList(1);
      picker.initializePickList();
      actors.forEach((entry) => picker.addPickList(entry.actor));

      const subscription = renderWindow.getInteractor().onLeftButtonPress((event) => {
        const position = event.position;
        if (!position) {
          return;
        }
        picker.pick([position.x, position.y, 0], renderer);
        const picked = picker.getActors()[0];
        const selected = actors.find((entry) => entry.actor === picked);
        actors.forEach((entry) => {
          const active = entry === selected;
          const color: [number, number, number] = active
            ? [0.98, 0.75, 0.16]
            : entry.color;
          entry.actor.getProperty().setColor(...color);
          if (entry.kind === "surface") {
            entry.actor.getProperty().setOpacity(active ? 1 : 0.9);
          }
        });
        setSelectedRegion(selected?.name || "");
        renderWindow.getRenderWindow().render();
      });

      renderer.resetCamera();
      const bounds = renderer.computeVisiblePropBounds();
      const center = [
        (bounds[0] + bounds[1]) / 2,
        (bounds[2] + bounds[3]) / 2,
        (bounds[4] + bounds[5]) / 2,
      ];
      const span = Math.max(
        bounds[1] - bounds[0],
        bounds[3] - bounds[2],
        bounds[5] - bounds[4],
        1.0e-6,
      );
      const camera = renderer.getActiveCamera();
      camera.setFocalPoint(center[0], center[1], center[2]);
      if (geometry?.dimension === 2) {
        camera.setPosition(center[0], center[1], center[2] + 2 * span);
        camera.setViewUp(0, 1, 0);
        camera.setParallelProjection(true);
        camera.setParallelScale(span * 0.6);
      } else {
        camera.setPosition(
          center[0] + 1.2 * span,
          center[1] - 1.2 * span,
          center[2] + 1.8 * span,
        );
        camera.setViewUp(0, 0, 1);
        camera.setParallelProjection(false);
      }
      renderer.resetCameraClippingRange();
      renderWindow.getRenderWindow().render();
      setMessage("");

      return () => {
        subscription.unsubscribe();
        picker.delete();
        renderWindow.delete();
        container.replaceChildren();
      };
    } catch (error) {
      setMessage((error as Error).message);
      renderWindow.delete();
      container.replaceChildren();
      return undefined;
    }
  }, [geometry, uploadedName, uploadedVtp]);

  return (
    <div className="geometryViewerShell">
      <div ref={containerRef} className="geometryVtkContainer" />
      <div className="viewerInteractionHint">Drag to rotate · wheel to zoom · click a region</div>
      {selectedRegion ? (
        <div className="selectedRegionBadge">Selected region: <strong>{selectedRegion}</strong></div>
      ) : null}
      {message ? <div className="viewerError geometryViewerError">{message}</div> : null}
    </div>
  );
}
