import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const layout = await readFile(new URL("../src/components/Layout.tsx", import.meta.url), "utf8");
const css = await readFile(new URL("../src/index.css", import.meta.url), "utf8");

test("sidebar renders one shared hover pill inside the scrolling nav", () => {
  assert.equal(layout.match(/sidebar-hover-pill/g)?.length, 1);
  assert.match(layout, /sidebar-scroll relative/);
  assert.match(layout, /onPointerLeave=\{hidePill\}/);
});

test("hover pill is not shown for touch pointers", () => {
  assert.match(layout, /pointerType !== "touch"/);
});

test("hover pill animates position, snaps on first show and honours reduced motion", () => {
  assert.match(css, /\.sidebar-hover-pill\s*{[^}]*transition:[^}]*top 320ms/s);
  assert.match(css, /\.sidebar-hover-pill\.is-snap/);
  assert.match(css, /prefers-reduced-motion: reduce\)\s*{\s*\.sidebar-hover-pill/);
});

test("menu items no longer paint their own hover background", () => {
  const rule = css.match(/\.sidebar-nav-item:not\(\.is-active\):hover\s*{([^}]*)}/)?.[1] ?? "";
  assert.ok(!rule.includes("background"));
});

test("active route is marked by a gliding pill instead of per-item background and bar", () => {
  assert.match(layout, /sidebar-active-pill/);
  assert.match(layout, /aria-current="page"/);
  assert.ok(!layout.includes('"is-active bg-white/15'));
  assert.match(css, /\.sidebar-active-pill\.is-snap/);
});

test("sidebar groups open independently (call management open by default) and stay fully open in minimal mode", () => {
  assert.match(layout, /aria-expanded=\{isOpen\}/);
  assert.match(layout, /const isOpen = collapsed \|\| standalone \|\| openGroups\.includes\(group\.label\)/);
  assert.match(layout, /DEFAULT_OPEN_GROUP = "مدیریت تماس‌ها"/);
  assert.match(layout, /if \(activeGroup\) setOpenGroups/);
  assert.match(css, /\.sidebar-group-panel\[data-open="true"\]/);
  assert.match(css, /\.sidebar-group-panel\s*{[^}]*visibility: hidden/s);
});

test("hover tick is synthesized, gesture-armed, throttled and can be muted", async () => {
  const sound = await readFile(new URL("../src/lib/menuSound.ts", import.meta.url), "utf8");
  assert.match(sound, /pointerdown/);
  assert.match(sound, /MIN_GAP_MS/);
  assert.match(sound, /getMenuSound\(\)/);
  assert.match(layout, /playMenuTick\(\)/);
  assert.match(layout, /nextMenuSound\(sound\)/);
});

test("pill offsets subtract the nav client edge so a RTL left-side scrollbar cannot shift them", () => {
  assert.equal(layout.match(/- nav\.clientLeft \+ nav\.scrollLeft/g)?.length, 2);
});

test("single-item groups (overview) stay outside the accordion", () => {
  assert.match(layout, /const standalone = group\.items\.length === 1/);
  assert.match(layout, /!collapsed && !standalone/);
});
