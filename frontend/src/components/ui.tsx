import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Check,
  Circle,
  Database,
  Image as ImageIcon,
  TriangleAlert,
  X,
} from "lucide-react";
import { imageUrl, type ImageRecord, type Pair } from "../api";

export function ErrorBox({ error }: { error: unknown }) {
  return error ? (
    <div className="error-box" role="alert">
      <TriangleAlert size={17} />
      <span>{error instanceof Error ? error.message : String(error)}</span>
    </div>
  ) : null;
}

export function Empty({
  icon = <Database size={28} />,
  title,
  children,
}: {
  icon?: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      <div>{children}</div>
    </div>
  );
}

export function Modal({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      aria-label={title}
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      className="modal"
    >
      <div className="modal-title">
        <h2>{title}</h2>
        <button className="icon-button" aria-label="닫기" onClick={close}>
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}

export function Status({ pair }: { pair: Pair }) {
  return !pair.enabled ? (
    <span className="badge muted">제외됨</span>
  ) : pair.import_issues.length ? (
    <span className="badge red">파일 확인</span>
  ) : pair.gt_x === null ? (
    <span className="badge amber">
      <Circle size={10} /> GT 미지정
    </span>
  ) : pair.gt_source === "auto_cross" ? (
    <span className="badge amber">
      <Circle size={10} /> 자동 GT · 확인 필요
    </span>
  ) : (
    <span className="badge green">
      <Check size={12} /> GT 완료
    </span>
  );
}

export function Thumb({ image }: { image: ImageRecord | null }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [image?.file_hash]);
  return (
    <div className="thumb">
      {image && !image.error && !failed ? (
        <img
          src={imageUrl(image, true)}
          alt={image.file_name}
          loading="lazy"
          onError={() => setFailed(true)}
        />
      ) : (
        <ImageIcon size={16} />
      )}
    </div>
  );
}
