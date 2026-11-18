/**
 * A short burst of confetti for a win, drawn on a canvas over the page. It
 * never blocks input, is hidden from assistive technology, cleans up after
 * itself, and is skipped entirely when the listener prefers reduced motion.
 */
import {useEffect, useRef, useState} from 'react';

const DURATION_MS = 2600;
const PIECES = 150;

interface Piece {
  x: number;
  y: number;
  vx: number;
  vy: number;
  size: number;
  spin: number;
  angle: number;
  color: string;
  round: boolean;
}

function palette(): string[] {
  const css = getComputedStyle(document.documentElement);
  const read = (name: string, fallback: string) =>
    css.getPropertyValue(name).trim() || fallback;
  return [
    read('--series-1', '#3987e5'),
    read('--series-2', '#d95926'),
    read('--series-3', '#199e70'),
    read('--brand', '#ff0000'),
    '#ffd54f',
    '#ffffff',
  ];
}

function reducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

/** Bursts once when mounted. Remount (change `key`) to burst again. */
export function Confetti() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [done, setDone] = useState(() => reducedMotion());

  useEffect(() => {
    const el = canvas.current;
    const ctx = el?.getContext('2d');
    if (!el || !ctx || done) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const w = window.innerWidth;
    const h = window.innerHeight;
    el.width = w * ratio;
    el.height = h * ratio;
    ctx.scale(ratio, ratio);
    const colors = palette();
    // Two cannons from the lower corners, aimed up and inwards.
    const pieces: Piece[] = Array.from({length: PIECES}, (_, i) => {
      const left = i % 2 === 0;
      const angle =
        (left ? -60 : -120) * (Math.PI / 180) + (Math.random() - 0.5) * 0.7;
      const speed = 11 + Math.random() * 9;
      return {
        x: left ? w * 0.08 : w * 0.92,
        y: h * 0.95,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        size: 6 + Math.random() * 6,
        spin: (Math.random() - 0.5) * 0.4,
        angle: Math.random() * Math.PI,
        color: colors[i % colors.length]!,
        round: Math.random() < 0.3,
      };
    });
    const start = performance.now();
    let frame = 0;
    function draw(now: number) {
      const t = now - start;
      ctx!.clearRect(0, 0, w, h);
      ctx!.globalAlpha = Math.max(
        0,
        1 - Math.max(0, t - DURATION_MS * 0.6) / (DURATION_MS * 0.4),
      );
      for (const p of pieces) {
        p.vy += 0.32;
        p.vx *= 0.985;
        p.vy *= 0.985;
        p.x += p.vx;
        p.y += p.vy;
        p.angle += p.spin;
        ctx!.save();
        ctx!.translate(p.x, p.y);
        ctx!.rotate(p.angle);
        ctx!.fillStyle = p.color;
        if (p.round) {
          ctx!.beginPath();
          ctx!.arc(0, 0, p.size / 2.4, 0, Math.PI * 2);
          ctx!.fill();
        } else {
          ctx!.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
        }
        ctx!.restore();
      }
      if (t < DURATION_MS) frame = requestAnimationFrame(draw);
      else setDone(true);
    }
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [done]);

  if (done) return null;
  return <canvas ref={canvas} className="confetti" aria-hidden="true" />;
}
