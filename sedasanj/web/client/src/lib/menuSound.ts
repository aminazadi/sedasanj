// Soft synthesized hover notes for the sidebar. No audio assets; Web Audio only.
const STORAGE_KEY = "sedasanj.menuSound";
const MIN_GAP_MS = 60;

export type MenuSoundId = "off" | "kalimba" | "marimba" | "celesta";

export const MENU_SOUNDS: ReadonlyArray<{ id: MenuSoundId; label: string }> = [
  { id: "off", label: "بی‌صدا" },
  { id: "kalimba", label: "کالیمبا" },
  { id: "marimba", label: "ماریمبا" },
  { id: "celesta", label: "سلستا" },
];

// C major pentatonic over two octaves: any two notes sound consonant, so hovering down the
// menu plays a soft ascending phrase instead of repeated identical clicks.
const SCALE = [523.25, 587.33, 659.25, 783.99, 880, 1046.5, 1174.66, 1318.51];

const DEFAULT_SOUND: MenuSoundId = "kalimba";

let context: AudioContext | null = null;
let lastPlayed = 0;

type AudioWindow = Window & { webkitAudioContext?: typeof AudioContext };

export function getMenuSound(): MenuSoundId {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "0") return "off";
    return MENU_SOUNDS.find((sound) => sound.id === stored)?.id ?? DEFAULT_SOUND;
  } catch {
    return DEFAULT_SOUND;
  }
}

export function setMenuSound(id: MenuSoundId): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // Storage can be blocked; the choice then lasts for this page view only.
  }
}

export function menuSoundLabel(id: MenuSoundId): string {
  return MENU_SOUNDS.find((sound) => sound.id === id)?.label ?? "";
}

export function nextMenuSound(current: MenuSoundId): MenuSoundId {
  const index = MENU_SOUNDS.findIndex((sound) => sound.id === current);
  return MENU_SOUNDS[(index + 1) % MENU_SOUNDS.length].id;
}

// Browsers only allow audio after a user gesture, so the context is created on the first one.
function arm(): void {
  const create = () => {
    if (context) return;
    const Ctor = window.AudioContext ?? (window as AudioWindow).webkitAudioContext;
    if (!Ctor) return;
    try {
      context = new Ctor();
    } catch {
      context = null;
    }
  };
  window.addEventListener("pointerdown", create, { once: true, passive: true });
  window.addEventListener("keydown", create, { once: true, passive: true });
}
if (typeof window !== "undefined") arm();

let reverb: ConvolverNode | null = null;

// A short synthetic room tail gives the notes some air; built once per context.
function getReverb(ctx: AudioContext): ConvolverNode {
  if (reverb) return reverb;
  const seconds = 1.4;
  const length = Math.floor(ctx.sampleRate * seconds);
  const impulse = ctx.createBuffer(2, length, ctx.sampleRate);
  for (let channel = 0; channel < 2; channel += 1) {
    const data = impulse.getChannelData(channel);
    for (let i = 0; i < length; i += 1) data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / length, 3.2);
  }
  reverb = ctx.createConvolver();
  reverb.buffer = impulse;
  const wet = ctx.createGain();
  wet.gain.value = 0.35;
  reverb.connect(wet).connect(ctx.destination);
  return reverb;
}

type Partial = { ratio: number; level: number; decay: number };

const TIMBRES: Record<Exclude<MenuSoundId, "off">, { octave: number; attack: number; partials: Partial[] }> = {
  // Thumb piano: pure fundamental with a quickly fading metallic overtone.
  kalimba: { octave: 1, attack: 0.002, partials: [{ ratio: 1, level: 1, decay: 0.55 }, { ratio: 5.4, level: 0.12, decay: 0.07 }] },
  // Wooden bar: warm, lower and shorter, with a short 4th-harmonic knock.
  marimba: { octave: 0.5, attack: 0.002, partials: [{ ratio: 1, level: 1, decay: 0.38 }, { ratio: 4, level: 0.22, decay: 0.09 }] },
  // Celesta: soft attack, gentle harmonics, longer ring.
  celesta: { octave: 1, attack: 0.008, partials: [{ ratio: 1, level: 1, decay: 0.8 }, { ratio: 2, level: 0.3, decay: 0.5 }, { ratio: 3, level: 0.1, decay: 0.3 }] },
};

function playNote(ctx: AudioContext, id: Exclude<MenuSoundId, "off">, noteIndex: number): void {
  const timbre = TIMBRES[id];
  const start = ctx.currentTime;
  const frequency = SCALE[((noteIndex % SCALE.length) + SCALE.length) % SCALE.length] * timbre.octave;
  const dry = ctx.createGain();
  dry.gain.value = 0.9;
  dry.connect(ctx.destination);
  dry.connect(getReverb(ctx));
  for (const partial of timbre.partials) {
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(frequency * partial.ratio, start);
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.085 * partial.level, start + timbre.attack);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + partial.decay);
    oscillator.connect(gain).connect(dry);
    oscillator.start(start);
    oscillator.stop(start + partial.decay + 0.05);
  }
}

// noteIndex: position of the hovered menu item; omit it to preview a random note.
export function playMenuTick(noteIndex?: number): void {
  const id = getMenuSound();
  if (!context || id === "off") return;
  const now = performance.now();
  if (now - lastPlayed < MIN_GAP_MS) return;
  lastPlayed = now;
  try {
    if (context.state === "suspended") void context.resume();
    if (context.state !== "running") return;
    playNote(context, id, noteIndex ?? Math.floor(Math.random() * SCALE.length));
  } catch {
    // Audio is a nicety; never let it break the menu.
  }
}
