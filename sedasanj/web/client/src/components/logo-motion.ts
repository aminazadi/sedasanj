import { gsap } from "gsap";

export const LOGO_MOTION_DURATION = 1.6;
const PEN_TIMELINE_DURATION = 3.65;

export const PEN_STROKES = [
  { name: "sad-bowl", clip: "M397 70H482V130H397Z", path: "M454 99 C449 96 443 96 437 96 C427 96 420 100 417 106 C418 113 425 116 434 116 L405 116", width: 25, start: 0.1, time: 0.58 },
  { name: "sad-join", clip: "M340 74H406V130H340Z", path: "M405 116 C395 117 387 113 382 103 C381 116 373 120 364 117 C354 114 347 106 340 95", width: 25, start: 0.62, time: 0.5 },
  { name: "dal", clip: "M300 72H348V130H300Z", path: "M308 84 L323 84 C348 85 348 117 322 117 L310 117", width: 24, start: 1.03, time: 0.42 },
  { name: "alef", clip: "M273 38H299V130H273Z", path: "M286 51 L285 119", width: 27, start: 1.4, time: 0.3 },
  { name: "sin", clip: "M155 71H273V130H155Z", path: "M258 84 L258 99 C258 123 223 124 223 91 C223 124 185 125 185 93 C185 120 160 121 153 107", width: 24, start: 1.67, time: 0.75 },
  { name: "nun", clip: "M100 77H160V131H100Z", path: "M147 87 L147 98 C147 123 111 124 105 101", width: 25, start: 2.32, time: 0.35 },
  { name: "jim-head", clip: "M39 67H116V113H39Z", path: "M57 81 L86 80 C111 80 112 106 88 107 L66 107", width: 25, start: 2.62, time: 0.34 },
  { name: "jim-bowl", clip: "M39 98H105V148H39Z", path: "M84 107 L68 107 C43 108 47 138 65 138 L70 138", width: 24, start: 2.9, time: 0.31 },
  { name: "nun-dot", clip: "M134 51H160V76H134Z", path: "M147 64 L147 64.01", width: 24, start: 2.64, time: 0.19, dot: true },
  { name: "jim-dot", clip: "M76 123H102V149H76Z", path: "M89 136 L89 136.01", width: 24, start: 3.22, time: 0.19, dot: true },
] as const;

type Particle = { x: number; y: number; vx: number; vy: number; radius: number; life: number; age: number; color: string };
type Point = { x: number; y: number };

export function createLogoMotion(svg: SVGSVGElement, canvas: HTMLCanvasElement, duration: number, onComplete?: () => void) {
  const context = canvas.getContext("2d");
  const paths = Array.from(svg.querySelectorAll<SVGPathElement>("[data-pen-stroke]"));
  const artwork = svg.querySelector<SVGPathElement>("[data-logo-artwork]")!;
  const finish = svg.querySelector<SVGRectElement>("[data-mask-finish]")!;
  const particles: Particle[] = [];
  const speed = duration / PEN_TIMELINE_DURATION;
  const states = paths.map((path, index) => {
    const length = path.getTotalLength();
    const points = Array.from({ length: 161 }, (_, sample) => path.getPointAtLength(length * sample / 160));
    path.style.strokeDasharray = `${length} ${length}`;
    path.style.strokeDashoffset = `${length}`;
    if ("dot" in PEN_STROKES[index]) path.style.strokeWidth = "0";
    return { progress: 0, previous: 0, emission: 0, path, length, points, index };
  });
  let disposed = false;
  let completed = false;
  let tail = 0;
  let scale = 1;
  let offsetX = 0;
  let offsetY = 0;
  let ratio = 1;
  finish.style.opacity = "0";

  const resize = () => {
    const box = canvas.getBoundingClientRect();
    const logo = svg.getBoundingClientRect();
    ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(box.width * ratio);
    canvas.height = Math.round(box.height * ratio);
    scale = logo.width / 520;
    offsetX = logo.left - box.left;
    offsetY = logo.top - box.top;
  };
  const observer = new ResizeObserver(resize);
  observer.observe(svg);
  resize();

  const emit = (point: Point, tangent: Point, width: number, dot: boolean) => {
    const magnitude = Math.hypot(tangent.x, tangent.y) || 1;
    const side = Math.random() < 0.5 ? -1 : 1;
    const normal = { x: -tangent.y / magnitude * side, y: tangent.x / magnitude * side };
    if (dot) {
      const angle = Math.random() * Math.PI * 2;
      normal.x = Math.cos(angle);
      normal.y = Math.sin(angle);
    }
    let distance = width / 2 + 3;
    let x = point.x + normal.x * distance;
    let y = point.y + normal.y * distance;
    for (let attempt = 0; attempt < 5 && artwork.isPointInFill(new DOMPoint(x, y)); attempt++) {
      distance += 5;
      x = point.x + normal.x * distance;
      y = point.y + normal.y * distance;
    }
    particles.push({ x, y, vx: normal.x * (18 + Math.random() * 32) - 6, vy: normal.y * (18 + Math.random() * 30), radius: 1 + Math.random() * 2.3, life: 0.48 + Math.random() * 0.5, age: 0, color: Math.random() > 0.25 ? "169,133,64" : "75,110,72" });
  };

  const timeline = gsap.timeline({ onComplete: () => { completed = true; finish.style.opacity = "1"; onComplete?.(); } });
  states.forEach((state, index) => {
    const stroke = PEN_STROKES[index];
    timeline.to(state, {
      progress: 1,
      duration: stroke.time * speed,
      ease: "dot" in stroke ? "sine.out" : "none",
      onUpdate: () => {
        if ("dot" in stroke) {
          state.path.style.strokeDashoffset = "0";
          state.path.style.strokeWidth = `${stroke.width * state.progress}`;
        } else {
          state.path.style.strokeDashoffset = `${state.length * (1 - state.progress)}`;
        }
      },
    }, stroke.start * speed);
  });
  timeline.to(finish, { opacity: 1, duration: 0.08 * speed }, 3.41 * speed);
  timeline.to({}, { duration: 0.16 * speed });

  const tick = (_time: number, milliseconds: number) => {
    if (disposed || !context) return;
    const dt = Math.min(milliseconds / 1000, 0.04);
    states.forEach(state => {
      const stroke = PEN_STROKES[state.index];
      const distance = (state.progress - state.previous) * state.length;
      const dot = "dot" in stroke;
      state.emission += dot ? (state.progress - state.previous) * 28 : distance / 2.5;
      const count = Math.min(7, Math.floor(state.emission));
      state.emission -= count;
      for (let i = 0; i < count && particles.length < 160; i++) {
        const progress = state.previous + (state.progress - state.previous) * (i + 1) / count;
        const sample = Math.min(159, Math.floor(progress * 160));
        const a = state.points[sample];
        const b = state.points[sample + 1];
        const mix = progress * 160 - sample;
        emit({ x: a.x + (b.x - a.x) * mix, y: a.y + (b.y - a.y) * mix }, { x: b.x - a.x, y: b.y - a.y }, stroke.width, dot);
      }
      state.previous = state.progress;
    });
    context.setTransform(1, 0, 0, 1, 0, 0);
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.setTransform(scale * ratio, 0, 0, scale * ratio, offsetX * ratio, offsetY * ratio);
    for (let i = particles.length - 1; i >= 0; i--) {
      const particle = particles[i];
      particle.age += dt;
      if (particle.age >= particle.life) { particles.splice(i, 1); continue; }
      particle.vx *= Math.exp(-1.7 * dt);
      particle.vy *= Math.exp(-1.7 * dt);
      particle.x += particle.vx * dt;
      particle.y += particle.vy * dt;
      const remaining = 1 - particle.age / particle.life;
      const fadeIn = Math.min(particle.age / 0.06, 1);
      context.fillStyle = `rgba(${particle.color},${remaining * remaining * fadeIn * 0.85})`;
      context.beginPath();
      context.arc(particle.x, particle.y, particle.radius * (0.65 + remaining * 0.35), 0, Math.PI * 2);
      context.fill();
    }
    if (completed) {
      tail += dt;
      if (!particles.length || tail > 1.1) gsap.ticker.remove(tick);
    }
  };
  gsap.ticker.add(tick);
  return () => {
    disposed = true;
    timeline.kill();
    gsap.ticker.remove(tick);
    observer.disconnect();
    context?.clearRect(0, 0, canvas.width, canvas.height);
  };
}
