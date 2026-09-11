import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Crosshair,
  Download,
  Eraser,
  Loader2,
  Minus,
  Plus,
  Save,
  ScanLine,
  Square,
  Trash2,
  Undo2,
  X,
} from "lucide-react";
import {
  api,
  imageUrl,
  type CleanupConfig,
  type ImageRecord,
  type PixelRect,
} from "./api";
import "./cleaner.css";

type Preview = {
  preview_url: string;
  mask_url: string;
  info: { masked_pixels: number; masked_fraction: number; noise_sigma: number };
};
type Detection = {
  box: PixelRect | null;
  cross: PixelRect | null;
  source_hash: string;
  box_coverage: number;
};

export default function ImageCleaner({
  image,
  close,
  saved,
}: {
  image: ImageRecord;
  close: () => void;
  saved: () => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const sourceViewport = useRef<HTMLDivElement>(null);
  const [fitWidth, setFitWidth] = useState(0);
  const [config, setConfig] = useState<CleanupConfig>(() =>
    image.cleanup && !image.cleanup.stale
      ? image.cleanup.config.parameters
      : {
          source_hash: image.file_hash!,
          box: null,
          cross: null,
          padding: 1,
          radius: 3,
          cross_noise: true,
        },
  );
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mode, setMode] = useState<"box" | "cross" | null>(null);
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null);
  const [message, setMessage] = useState(
    "자동 찾기 또는 직접 지정을 선택하세요. 네모는 테두리만, 십자선은 가로·세로 띠를 제거합니다.",
  );
  const [zoom, setZoom] = useState(1);
  const [showMask, setShowMask] = useState(true);
  const [imageFailed, setImageFailed] = useState(false);
  const width = image.width!,
    height = image.height!;
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  useEffect(() => {
    const viewport = sourceViewport.current;
    if (!viewport) return;
    const observer = new ResizeObserver(() => updateFitWidth());
    function updateFitWidth() {
      if (viewport)
        setFitWidth(
          Math.min(
            viewport.clientWidth,
            (viewport.clientHeight * width) / height,
          ),
        );
    }
    observer.observe(viewport);
    updateFitWidth();
    return () => observer.disconnect();
  }, [width, height]);
  const detect = useMutation({
    mutationFn: (_kind: "box" | "cross") =>
      api<Detection>(`/images/${image.id}/clean/detect`),
    onSuccess: (data, kind) => {
      setPreview(null);
      setMode(null);
      setAnchor(null);
      if (data.source_hash !== config.source_hash) {
        setMessage("이미지가 변경되었습니다. 닫고 폴더를 재검색하세요.");
        return;
      }
      setConfig((c) => ({ ...c, [kind]: data[kind] }));
      setMessage(
        data[kind]
          ? `${kind === "box" ? "네모" : "십자선"} 후보를 찾았습니다. 표시된 영역을 확인하고 미리보기를 실행하세요.`
          : `${kind === "box" ? "네모" : "십자선"}을 확실하게 찾지 못했습니다. 직접 지정으로 위치를 선택하세요.`,
      );
    },
  });
  const render = useMutation({
    mutationFn: () =>
      api<Preview>(`/images/${image.id}/clean/preview`, "POST", config),
    onSuccess: (data) => {
      setPreview(data);
      setMode(null);
      setAnchor(null);
    },
  });
  const save = useMutation({
    mutationFn: () => api(`/images/${image.id}/clean`, "POST", config),
    onSuccess: saved,
  });
  const reset = useMutation({
    mutationFn: () =>
      api(`/images/${image.id}/clean/reset`, "POST", {
        source_hash: image.file_hash,
      }),
    onSuccess: saved,
  });
  const busy =
    detect.isPending || render.isPending || save.isPending || reset.isPending;
  const error = detect.error || render.error || save.error || reset.error;
  function update(changes: Partial<CleanupConfig>) {
    setConfig((c) => ({ ...c, ...changes }));
    setPreview(null);
    render.reset();
    save.reset();
  }
  function start(kind: "box" | "cross") {
    setMode(kind);
    setAnchor(null);
    setMessage(
      kind === "box"
        ? "네모 테두리의 왼쪽 위와 오른쪽 아래 모서리를 차례로 클릭하세요."
        : "십자선의 교차점을 클릭하세요. 전체 가로·세로 선을 제거합니다.",
    );
  }
  function pick(x: number, y: number) {
    if (busy || !mode || imageFailed) return;
    if (mode === "cross") {
      update({ cross: { x0: x, x1: x, y0: y, y1: y } });
      setMode(null);
    } else if (!anchor) setAnchor({ x, y });
    else {
      update({
        box: {
          x0: Math.min(anchor.x, x),
          y0: Math.min(anchor.y, y),
          x1: Math.max(anchor.x, x),
          y1: Math.max(anchor.y, y),
        },
      });
      setMode(null);
      setAnchor(null);
    }
  }
  function rectFields(kind: "box" | "cross", rect: PixelRect) {
    return (
      <div className="cleanup-coords">
        {(["x0", "y0", "x1", "y1"] as const).map((key) => (
          <label key={key}>
            {key.toUpperCase()}
            <input
              aria-label={`${kind === "box" ? "네모" : "십자선"} ${key}`}
              type="number"
              min={0}
              max={key.startsWith("x") ? width - 1 : height - 1}
              value={rect[key]}
              onChange={(e) =>
                update({ [kind]: { ...rect, [key]: Number(e.target.value) } })
              }
            />
          </label>
        ))}
      </div>
    );
  }
  return (
    <dialog
      ref={dialog}
      aria-label="흰 표시 제거"
      className="modal cleanup-modal"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) close();
      }}
    >
      <div className="modal-title">
        <div>
          <h2>
            <Eraser size={19} /> 흰 표시 제거
          </h2>
          <p>
            {image.role} · {image.file_name} · {width} × {height}
          </p>
        </div>
        <button
          className="icon-button"
          aria-label="제거 창 닫기"
          disabled={busy}
          onClick={close}
        >
          <X size={20} />
        </button>
      </div>
      <div className="cleanup-body">
        <div className="cleanup-intro">
          흰 네모·십자선 부분을 주변 픽셀로 채웁니다. 원본과 GT는 그대로
          보존합니다.
        </div>
        <fieldset disabled={busy} className="cleanup-fieldset">
          <div className="cleanup-tools">
            <button
              className="button secondary"
              onClick={() => detect.mutate("box")}
            >
              <ScanLine size={15} /> 네모 자동 찾기
            </button>
            <button
              className={`button secondary ${mode === "box" ? "selected-tool" : ""}`}
              onClick={() => start("box")}
            >
              <Square size={15} /> 네모 직접 지정
            </button>
            <span className="tool-divider" />
            <button
              className="button secondary"
              onClick={() => detect.mutate("cross")}
            >
              <ScanLine size={15} /> 십자선 자동 찾기
            </button>
            <button
              className={`button secondary ${mode === "cross" ? "selected-tool" : ""}`}
              onClick={() => start("cross")}
            >
              <Crosshair size={15} /> 십자선 직접 지정
            </button>
          </div>
          <p className="cleanup-instruction" role="status">
            {detect.isPending ? "표시 위치를 찾는 중…" : message}
          </p>
          <div className="cleanup-images">
            <section>
              <header>
                <strong>원본 · 제거할 영역</strong>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={showMask}
                    onChange={(e) => setShowMask(e.target.checked)}
                  />{" "}
                  영역 표시
                </label>
              </header>
              <div className="cleanup-viewport" ref={sourceViewport}>
                <div
                  className="cleanup-stage"
                  style={{ width: fitWidth ? `${fitWidth * zoom}px` : "100%" }}
                >
                  <img
                    src={imageUrl(image)}
                    alt="제거 전 원본"
                    draggable={false}
                    onError={() => setImageFailed(true)}
                  />
                  <svg
                    aria-label="제거 영역 지정"
                    className={mode ? "drawing" : ""}
                    viewBox={`0 0 ${width} ${height}`}
                    onClick={(e) => {
                      const r = e.currentTarget.getBoundingClientRect();
                      pick(
                        Math.max(
                          0,
                          Math.min(
                            width - 1,
                            Math.round(
                              ((e.clientX - r.left) / r.width) * width,
                            ),
                          ),
                        ),
                        Math.max(
                          0,
                          Math.min(
                            height - 1,
                            Math.round(
                              ((e.clientY - r.top) / r.height) * height,
                            ),
                          ),
                        ),
                      );
                    }}
                  >
                    {showMask && config.box && (
                      <rect
                        x={config.box.x0}
                        y={config.box.y0}
                        width={Math.max(0, config.box.x1 - config.box.x0)}
                        height={Math.max(0, config.box.y1 - config.box.y0)}
                        fill="none"
                        stroke="#ff6b72"
                        strokeWidth={2 * config.padding + 1}
                        opacity={0.8}
                      />
                    )}
                    {showMask && config.cross && (
                      <g fill="#ff6b72" opacity={0.65}>
                        <rect
                          x={Math.max(0, config.cross.x0 - config.padding)}
                          y={0}
                          width={
                            config.cross.x1 -
                            config.cross.x0 +
                            1 +
                            2 * config.padding
                          }
                          height={height}
                        />
                        <rect
                          x={0}
                          y={Math.max(0, config.cross.y0 - config.padding)}
                          width={width}
                          height={
                            config.cross.y1 -
                            config.cross.y0 +
                            1 +
                            2 * config.padding
                          }
                        />
                      </g>
                    )}
                    {anchor && (
                      <circle
                        cx={anchor.x}
                        cy={anchor.y}
                        r={5 / zoom}
                        fill="#ffdf5c"
                      />
                    )}
                  </svg>
                </div>
              </div>
            </section>
            <section>
              <header>
                <strong>제거 후 미리보기</strong>
                {preview && (
                  <span className="badge green">아직 저장되지 않음</span>
                )}
              </header>
              <div className="cleanup-viewport">
                {preview ? (
                  <div
                    className="cleanup-stage"
                    style={{
                      width: fitWidth ? `${fitWidth * zoom}px` : "100%",
                    }}
                  >
                    <img
                      src={preview.preview_url}
                      alt="흰 표시 제거 미리보기"
                    />
                  </div>
                ) : (
                  <div className="cleanup-placeholder">
                    {render.isPending ? (
                      <Loader2 className="spin" size={30} />
                    ) : (
                      <Eraser size={30} />
                    )}
                    <p>
                      {render.isPending
                        ? "선 부분을 채우는 중…"
                        : "영역을 지정하고 미리보기를 누르세요."}
                    </p>
                  </div>
                )}
              </div>
            </section>
          </div>
          <div className="cleanup-zoom">
            <span>확대 후 스크롤로 이동 · 두 화면에 동일한 확대율 적용</span>
            <button
              className="icon-button"
              aria-label="제거 화면 축소"
              disabled={zoom <= 1 || busy}
              onClick={() => setZoom((z) => Math.max(1, z - 0.5))}
            >
              <Minus size={14} />
            </button>
            <span>{zoom === 1 ? "Fit" : `${zoom * 100}%`}</span>
            <button
              className="icon-button"
              aria-label="제거 화면 확대"
              disabled={zoom >= 4 || busy}
              onClick={() => setZoom((z) => Math.min(4, z + 0.5))}
            >
              <Plus size={14} />
            </button>
          </div>
          <div className="cleanup-options">
            <section>
              <h3>
                네모 테두리{" "}
                {config.box && (
                  <button
                    className="icon-button"
                    aria-label="네모 영역 해제"
                    onClick={() => {
                      update({ box: null });
                      setAnchor(null);
                      setMode(null);
                    }}
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </h3>
              {config.box ? (
                rectFields("box", config.box)
              ) : (
                <p>지정되지 않음</p>
              )}
            </section>
            <section>
              <h3>
                십자선 띠{" "}
                {config.cross && (
                  <button
                    className="icon-button"
                    aria-label="십자선 영역 해제"
                    onClick={() => {
                      update({ cross: null });
                      setAnchor(null);
                      setMode(null);
                    }}
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </h3>
              {config.cross ? (
                rectFields("cross", config.cross)
              ) : (
                <p>지정되지 않음</p>
              )}
            </section>
            <section>
              <h3>채우기 설정</h3>
              <div className="cleanup-coords">
                <label>
                  여유 폭 (px)
                  <input
                    aria-label="제거 여유 폭"
                    type="number"
                    min={0}
                    max={5}
                    value={config.padding}
                    onChange={(e) =>
                      update({ padding: Number(e.target.value) })
                    }
                  />
                </label>
                <label>
                  복원 반경 (px)
                  <input
                    aria-label="복원 반경"
                    type="number"
                    min={1}
                    max={10}
                    value={config.radius}
                    onChange={(e) => update({ radius: Number(e.target.value) })}
                  />
                </label>
              </div>
              <label className="cleanup-noise">
                <input
                  type="checkbox"
                  checked={config.cross_noise}
                  onChange={(e) => update({ cross_noise: e.target.checked })}
                />{" "}
                십자선 채움에 주변 질감 노이즈 추가
              </label>
            </section>
          </div>
        </fieldset>
        {imageFailed && (
          <div className="error-box" role="alert">
            원본 이미지를 불러오지 못했습니다. 닫고 폴더를 재검색하세요.
          </div>
        )}
        {error && (
          <div className="error-box" role="alert">
            {error.message}
          </div>
        )}
        <div className="cleanup-bottom">
          <span>
            {preview
              ? `제거 영역 ${preview.info.masked_pixels.toLocaleString()} px · ${(preview.info.masked_fraction * 100).toFixed(2)}%`
              : "Clean PNG와 제거 마스크를 별도로 저장합니다."}
          </span>
          {image.cleanup && (
            <>
              <a
                className="button secondary"
                href={`/api/cleanups/${image.cleanup.id}/image?download=true`}
              >
                <Download size={14} /> 저장된 PNG
              </a>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => reset.mutate()}
              >
                <Undo2 size={14} /> 원본 사용으로 되돌리기
              </button>
            </>
          )}
          <button
            className="button secondary"
            disabled={
              busy || imageFailed || (!config.box && !config.cross) || !!anchor
            }
            onClick={() => render.mutate()}
          >
            {render.isPending ? (
              <Loader2 className="spin" size={15} />
            ) : (
              <Eraser size={15} />
            )}{" "}
            제거 미리보기
          </button>
          <button
            className="button primary"
            disabled={busy || !preview || imageFailed}
            onClick={() => save.mutate()}
          >
            {save.isPending ? (
              <Loader2 className="spin" size={15} />
            ) : (
              <Save size={15} />
            )}{" "}
            Clean 이미지 저장
          </button>
        </div>
      </div>
    </dialog>
  );
}
