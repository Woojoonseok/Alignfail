import { useEffect, useRef, useState } from "react";
import { api, imageUrl, cleanImageUrl, type Pair } from "./api";

export default function ReferenceROI({
  pair,
  close,
  saved,
}: {
  pair: Pair;
  close: () => void;
  saved: () => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const im = pair.reference!;
  const [box, setBox] = useState(
    pair.reference_annotation?.image_hash === im.file_hash
      ? pair.reference_annotation.box
      : [0, 0, im.width! - 1, im.height! - 1],
  );
  const [anchor, setAnchor] = useState<number[] | null>(null);
  const [drawing, setDrawing] = useState(false);
  const [source, setSource] = useState("ref_box_manual");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <dialog
      className="modal roi-modal"
      ref={dialog}
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) close();
      }}
    >
      <div className="modal-title">
        <div>
          <h2>REF 대상 ROI</h2>
          <p>두 모서리의 원본 픽셀 좌표 · 중심은 두 모서리의 평균</p>
        </div>
        <button
          className="icon-button"
          disabled={busy}
          onClick={close}
          aria-label="REF ROI 닫기"
        >
          ✕
        </button>
      </div>
      <div className="training-body">
        <fieldset disabled={busy}>
          <div className="training-controls">
            <button
              className="button secondary"
              onClick={() => {
                setDrawing(true);
                setAnchor(null);
              }}
            >
              두 모서리 직접 지정
            </button>
            <button
              className="button secondary"
              onClick={() =>
                action(async () => {
                  const found = await api<{
                    box: {
                      x0: number;
                      y0: number;
                      x1: number;
                      y1: number;
                    } | null;
                  }>(`/images/${im.id}/clean/detect`);
                  if (!found.box)
                    throw new Error("네모 후보 없음. 직접 지정하세요.");
                  setBox([
                    found.box.x0,
                    found.box.y0,
                    found.box.x1,
                    found.box.y1,
                  ]);
                  setSource("ref_box_auto");
                  setDrawing(false);
                })
              }
            >
              흰 네모에서 ROI 후보 찾기
            </button>
          </div>
          <p>
            {drawing
              ? anchor
                ? "두 번째 모서리를 클릭하세요."
                : "첫 번째 모서리를 클릭하세요."
              : "초기 전체 영역 또는 표시된 ROI를 확인하고 저장하세요. 흰 표시 제거 설정과 별개입니다."}
          </p>
          <div className="roi-canvas">
            <img
              src={
                im.cleanup && !im.cleanup.stale
                  ? cleanImageUrl(im)
                  : imageUrl(im)
              }
              alt="REF ROI 원본"
            />
            <svg
              aria-label="REF ROI 지정 영역"
              viewBox={`0 0 ${im.width} ${im.height}`}
              onClick={(e) => {
                if (!drawing || busy) return;
                const r = e.currentTarget.getBoundingClientRect();
                const p = [
                  Math.min(
                    im.width! - 1,
                    Math.max(
                      0,
                      Math.round(((e.clientX - r.left) / r.width) * im.width!),
                    ),
                  ),
                  Math.min(
                    im.height! - 1,
                    Math.max(
                      0,
                      Math.round(((e.clientY - r.top) / r.height) * im.height!),
                    ),
                  ),
                ];
                if (!anchor) setAnchor(p);
                else {
                  setBox([
                    Math.min(anchor[0], p[0]),
                    Math.min(anchor[1], p[1]),
                    Math.max(anchor[0], p[0]),
                    Math.max(anchor[1], p[1]),
                  ]);
                  setAnchor(null);
                  setDrawing(false);
                  setSource("ref_box_manual");
                }
              }}
            >
              <rect
                x={box[0]}
                y={box[1]}
                width={box[2] - box[0]}
                height={box[3] - box[1]}
                fill="rgba(27,190,120,.12)"
                stroke="#4affac"
                strokeWidth={2}
              />
              <circle
                cx={(box[0] + box[2]) / 2}
                cy={(box[1] + box[3]) / 2}
                r={3}
                fill="#ffdc63"
              />
            </svg>
          </div>
          <div className="training-controls">
            {["x0", "y0", "x1", "y1"].map((label, i) => (
              <label key={label}>
                {label}
                <input
                  type="number"
                  step="0.5"
                  aria-label={`REF ROI ${label}`}
                  value={box[i]}
                  onChange={(e) => {
                    setBox(
                      box.map((v, j) => (i === j ? Number(e.target.value) : v)),
                    );
                    setSource("ref_box_manual");
                  }}
                />
              </label>
            ))}
          </div>
          <p>
            Center: {((box[0] + box[2]) / 2).toFixed(2)},{" "}
            {((box[1] + box[3]) / 2).toFixed(2)}
          </p>
          <button
            className="button primary"
            onClick={() =>
              action(async () => {
                await api(`/pairs/${pair.id}/reference-annotation`, "PUT", {
                  revision: pair.revision,
                  image_hash: im.file_hash,
                  box,
                  source,
                });
                await saved();
              })
            }
          >
            REF ROI 저장
          </button>
        </fieldset>
        {error && <p className="error-box">{error}</p>}
      </div>
    </dialog>
  );
}
