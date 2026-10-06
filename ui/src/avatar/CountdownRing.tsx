/**
 * The thin ring around the avatar while a request waits for your answer
 * (DESIGN.md section 5): it empties until the automatic refusal, since
 * silence is refusal. Updated once a second: a countdown in seconds needs no
 * more frames than that, and every frame of this window has a cost.
 */

import { useEffect, useState } from "react";

export function CountdownRing({
  deadline,
  total,
  size,
}: {
  /** Date.now() at which the request is refused. */
  deadline: number;
  /** Its full length, in ms. */
  total: number;
  size: number;
}) {
  const [left, setLeft] = useState(() => Math.max(0, deadline - Date.now()));
  useEffect(() => {
    const timer = setInterval(() => setLeft(Math.max(0, deadline - Date.now())), 1000);
    return () => clearInterval(timer);
  }, [deadline]);

  const radius = size / 2 - 2;
  const length = 2 * Math.PI * radius;
  return (
    <svg
      width={size}
      height={size}
      style={{ position: "absolute", inset: 0, pointerEvents: "none" }}
      aria-hidden="true"
    >
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="var(--lw-color-state-waiting)"
        strokeWidth={2}
        strokeLinecap="round"
        strokeDasharray={length}
        strokeDashoffset={length * (1 - left / total)}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
    </svg>
  );
}
