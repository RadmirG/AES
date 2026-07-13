import { openWebUiUrl } from "../config";

export function OpenWebUiFrame() {
  return (
    <div className="framePanel">
      <iframe title="Open WebUI" src={openWebUiUrl} />
      <p className="frameHint">
        If this panel stays blank, Open WebUI is blocking iframe embedding. Use
        the AES Chat tab instead.
      </p>
    </div>
  );
}

