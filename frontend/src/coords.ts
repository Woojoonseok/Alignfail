import type { MouseEvent } from "react";

/**
 * Map a mouse event on an element that exactly covers the image to raw pixel
 * coordinates (top-left origin, rounded, clamped inside the image).
 */
export function pixelFromEvent(
  e: MouseEvent<Element>,
  width: number,
  height: number,
) {
  const r = e.currentTarget.getBoundingClientRect();
  const clamp = (value: number, size: number) =>
    Math.max(0, Math.min(size - 1, Math.round(value)));
  return {
    x: clamp(((e.clientX - r.left) / r.width) * width, width),
    y: clamp(((e.clientY - r.top) / r.height) * height, height),
  };
}
