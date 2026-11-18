/**
 * Artist photos for the canvas, decoded once and kept as small round sprites.
 *
 * A web of ~150 artists redraws up to 60 times a second while it settles, so a
 * frame must never decode, crop or clip an image: each photo is loaded once,
 * cropped to a circle on the face (the upper third, as `.cover__img` frames it)
 * at a fixed size, and from then on drawn with a single drawImage. A photo
 * that fails to load is remembered as failed and the generated cover stays.
 *
 * Photos load with CORS (Wikimedia allows it), so drawing them leaves the
 * canvas readable: the web's share image reads it back. A host without CORS
 * fails the load, and the generated cover is drawn instead.
 */

/** Sprite size in device pixels: sharp up to a 32px node at 2x. */
const SIZE = 128;
/** Sprites are 64 KB each; past this many the least recently added go. */
const MAX_ENTRIES = 360;

export interface Photo {
  state: 'loading' | 'ready' | 'failed';
  sprite: HTMLCanvasElement | null;
  /** When the sprite became ready (performance.now()), for the fade-in. */
  readyAt: number;
}

const cache = new Map<string, Photo>();
const listeners = new Set<() => void>();

/** Called whenever a photo finishes loading, so a web can redraw. */
export function onPhotoReady(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function crop(image: HTMLImageElement): HTMLCanvasElement | null {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = SIZE;
  const context = canvas.getContext('2d');
  const w = image.naturalWidth;
  const h = image.naturalHeight;
  if (!context || !w || !h) return null;
  const side = Math.min(w, h);
  const sx = (w - side) / 2;
  // Portraits: the face sits in the upper third, so crop from there.
  const sy = (h - side) * 0.22;
  context.beginPath();
  context.arc(SIZE / 2, SIZE / 2, SIZE / 2, 0, 2 * Math.PI);
  context.clip();
  context.imageSmoothingQuality = 'high';
  context.drawImage(image, sx, sy, side, side, 0, 0, SIZE, SIZE);
  // A faint inner shade at the rim, so a pale photo still reads as a disc.
  const rim = context.createRadialGradient(
    SIZE / 2,
    SIZE / 2,
    SIZE * 0.36,
    SIZE / 2,
    SIZE / 2,
    SIZE / 2,
  );
  rim.addColorStop(0, 'rgb(0 0 0 / 0%)');
  rim.addColorStop(1, 'rgb(0 0 0 / 28%)');
  context.fillStyle = rim;
  context.fillRect(0, 0, SIZE, SIZE);
  return canvas;
}

function load(url: string, entry: Photo): void {
  const image = new Image();
  image.decoding = 'async';
  image.referrerPolicy = 'no-referrer';
  // Wikimedia serves photos with CORS, so drawing them keeps the canvas
  // readable (the web's share image reads it back).
  image.crossOrigin = 'anonymous';
  const fail = () => {
    entry.state = 'failed';
  };
  image.onload = () => {
    const decoded = image.decode ? image.decode() : Promise.resolve();
    decoded
      .catch(() => undefined)
      .then(() => {
        const sprite = crop(image);
        if (!sprite) return fail();
        entry.sprite = sprite;
        entry.state = 'ready';
        entry.readyAt = performance.now();
        listeners.forEach(listener => listener());
      })
      .catch(fail);
  };
  image.onerror = fail;
  image.src = url;
}

/** The photo for a URL, starting its load the first time it is asked for. */
export function photoFor(url: string): Photo {
  let entry = cache.get(url);
  if (!entry) {
    entry = {state: 'loading', sprite: null, readyAt: 0};
    cache.set(url, entry);
    if (cache.size > MAX_ENTRIES) {
      const oldest = cache.keys().next().value;
      if (oldest !== undefined) cache.delete(oldest);
    }
    load(url, entry);
  }
  return entry;
}
