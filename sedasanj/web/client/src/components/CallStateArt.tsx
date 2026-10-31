import type { ReactNode } from "react";

export type CallStateSection =
  | "sentiment"
  | "conversation"
  | "transcript"
  | "tasks"
  | "summary"
  | "coach"
  | "entities"
  | "assistant"
  | "training"
  | "temporary";
export type CallStateKind = "empty" | "processing" | "failed";

const G = "#4b6e48";
const T = "#b2ac88";
const C = "#f2f0ef";
const ROSE = "#b5543f";
const SOFT = "#e2eadd";
const BAR = "#d3dccd";
const SIDE = "#dde5d8";

/* Visual language (same as the panel's landing illustrations): layered cards with a
   little thickness, a pedestal with a soft green glow, circuit lines with ring nodes
   and waveform clusters. Empty = tan dashed ghost, processing = animated green,
   failed = rose break plus an alert badge. */

type Kind = { kind: CallStateKind };

function Defs() {
  return (
    <defs>
      <linearGradient id="csaCard" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#fdfdfb" />
        <stop offset="1" stopColor="#eef2ea" />
      </linearGradient>
      <radialGradient id="csaGlow" cx="50%" cy="50%" r="50%">
        <stop offset="0" stopColor={G} stopOpacity=".28" />
        <stop offset="1" stopColor={G} stopOpacity="0" />
      </radialGradient>
    </defs>
  );
}

function Stage({ kind, plinth = true }: Kind & { plinth?: boolean }) {
  const bars = (x: number) => [-12, -6, 0, 6, 12].map((dx, i) => {
    const h = [10, 20, 30, 18, 12][i];
    return (
      <path
        key={dx}
        d={`M${x + dx} ${150 - h}v${h * 2}`}
        className={kind === "processing" ? "csa-bar" : undefined}
        style={kind === "processing" ? { animationDelay: `${i * 0.14}s`, transformOrigin: `${x + dx}px 150px` } : undefined}
      />
    );
  });
  return (
    <>
      <ellipse cx="240" cy="268" rx="196" ry="24" fill="url(#csaGlow)" />
      <g stroke={T} strokeWidth="1.6" strokeLinecap="round" fill="none" opacity=".9">
        <path d="M60 64h50c14 0 16 12 30 12" />
        <path d="M420 218h-48c-14 0-16-12-30-12" />
        <path d="M72 238h38c12 0 16-10 30-10" />
        <path d="M414 82h-40c-12 0-16 10-30 10" />
      </g>
      <g stroke={G} strokeWidth="2" fill={C}>
        <circle cx="60" cy="64" r="6" />
        <circle cx="420" cy="218" r="6" />
        <circle cx="72" cy="238" r="5" />
        <circle cx="414" cy="82" r="5" />
      </g>
      <g stroke={G} strokeWidth="4.5" strokeLinecap="round" opacity={kind === "empty" ? 0.3 : 0.55}>
        {bars(40)}
        {bars(440)}
      </g>
      {plinth ? (
        <>
                    </>
      ) : null}
      <g stroke={G} strokeWidth="2" strokeLinecap="round">
        <path d="M392 44v12M386 50h12" />
        <path d="M92 52v9M87.5 56.5h9" stroke={T} />
      </g>
    </>
  );
}

function Badge({ kind, x = 372, y = 40 }: Kind & { x?: number; y?: number }) {
  if (kind === "empty") return null;
  const color = kind === "failed" ? ROSE : G;
  return (
    <g>
      <circle cx={x} cy={y} r="15" fill={C} stroke={color} strokeWidth="2.4" />
      {kind === "failed" ? (
        <g stroke={ROSE} strokeWidth="2.8" strokeLinecap="round">
          <path d={`M${x} ${y - 7}v8`} />
          <path d={`M${x} ${y + 6.5}v.1`} />
        </g>
      ) : (
        <path className="csa-spin" d={`M${x} ${y - 9}a9 9 0 0 1 9 9`} stroke={G} strokeWidth="2.8" strokeLinecap="round" fill="none" style={{ transformOrigin: `${x}px ${y}px` }} />
      )}
    </g>
  );
}

function Card({
  x, y, w, h, r = 8, ghost = false, tilt = 0, bar = false, children,
}: {
  x: number; y: number; w: number; h: number; r?: number; ghost?: boolean; tilt?: number; bar?: boolean; children?: ReactNode;
}) {
  const transform = tilt ? `translate(0 ${(-Math.tan((tilt * Math.PI) / 180) * (x + w / 2)).toFixed(1)}) skewY(${tilt})` : undefined;
  const ink = ghost ? T : G;
  const dash = ghost ? "5 4" : undefined;
  return (
    <g transform={transform}>
      <rect x={x + 5} y={y + 5} width={w} height={h} rx={r} fill={SIDE} stroke={ink} strokeWidth="1.6" strokeOpacity={ghost ? 0.6 : 0.7} />
      <rect x={x} y={y} width={w} height={h} rx={r} fill="url(#csaCard)" stroke={ink} strokeWidth="2.4" strokeDasharray={dash} />
      {bar ? (
        <>
          <g fill={ghost ? T : G}>
            <circle cx={x + 12} cy={y + 11} r="2.6" />
            <circle cx={x + 21} cy={y + 11} r="2.6" opacity=".6" />
            <circle cx={x + 30} cy={y + 11} r="2.6" opacity=".6" />
          </g>
          <rect x={x + w - 38} y={y + 8} width="28" height="6" rx="3" fill={BAR} />
          <path d={`M${x} ${y + 22}h${w}`} stroke={T} strokeWidth="1.2" opacity=".7" />
        </>
      ) : null}
      {children}
    </g>
  );
}

function Face({ cx, cy, mood, color = G, ghost = false }: { cx: number; cy: number; mood: "smile" | "flat" | "frown"; color?: string; ghost?: boolean }) {
  const mouth = { smile: `M${cx - 5} ${cy + 3}q5 5 10 0`, flat: `M${cx - 5} ${cy + 5}h10`, frown: `M${cx - 5} ${cy + 7}q5 -5 10 0` }[mood];
  return (
    <g stroke={color} strokeWidth="2" strokeLinecap="round" fill="none" opacity={ghost ? 0.7 : 1}>
      <circle cx={cx} cy={cy} r="13" fill={ghost ? "none" : SOFT} strokeDasharray={ghost ? "3 3" : undefined} />
      <path d={`M${cx - 5} ${cy - 3}v.1M${cx + 5} ${cy - 3}v.1`} strokeWidth="2.6" />
      <path d={mouth} />
    </g>
  );
}

function Lines({ x, y, widths, gap = 12, ghost, animate, base = 0, color = BAR, weight = 5 }: {
  x: number; y: number; widths: number[]; gap?: number; ghost?: boolean; animate?: boolean; base?: number; color?: string; weight?: number;
}) {
  return (
    <g stroke={ghost ? T : color} strokeWidth={weight} strokeLinecap="round" fill="none" strokeDasharray={ghost ? "3 6" : undefined}>
      {widths.map((w, i) => (
        <path
          key={i}
          d={`M${x} ${y + i * gap}h${w}`}
          className={animate ? "csa-draw" : undefined}
          pathLength={animate ? 1 : undefined}
          style={animate ? { animationDelay: `${base + i * 0.3}s` } : undefined}
        />
      ))}
    </g>
  );
}

/* ---------- call detail sections ---------- */

function Sentiment({ kind }: Kind) {
  const ghost = kind === "empty";
  const cust = "M172 176 198 154l24 10 26-32 26 8 30-26";
  const oper = "M172 156l26 12 24-22 26 8 26-26 30 8";
  return (
    <>
      <Card x={150} y={62} w={180} h={146} tilt={-2} bar ghost={ghost}>
        <path d="M164 100v86h152" stroke={T} strokeWidth="2" strokeLinecap="round" fill="none" />
        <path d="M168 128h144M168 158h144" stroke={T} strokeWidth="1" strokeDasharray="2 5" opacity=".8" />
        {ghost ? (
          <g fill="none" strokeWidth="3" strokeLinecap="round">
            <path d="M172 170h130" stroke={G} strokeDasharray="6 6" opacity=".5" />
            <path d="M172 150h130" stroke={T} strokeDasharray="6 6" />
            <circle cx="172" cy="170" r="4" fill={C} stroke={G} />
            <circle cx="172" cy="150" r="4" fill={C} stroke={T} />
          </g>
        ) : null}
        {kind === "processing" ? (
          <g fill="none" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round">
            <path className="csa-draw" pathLength={1} d={cust} stroke={G} />
            <path className="csa-draw csa-delay" pathLength={1} d={oper} stroke={T} />
            <circle className="csa-pulse" cx="302" cy="106" r="5" fill={G} stroke="none" style={{ transformOrigin: "302px 106px" }} />
          </g>
        ) : null}
        {kind === "failed" ? (
          <g fill="none" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M172 176 198 154l24 10 14-18" stroke={G} />
            <path d="M262 132l12 6M286 138l16-14" stroke={G} strokeDasharray="2 7" opacity=".6" />
            <path d="m244 128 12 12m0-12-12 12" stroke={ROSE} strokeWidth="3.4" />
            <path d="M172 156l26 12 24-22" stroke={T} />
          </g>
        ) : null}
        <g fill="none">
          <rect x="168" y="192" width="10" height="5" rx="2.5" fill={ghost ? "none" : G} stroke={ghost ? G : "none"} />
          <rect x="182" y="193" width="28" height="3" rx="1.5" fill={BAR} />
          <rect x="222" y="192" width="10" height="5" rx="2.5" fill={ghost ? "none" : T} stroke={ghost ? T : "none"} />
          <rect x="236" y="193" width="28" height="3" rx="1.5" fill={BAR} />
        </g>
      </Card>
      <Card x={92} y={112} w={46} h={46} r={9} ghost={ghost}>
        <Face cx={115} cy={135} mood={ghost ? "flat" : "smile"} ghost={ghost} />
      </Card>
      <Card x={344} y={134} w={46} h={46} r={9} ghost={ghost}>
        <Face cx={367} cy={157} mood={kind === "failed" ? "frown" : "flat"} color={kind === "failed" ? ROSE : G} ghost={ghost} />
      </Card>
    </>
  );
}

function Conversation({ kind }: Kind) {
  const ghost = kind === "empty";
  const ring = { cx: 240, cy: 132, r: 38 };
  return (
    <>
      <Card x={160} y={62} w={160} h={148} tilt={-2} ghost={ghost}>
        <circle {...ring} fill="none" stroke={ghost ? T : "#d9dfcf"} strokeWidth="13" opacity={ghost ? 0.7 : 1} strokeDasharray={ghost ? "4 7" : undefined} />
        {kind === "processing" ? (
          <circle className="csa-spin" {...ring} fill="none" stroke={G} strokeWidth="13" strokeDasharray="78 161" style={{ transformOrigin: "240px 132px" }} />
        ) : null}
        {kind === "failed" ? (
          <>
            <circle {...ring} fill="none" stroke={G} strokeWidth="13" strokeDasharray="88 151" transform="rotate(-90 240 132)" />
            <circle {...ring} fill="none" stroke={ROSE} strokeWidth="13" strokeDasharray="16 223" transform="rotate(90 240 132)" />
          </>
        ) : null}
        <g fill={ghost ? "none" : C} stroke={ghost ? T : G} strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round" strokeDasharray={ghost ? "3 3" : undefined}>
          <path d="M224 120h24v16h-11l-7 6v-6h-6z" />
          <path d="M252 126h8v16h-5v5l-6-5h-8" fill="none" />
        </g>
        <g fill="none" strokeLinecap="round">
          <rect x="178" y="186" width="10" height="6" rx="3" fill={ghost ? "none" : G} stroke={ghost ? G : "none"} />
          <rect x="192" y="187" width="30" height="4" rx="2" fill={BAR} />
          <rect x="238" y="186" width="10" height="6" rx="3" fill={ghost ? "none" : T} stroke={ghost ? T : "none"} />
          <rect x="252" y="187" width="30" height="4" rx="2" fill={BAR} />
        </g>
      </Card>
      <Card x={100} y={106} w={46} h={46} r={9} ghost={ghost}>
        <path d="M112 122c0 12 8 20 20 20l4-6-8-4-3 3c-4-2-7-5-9-9l3-3-4-8z" transform="translate(-2 0)" fill={ghost ? "none" : SOFT} stroke={ghost ? T : G} strokeWidth="2.2" strokeLinejoin="round" strokeDasharray={ghost ? "3 3" : undefined} />
      </Card>
      <Card x={336} y={106} w={46} h={46} r={9} ghost={ghost}>
        <g fill="none" stroke={ghost ? T : G} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" strokeDasharray={ghost ? "3 3" : undefined}>
          <path d="M347 132v-4a12 12 0 0 1 24 0v4" />
          <rect x="344" y="130" width="6" height="11" rx="2" fill={ghost ? "none" : SOFT} />
          <rect x="368" y="130" width="6" height="11" rx="2" fill={ghost ? "none" : SOFT} />
          <path d="M371 141c0 4-4 5-9 5" />
        </g>
      </Card>
    </>
  );
}

function Transcript({ kind }: Kind) {
  const ghost = kind === "empty";
  const heights = [6, 12, 20, 12, 26, 16, 22, 10, 18, 8, 12, 6];
  const rows = [
    { y: 92, side: 0, w: 70 },
    { y: 118, side: 1, w: 56 },
    { y: 144, side: 0, w: 76 },
    { y: 170, side: 1, w: 48 },
  ];
  return (
    <>
      <Card x={92} y={84} w={140} h={116} tilt={-2} bar ghost={ghost}>
        <circle cx="118" cy="132" r="15" fill={ghost ? "none" : SOFT} stroke={ghost ? T : G} strokeWidth="2" strokeDasharray={ghost ? "3 3" : undefined} />
        <g fill="none" stroke={ghost ? T : G} strokeWidth="2.2" strokeLinecap="round">
          <rect x="114" y="123" width="8" height="13" rx="4" />
          <path d="M110 133a8 8 0 0 0 16 0M118 141v4" />
        </g>
        <g stroke={kind === "failed" ? ROSE : G} strokeWidth="3.2" strokeLinecap="round" opacity={ghost ? 0.45 : 1}>
          {heights.map((h, i) => {
            const flat = ghost;
            const cut = kind === "failed" && (i === 5 || i === 6);
            const hh = cut ? 0.1 : flat ? 2 : h;
            return (
              <path
                key={i}
                d={`M${144 + i * 7} ${132 - hh / 2}v${hh}`}
                className={kind === "processing" ? "csa-bar" : undefined}
                style={kind === "processing" ? { animationDelay: `${i * 0.1}s`, transformOrigin: `${144 + i * 7}px 132px` } : undefined}
                strokeDasharray={cut ? "1 3" : undefined}
              />
            );
          })}
        </g>
        <Lines x={106} y={166} widths={[100, 70]} gap={12} ghost={ghost} />
      </Card>
      <path d="M238 142h12m-5-5 5 5-5 5" stroke={ghost ? T : G} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <Card x={256} y={64} w={130} h={146} tilt={2} bar ghost={ghost}>
        {rows.map((row, i) => {
          const left = row.side === 0;
          const cx = left ? 276 : 366;
          const x0 = left ? 290 : 358 - row.w;
          return (
            <g key={row.y}>
              <circle cx={cx} cy={row.y + 8} r="8" fill={ghost ? "none" : left ? SOFT : "#efe9d3"} stroke={ghost ? T : left ? G : T} strokeWidth="1.8" strokeDasharray={ghost ? "2 3" : undefined} />
              <Lines x={x0} y={row.y + 4} widths={[row.w]} gap={0} ghost={ghost} animate={kind === "processing"} base={i * 0.45} weight={6} />
              <Lines x={x0} y={row.y + 15} widths={[row.w * 0.6]} gap={0} ghost={ghost || (kind === "failed" && i > 1)} animate={kind === "processing"} base={i * 0.45 + 0.2} weight={4} />
            </g>
          );
        })}
      </Card>
    </>
  );
}

function Summary({ kind }: Kind) {
  const ghost = kind === "empty";
  const spark = "M240 124l5 15 15 5-15 5-5 15-5-15-15-5 15-5z";
  return (
    <>
      <g stroke={ghost ? T : G} strokeWidth="3" strokeLinecap="round">
        <path d="M240 92v-12M214 102l-8-8M266 102l8-8" />
      </g>
      <Card x={92} y={110} w={104} h={100} tilt={-2} ghost={ghost}>
        <Lines x={106} y={128} widths={[74, 62, 78, 54, 70, 46]} gap={12} ghost={ghost} animate={false} />
      </Card>
      <Card x={284} y={110} w={104} h={100} tilt={2} ghost={ghost}>
        <circle cx="304" cy="132" r="9" fill={ghost ? "none" : SOFT} stroke={ghost ? T : G} strokeWidth="1.8" strokeDasharray={ghost ? "2 3" : undefined} />
        <Lines x={320} y={129} widths={[48]} gap={0} ghost={ghost} animate={kind === "processing"} weight={5} />
        <path d="M298 152h78" stroke={T} strokeWidth="1.2" opacity=".7" />
        <Lines x={298} y={166} widths={[78, 78, 52]} gap={12} ghost={ghost || kind === "failed"} animate={kind === "processing"} base={0.4} color={G} weight={4} />
      </Card>
      <path d="M200 160h14m-5-5 5 5-5 5M266 160h14m-5-5 5 5-5 5" stroke={ghost ? T : G} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <g>
        <circle cx="240" cy="148" r="38" fill="url(#csaCard)" stroke={ghost ? T : G} strokeWidth="2.6" strokeDasharray={ghost ? "6 5" : undefined} />
        <path
          className={kind === "processing" ? "csa-pulse" : undefined}
          d={spark}
          fill={ghost ? "none" : kind === "failed" ? C : G}
          stroke={kind === "failed" ? T : G}
          strokeWidth="2.4"
          strokeLinejoin="round"
          strokeDasharray={ghost ? "3 4" : undefined}
          style={kind === "processing" ? { transformOrigin: "240px 148px" } : undefined}
        />
        {kind === "failed" ? <path d="M222 168l36-40" stroke={ROSE} strokeWidth="3" strokeLinecap="round" /> : null}
      </g>
    </>
  );
}

function Entities({ kind }: Kind) {
  const ghost = kind === "empty";
  const ink = ghost ? T : G;
  const chip = (x: number, y: number, w: number, i: number, glyph: ReactNode, missing = false) => {
    const g = ghost || missing;
    return (
      <g key={i} className={kind === "processing" ? "csa-pop" : undefined} style={kind === "processing" ? { animationDelay: `${i * 0.35}s`, transformOrigin: `${x + w / 2}px ${y + 14}px` } : undefined}>
        <rect x={x} y={y} width={w} height="28" rx="14" fill={g ? "none" : "url(#csaCard)"} stroke={g ? T : G} strokeWidth="2.2" strokeDasharray={g ? "4 4" : undefined} />
        <g stroke={g ? T : G} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" fill="none" transform={`translate(${x + 8} ${y + 6})`}>{glyph}</g>
        <rect x={x + 30} y={y + 12} width={w - 42} height="4" rx="2" fill={g ? T : BAR} opacity={g ? 0.5 : 1} />
      </g>
    );
  };
  return (
    <>
      <g stroke={T} strokeWidth="1.6" fill="none" strokeLinecap="round">
        <path d="M150 100h26M146 152h30M308 114h26M310 168h22" strokeDasharray={ghost ? "3 4" : undefined} />
      </g>
      <Card x={172} y={66} w={136} h={144} tilt={-1.5} ghost={ghost}>
        <circle cx="206" cy="108" r="19" fill={ghost ? "none" : SOFT} stroke={ink} strokeWidth="2.2" strokeDasharray={ghost ? "3 3" : undefined} />
        <g fill="none" stroke={ink} strokeWidth="2.2" strokeLinecap="round">
          <circle cx="206" cy="103" r="6" />
          <path d="M194 119a12 9 0 0 1 24 0" />
        </g>
        <Lines x={234} y={102} widths={[58, 40]} gap={12} ghost={ghost} weight={5} />
        <path d="M184 140h112" stroke={T} strokeWidth="1.2" opacity=".7" />
        {[0, 1, 2].map((i) => (
          <g key={i}>
            <rect x="186" y={152 + i * 17} width="10" height="10" rx="3" fill={ghost ? "none" : SOFT} stroke={ink} strokeWidth="1.8" strokeDasharray={ghost ? "2 2" : undefined} />
            <Lines x={204} y={157 + i * 17} widths={[i === 1 ? 64 : 82]} gap={0} ghost={ghost} animate={kind === "processing"} base={i * 0.4} weight={4} />
          </g>
        ))}
      </Card>
      {chip(86, 82, 66, 0, <><path d="M2 8a6 6 0 1 1 12 0c0 4-6 9-6 9S2 12 2 8Z" /><circle cx="8" cy="8" r="2" /></>)}
      {chip(78, 142, 72, 1, <><rect x="2" y="3" width="12" height="11" rx="2" /><path d="M2 7h12M5 1v4M11 1v4" /></>, kind === "failed")}
      {chip(332, 98, 68, 2, <><path d="M3 3h6l5 5-6 6-5-5z" /><circle cx="6" cy="6" r="1" /></>)}
      {chip(336, 158, 62, 3, <><circle cx="8" cy="8" r="6" /><path d="M8 4v4l3 2" /></>, kind === "failed")}
    </>
  );
}

function Tasks({ kind }: Kind) {
  const ghost = kind === "empty";
  const ink = ghost ? T : G;
  return (
    <>
      <Card x={150} y={72} w={132} h={140} tilt={-2} ghost={ghost}>
        {[104, 132, 160, 188].map((y, i) => (
          <g key={y}>
            <rect x="168" y={y - 8} width="16" height="16" rx="4" fill="none" stroke={ink} strokeWidth="2" strokeDasharray="3 3" />
            <Lines x={194} y={y - 3} widths={[i % 2 ? 56 : 70]} gap={0} ghost={ghost} weight={5} />
            <Lines x={194} y={y + 6} widths={[i % 2 ? 30 : 38]} gap={0} ghost={ghost} weight={3} />
          </g>
        ))}
        <circle cx="264" cy="200" r="14" fill={C} stroke={ink} strokeWidth="2.4" strokeDasharray={ghost ? "3 3" : undefined} />
        <path d="M264 194v12M258 200h12" stroke={ink} strokeWidth="2.4" strokeLinecap="round" />
      </Card>
      <g transform="translate(0 -3) skewY(-2)">
        <rect x="200" y="58" width="44" height="18" rx="6" fill={C} stroke={G} strokeWidth="2.4" />
        <rect x="214" y="53" width="16" height="9" rx="3" fill={SOFT} stroke={G} strokeWidth="2" />
      </g>
      <Card x={304} y={102} w={84} h={72} r={9} ghost={ghost}>
        <path d="M304 120h84" stroke={ink} strokeWidth="2" strokeDasharray={ghost ? "3 3" : undefined} />
        <g fill={ghost ? T : BAR}>
          {[0, 1, 2, 3].flatMap((r) => [0, 1, 2, 3].map((c) => <circle key={`${r}${c}`} cx={316 + c * 17} cy={132 + r * 11} r="2.4" opacity={ghost ? 0.7 : 1} />))}
        </g>
        {!ghost ? <rect x="327" y="142" width="14" height="10" rx="3" fill="none" stroke={G} strokeWidth="2" /> : null}
      </Card>
      <Card x={100} y={146} w={44} h={44} r={9} ghost={ghost}>
        <circle cx="122" cy="168" r="13" fill="none" stroke={ink} strokeWidth="2.2" strokeDasharray={ghost ? "3 3" : undefined} />
        <path d="M122 160v8l5 4" stroke={ink} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      </Card>
    </>
  );
}

/* ---------- operator coach ---------- */

function Coach({ kind }: Kind) {
  const ghost = kind === "empty";
  const ink = ghost ? T : G;
  return (
    <>
      <Card x={138} y={66} w={150} h={148} tilt={-2} ghost={ghost} bar>
        <rect x="156" y="98" width="86" height="22" rx="8" fill={ghost ? "none" : SOFT} stroke={ink} strokeWidth="2" strokeDasharray={ghost ? "3 3" : undefined} />
        <Lines x={166} y={109} widths={[62]} gap={0} ghost={ghost} weight={4} />
        <rect x="184" y="128" width="86" height="22" rx="8" fill="none" stroke={ink} strokeWidth="2" strokeDasharray={ghost ? "3 3" : undefined} />
        <Lines x={194} y={139} widths={[56]} gap={0} ghost={ghost} weight={4} />
        <g stroke={ink} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" strokeDasharray={ghost ? "3 3" : undefined}>
          <path d="M156 170h28l6-8 8 18 8-12 6 2h26" />
        </g>
        <Lines x={156} y={196} widths={[100, 60]} gap={10} ghost={ghost} weight={4} />
      </Card>
      <Card x={310} y={96} w={92} h={92} r={9} ghost={ghost}>
        <g fill={ghost ? T : BAR}>
          {[0, 1, 2, 3].map((i) => (
            <rect key={i} x={324 + i * 18} y={170 - (i + 1) * 17} width="11" height={(i + 1) * 17} rx="2" opacity={ghost ? 0.7 : 1} />
          ))}
        </g>
        <path d="M322 130l18-14 16 8 28-24" stroke={ink} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" fill="none" strokeDasharray={ghost ? "3 3" : undefined} />
      </Card>
      <Card x={90} y={150} w={46} h={46} r={9} ghost={ghost}>
        <path d="m113 160 4.4 9 9.6 1.3-7 6.8 1.7 9.6-8.7-4.6-8.7 4.6 1.7-9.6-7-6.8 9.6-1.3z" fill={ghost ? "none" : SOFT} stroke={ink} strokeWidth="2.2" strokeLinejoin="round" strokeDasharray={ghost ? "3 3" : undefined} />
      </Card>
    </>
  );
}

/* ---------- assistant ---------- */

function Assistant({ kind }: Kind) {
  const ghost = kind === "empty";
  return (
    <>
      <Card x={140} y={58} w={200} h={156} tilt={-1.5} bar>
        <rect x="236" y="88" width="90" height="20" rx="8" fill={SOFT} stroke={G} strokeWidth="1.8" />
        <Lines x={246} y={98} widths={[62]} gap={0} color={G} weight={4} />
        <circle cx="162" cy="134" r="10" fill={C} stroke={G} strokeWidth="2" />
        <path d="M158 132v.1M166 132v.1M158 138h8" stroke={G} strokeWidth="2.2" strokeLinecap="round" />
        <rect x="178" y="118" width="120" height="38" rx="9" fill="url(#csaCard)" stroke={G} strokeWidth="1.8" />
        <Lines x={188} y={130} widths={[96, 70]} gap={12} />
        <rect x="152" y="180" width="176" height="22" rx="8" fill="#f6f8f3" stroke={T} strokeWidth="1.8" />
        <rect x="156" y="184" width="22" height="14" rx="5" fill={G} />
        <path d="M171 191h-8m3-3-3 3 3 3" stroke={C} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        <Lines x={190} y={191} widths={[60]} gap={0} weight={4} />
        {kind === "processing" ? (
          <g fill={G}>
            {[0, 1, 2].map((i) => (
              <circle key={i} className="csa-pop" cx={196 + i * 10} cy="168" r="2.8" style={{ animationDelay: `${i * 0.2}s`, transformOrigin: `${196 + i * 10}px 168px` }} />
            ))}
          </g>
        ) : null}
      </Card>
      <Card x={86} y={104} w={46} h={46} r={9} ghost={ghost}>
        <path d="M109 116l3.4 10.2L122 130l-9.6 3.8L109 144l-3.4-10.2L96 130l9.6-3.8z" fill={SOFT} stroke={G} strokeWidth="2" strokeLinejoin="round" transform="translate(0 -1)" />
      </Card>
      <Card x={350} y={126} w={46} h={46} r={9}>
        <g fill="none" stroke={G} strokeWidth="2.2" strokeLinecap="round">
          <rect x="368" y="136" width="10" height="17" rx="5" fill={SOFT} />
          <path d="M363 148a10 10 0 0 0 20 0M373 158v4" />
        </g>
      </Card>
    </>
  );
}

function Training({ kind }: Kind) {
  return (
    <>
      <Card x={150} y={62} w={180} h={150} tilt={-2} bar>
        <rect x="166" y="92" width="148" height="26" rx="7" fill={SOFT} stroke={G} strokeWidth="1.8" />
        <Lines x={176} y={102} widths={[110]} gap={0} color={G} weight={4} />
        <Lines x={176} y={109} widths={[70]} gap={0} color={G} weight={3} />
        {[132, 156, 180].map((y, i) => (
          <g key={y}>
            <circle cx="174" cy={y + 4} r="4" fill={i === 0 ? G : "none"} stroke={G} strokeWidth="1.8" />
            <Lines x={188} y={y + 4} widths={[i === 1 ? 92 : 116]} gap={0} weight={5} />
          </g>
        ))}
      </Card>
      <g>
        <circle cx="350" cy="64" r="22" fill="url(#csaCard)" stroke={G} strokeWidth="2.6" />
        <g stroke={G} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" fill="none">
          <path d="M342 62a8 8 0 1 1 16 0c0 4-3 5-3 9h-10c0-4-3-5-3-9z" fill={SOFT} className={kind === "processing" ? "csa-pulse" : undefined} style={{ transformOrigin: "350px 64px" }} />
          <path d="M346 75h8" />
        </g>
      </g>
      <Card x={86} y={116} w={46} h={46} r={9}>
        <g fill="none" stroke={G} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M97 128h14a5 5 0 0 1 5 5v13" />
          <path d="M121 128h-3a5 5 0 0 0-5 5v13M97 128v16h11a5 5 0 0 1 5 5" />
        </g>
      </Card>
      <Card x={350} y={134} w={46} h={46} r={9}>
        <g fill="none" stroke={G} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M360 144h26v16h-12l-7 6v-6h-7z" fill={SOFT} />
          <path d="M369 150a3 3 0 1 1 4 3v2M373 158v.1" />
        </g>
      </Card>
    </>
  );
}

function Temporary({ kind }: Kind) {
  return (
    <>
      <Card x={140} y={66} w={200} h={146} tilt={-1.5} ghost>
        <g opacity=".8">
          <rect x="236" y="96" width="90" height="20" rx="8" fill="none" stroke={T} strokeWidth="1.8" strokeDasharray="4 3" />
          <Lines x={246} y={106} widths={[62]} gap={0} ghost />
          <rect x="156" y="130" width="124" height="38" rx="9" fill="none" stroke={T} strokeWidth="1.8" strokeDasharray="4 3" />
          <Lines x={166} y={142} widths={[100, 74]} gap={12} ghost />
          <rect x="152" y="182" width="176" height="20" rx="8" fill="none" stroke={T} strokeWidth="1.8" strokeDasharray="4 3" />
        </g>
      </Card>
      <g>
        <circle cx="344" cy="72" r="22" fill="url(#csaCard)" stroke={G} strokeWidth="2.6" />
        <circle cx="344" cy="72" r="13" fill="none" stroke={T} strokeWidth="2" strokeDasharray="3 3" />
        <path className={kind === "processing" ? "csa-spin" : undefined} d="M344 72v-8M344 72l6 4" stroke={G} strokeWidth="2.6" strokeLinecap="round" fill="none" style={{ transformOrigin: "344px 72px" }} />
      </g>
      <Card x={86} y={116} w={46} h={46} r={9}>
        <g fill="none" stroke={G} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="97" y="138" width="24" height="16" rx="3" fill={SOFT} />
          <path d="M101 138v-5a8 8 0 0 1 16 0v5M109 144v4" />
        </g>
      </Card>
      <Card x={350} y={134} w={46} h={46} r={9} ghost>
        <path d="M361 150h24m-20 0 1 14h14l1-14M368 146h10M370 154v6M376 154v6" stroke={T} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      </Card>
    </>
  );
}

const SCENES: Record<CallStateSection, (props: Kind) => ReactNode> = {
  sentiment: Sentiment,
  conversation: Conversation,
  transcript: Transcript,
  summary: Summary,
  coach: Coach,
  entities: Entities,
  tasks: Tasks,
  assistant: Assistant,
  training: Training,
  temporary: Temporary,
};

export function CallStateArt({
  section,
  kind = "empty",
  compact = false,
  className = "",
}: {
  section: CallStateSection;
  kind?: CallStateKind;
  compact?: boolean;
  className?: string;
}) {
  const Scene = SCENES[section];
  return (
    <svg className={`csa ${compact ? "csa--sm" : ""} ${className}`} viewBox="0 0 480 300" fill="none" aria-hidden="true" focusable="false">
      <Defs />
      <Stage kind={kind} plinth={section !== "assistant"} />
      <Scene kind={kind} />
      <Badge kind={kind} />
    </svg>
  );
}
