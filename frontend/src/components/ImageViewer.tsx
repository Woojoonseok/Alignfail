import { useEffect, useState } from "react";
import {
  Eraser,
  Image as ImageIcon,
  Maximize,
  Minus,
  Plus,
} from "lucide-react";
import { imageUrl, cleanImageUrl, type ImageRecord } from "../api";
import { pixelFromEvent } from "../coords";

export function ImageViewer({
  image,
  title,
  gt,
  onPick,
  zoom,
  setZoom,
  showGT,
  onClean,
  emptyHint,
}: {
  image: ImageRecord | null;
  title: string;
  gt?: { x: number | null; y: number | null };
  onPick?: (x: number, y: number) => void;
  zoom: number;
  setZoom: (n: number) => void;
  showGT: boolean;
  onClean?: () => void;
  emptyHint?: string;
}) {
  const [failed, setFailed] = useState(false);
  const [hover, setHover] = useState<{ x: number; y: number } | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [cleanView, setCleanView] = useState(
    !!image?.cleanup && !image.cleanup.stale,
  );
  useEffect(() => {
    setFailed(false);
    setLoaded(false);
  }, [cleanView]);
  const markerSize = image?.width ? Math.max(5, image.width / 65 / zoom) : 6;
  return (
    <section className="viewer">
      <div className="viewer-heading">
        <span>
          <span className={`viewer-role ${onPick ? "query" : ""}`}>
            {title}
          </span>
          {onPick ? "정답 위치 지정" : "기준 이미지"}
        </span>
        <span>{image?.width && `${image.width} × ${image.height}`}</span>
      </div>
      <div className="viewer-clean-controls">
        <button
          disabled={!onClean || !image || !!image.error}
          onClick={onClean}
          aria-label={`${title} 흰 표시 제거`}
        >
          <Eraser size={13} /> 흰 표시 제거
        </button>
        {image?.cleanup && !image.cleanup.stale && (
          <button
            className={`clean-toggle ${cleanView ? "active" : ""}`}
            onClick={() => setCleanView((v) => !v)}
            aria-label={`${title} 원본 Clean 전환`}
          >
            {cleanView ? "Clean · 원본 보기" : "원본 · Clean 보기"}
          </button>
        )}
        {image?.cleanup?.stale && <span>제거 결과 재생성 필요</span>}
      </div>
      <div className={`image-viewport ${zoom === 1 ? "fit" : ""}`}>
        {!image || image.error || failed ? (
          <div className="viewer-empty">
            <ImageIcon size={30} />
            <strong>
              {image?.error ||
                (failed
                  ? "이미지를 불러올 수 없습니다."
                  : `${title} 이미지가 없습니다.`)}
            </strong>
            <span>{emptyHint ?? "파일과 폴더 재검색 결과를 확인하세요."}</span>
          </div>
        ) : (
          <div
            className={`image-stage ${zoom === 1 ? "fit" : ""}`}
            style={zoom === 1 ? undefined : { width: `${zoom * 100}%` }}
          >
            <img
              src={
                cleanView && image.cleanup
                  ? cleanImageUrl(image)
                  : imageUrl(image)
              }
              alt={`${title}: ${image.file_name}`}
              draggable={false}
              onLoad={() => setLoaded(true)}
              onError={() => setFailed(true)}
            />
            {loaded && image.width && image.height && (
              <svg
                aria-label={
                  onPick ? "Query GT 지정 영역" : "Reference 이미지 영역"
                }
                className={onPick ? "image-overlay editable" : "image-overlay"}
                viewBox={`0 0 ${image.width} ${image.height}`}
                onMouseMove={(e) =>
                  setHover(pixelFromEvent(e, image.width!, image.height!))
                }
                onMouseLeave={() => setHover(null)}
                onClick={(e) => {
                  if (!onPick) return;
                  const { x, y } = pixelFromEvent(
                    e,
                    image.width!,
                    image.height!,
                  );
                  onPick(x, y);
                }}
              >
                {showGT &&
                  gt?.x !== null &&
                  gt?.x !== undefined &&
                  gt.y !== null && (
                    <g
                      transform={`translate(${gt.x},${gt.y})`}
                      pointerEvents="none"
                    >
                      <circle
                        r={markerSize}
                        fill="rgba(255,216,78,.14)"
                        stroke="#ffdf5c"
                        strokeWidth={2}
                        vectorEffect="non-scaling-stroke"
                      />
                      <circle r={markerSize / 4} fill="#ffdf5c" />
                      <path
                        d={`M ${-markerSize * 1.65} 0 H ${-markerSize * 0.65} M ${markerSize * 0.65} 0 H ${markerSize * 1.65} M 0 ${-markerSize * 1.65} V ${-markerSize * 0.65} M 0 ${markerSize * 0.65} V ${markerSize * 1.65}`}
                        stroke="#ffdf5c"
                        strokeWidth={1.5}
                        vectorEffect="non-scaling-stroke"
                      />
                    </g>
                  )}
              </svg>
            )}
          </div>
        )}
      </div>
      <div className="viewer-toolbar">
        <span className="viewer-filename" title={image?.file_name}>
          {hover
            ? `X ${hover.x} · Y ${hover.y}`
            : (image?.file_name ?? "No image")}
        </span>
        <div>
          <button
            className="icon-button"
            disabled={zoom <= 1}
            aria-label={`${title} 축소`}
            onClick={() => setZoom(Math.max(1, zoom - 0.5))}
          >
            <Minus size={14} />
          </button>
          <span className="zoom-label">
            {zoom === 1 ? "Fit" : `${Math.round(zoom * 100)}%`}
          </span>
          <button
            className="icon-button"
            disabled={zoom >= 6}
            aria-label={`${title} 확대`}
            onClick={() => setZoom(Math.min(6, zoom + 0.5))}
          >
            <Plus size={14} />
          </button>
          <button
            className="icon-button"
            aria-label={`${title} 화면 맞춤`}
            onClick={() => setZoom(1)}
          >
            <Maximize size={14} />
          </button>
        </div>
      </div>
    </section>
  );
}
