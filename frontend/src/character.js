// MindLoop UI V2.0: reference-guided black character, connected egg eyes,
// pink lips and cheeks. Keeps the V1 cheek silhouette and spring interaction.
// Mount <mindloop-character> anywhere; call replay() / setPaused(boolean).
const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
let instanceId = 0;

class MindLoopCharacter extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.uid = `ml-${++instanceId}`;
    this.reduced = matchMedia('(prefers-reduced-motion: reduce)');
    this.paused = this.reduced.matches || new URLSearchParams(location.search).has('still');
    this.t = 0; this.x = 0; this.y = 0; this.vx = 0; this.vy = 0;
    this.side = 1; this.targetX = 0; this.targetY = 0;
    this.pointer = { x: 296, y: 623 }; this.dragging = false;
    this.lastInteraction = -100; this.hair = 0; this.hairV = 0;
    this.pat = 0; this.patV = 0;
    this.boundTick = this.tick.bind(this);
  }

  connectedCallback() {
    const id = this.uid;
    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; contain:layout style; }
        svg { display:block; width:100%; height:100%; overflow:visible; user-select:none; -webkit-user-select:none; }
        svg:focus { outline:none; }
        svg:focus-visible .focus-ring { opacity:1; }
        .focus-ring { opacity:0; fill:none; stroke:#006e93; stroke-width:2; stroke-dasharray:4 6; }
        .hit { fill:transparent; cursor:grab; touch-action:none; }
        .hit:active { cursor:grabbing; }
        .head-tap { fill:transparent; cursor:pointer; touch-action:manipulation; }
        :host([app]) .reference-mark, :host([app]) .hint, :host([app]) .demo-cursor { display:none; }
        .hint { pointer-events:none; }
      </style>
      <svg viewBox="0 120 592 960" preserveAspectRatio="xMidYMid meet" tabindex="0" role="img"
        aria-label="黑色弹性小角色。拖动两侧脸颊后松开，或按左右方向键拉伸。空格暂停，R 重播。">
        <defs>
          <linearGradient id="${id}-head" x1="0" y1="0" x2=".9" y2="1" gradientUnits="objectBoundingBox"><stop stop-color="#18161b"/><stop offset="1" stop-color="#08080a"/></linearGradient>
          <linearGradient id="${id}-shirt" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#ffcc49"/><stop offset="1" stop-color="#fbba2f"/></linearGradient>
          <filter id="${id}-grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".82" numOctaves="3" seed="12" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="linear" slope=".13"/></feComponentTransfer><feBlend in="SourceGraphic" mode="soft-light"/></filter>
          <clipPath id="${id}-headclip"><path class="head-clip"/></clipPath>
        </defs>
        <g class="hint" fill="#c84d54" aria-hidden="true">
          <text class="hint-text" x="296" y="441" text-anchor="middle" font-family="Arial, sans-serif" font-size="24" font-weight="600" letter-spacing="1">DRAG TO PULL</text>
          <path class="arrow-left" d="M132 634 H153 V625 L170 641 L153 657 V648 H132 Z"/>
          <path class="arrow-right" d="M456 634 H435 V625 L418 641 L435 657 V648 H456 Z"/>
        </g>
        <g class="body" aria-hidden="true">
          <path d="M266 775 C268 753 272 725 282 715 Q293 708 305 716 C313 730 317 753 321 775" fill="url(#${id}-shirt)" stroke="#f8b625" stroke-width="1.3"/>
          <path d="M277 774 C278 743 307 744 309 774" fill="none" stroke="#ffe094" stroke-width="2.8"/>
          <path class="neck-outline" d="M283 680 L283 716 Q284 727 293 727 Q303 727 303 716 L303 680" fill="#26222a"/>
          <path class="neck" d="M286 679 L286 714 Q286 723 293 723 Q300 723 300 714 L300 679" fill="#121015"/>
          <path d="M286 679 H300 V687 L286 692 Z" fill="#070709"/>
        </g>
        <g class="head-rig" aria-hidden="true">
          <g class="sprout"><path class="leaf-back" fill="#111015" stroke="#26222c" stroke-width="1"/><path class="leaf-front" fill="#3a353e" stroke="#26222c" stroke-width="1"/></g>
          <path class="head" fill="url(#${id}-head)" stroke="#28232d" stroke-width="1.3"/>
          <g clip-path="url(#${id}-headclip)" opacity=".22"><rect x="100" y="510" width="410" height="220" fill="#151319" filter="url(#${id}-grain)"/></g>
          <circle class="blush-left" cx="230" cy="633" r="7.5" fill="#f44d9e"/>
          <circle class="blush-right" cx="360" cy="633" r="7.5" fill="#f44d9e"/>
          <g class="eye-left"><ellipse cx="273" cy="586" rx="24" ry="35" transform="rotate(8 273 586)" fill="#fffefa"/><circle class="pupil-left" cx="275" cy="593" r="6.5" fill="#08080a"/></g>
          <g class="eye-right"><ellipse cx="316" cy="586" rx="24" ry="35" transform="rotate(-8 316 586)" fill="#fffefa"/><circle class="pupil-right" cx="314" cy="593" r="6.5" fill="#08080a"/></g>
          <path class="mouth" fill="#0b090d" stroke="#f44d9e" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>
        </g>
        <rect class="focus-ring" x="162" y="450" width="263" height="343" rx="40"/>
        <path class="hit"/>
        <rect class="head-tap" x="249" y="452" width="92" height="137" rx="35"/>
        <path class="demo-cursor" d="M0 0 L1 31 L9 23 L16 37 L22 34 L15 20 L26 20 Z" fill="#171a16" stroke="#fffceb" stroke-width="2.2" stroke-linejoin="round" pointer-events="none" aria-hidden="true"/>
      </svg>`;
    this.els = {};
    for (const el of this.shadowRoot.querySelectorAll('[class]')) for (const name of el.classList) this.els[name] = el;
    this.svg = this.shadowRoot.querySelector('svg');
    if (this.hasAttribute('app')) {
      this.svg.setAttribute('viewBox', this.hasAttribute('compact') ? '125 450 340 340' : '55 390 482 420');
      this.svg.setAttribute('aria-label', '澜序小伙伴。向外拽左脸选择缓一缓，拽右脸选择做一小步，拍拍头回看生活记录。也可使用旁边的文字按钮。');
      if (this.hasAttribute('compact')) this.svg.setAttribute('aria-label', '澜序小伙伴。拍拍头，或按回车，与它互动。');
    }
    this.abort = new AbortController(); const opts = { signal: this.abort.signal };
    this.els.hit.addEventListener('pointerdown', e => this.startDrag(e), opts);
    this.els['head-tap'].addEventListener('pointerdown', e => { this.tapStart = { x: e.clientX, y: e.clientY }; }, opts);
    this.els['head-tap'].addEventListener('pointerup', e => {
      if (this.tapStart && Math.hypot(e.clientX - this.tapStart.x, e.clientY - this.tapStart.y) < 12) this.activate('remember');
      this.tapStart = null;
    }, opts);
    this.els['head-tap'].addEventListener('pointercancel', () => { this.tapStart = null; }, opts);
    this.svg.addEventListener('pointermove', e => this.movePointer(e), opts);
    this.svg.addEventListener('pointerup', e => this.endDrag(e), opts);
    this.svg.addEventListener('pointercancel', e => this.endDrag(e), opts);
    this.svg.addEventListener('lostpointercapture', e => this.endDrag(e), opts);
    this.svg.addEventListener('keydown', e => this.onKey(e), opts);
    this.svg.addEventListener('keyup', e => { if (e.key.startsWith('Arrow')) { this.targetX = 0; this.targetY = 0; this.keyboardPull = false; this.lastInteraction = this.t; this.settleIfPaused(); } }, opts);
    this.svg.addEventListener('blur', () => { this.keyboardPull = false; this.targetX = 0; this.targetY = 0; }, opts);
    document.addEventListener('visibilitychange', () => {
      cancelAnimationFrame(this.frame);
      if (!document.hidden) { this.lastFrame = null; this.frame = requestAnimationFrame(this.boundTick); }
    }, opts);
    this.reduced.addEventListener('change', () => this.setPaused(this.reduced.matches), opts);
    this.render(); this.frame = requestAnimationFrame(this.boundTick);
  }

  disconnectedCallback() { cancelAnimationFrame(this.frame); clearTimeout(this.actionTimer); this.abort?.abort(); }
  activate(destination) {
    if (this.actionTimer) return;
    this.lastInteraction = this.t;
    if (destination === 'remember') { this.patV = 2.8; this.hairV = 180; }
    else { this.side = destination === 'focus' ? -1 : 1; this.x = this.side * 42; this.vx = -this.side * 260; }
    if (this.hasAttribute('compact')) return;
    this.reportGesture(true, true, destination);
    this.actionTimer = setTimeout(() => {
      this.actionTimer = null;
      this.dispatchEvent(new CustomEvent('character-navigate', { detail: { destination }, bubbles: true, composed: true }));
    }, this.reduced.matches || this.paused ? 0 : 180);
  }
  reportGesture(active, ready, destination = this.side < 0 ? 'focus' : 'start') {
    if (!this.hasAttribute('app') || this.hasAttribute('compact')) return;
    const key = `${active}:${ready}:${destination}`;
    if (key === this.gestureKey) return;
    this.gestureKey = key;
    this.dispatchEvent(new CustomEvent('character-gesture', {
      detail: { active, ready, destination }, bubbles: true, composed: true
    }));
  }
  point(e) { const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(this.svg.getScreenCTM().inverse()); return { x: p.x, y: p.y }; }
  startDrag(e) {
    if (this.dragging || (e.pointerType === 'mouse' && e.button !== 0)) return;
    e.preventDefault(); this.svg.focus({ preventScroll: true });
    this.dragging = true; this.pointerId = e.pointerId; this.keyboardPull = false;
    this.origin = this.point(e); this.side = this.origin.x < 294 ? -1 : 1;
    this.dragStart = { x: e.clientX, y: e.clientY }; this.dragReady = false;
    this.x = 0; this.y = 0; this.vx = 0; this.vy = 0;
    this.targetX = 0; this.targetY = 0; this.lastInteraction = this.t;
    this.svg.setPointerCapture(e.pointerId);
    this.reportGesture(true, false);
  }
  movePointer(e) {
    this.pointer = this.point(e);
    if (!this.dragging || e.pointerId !== this.pointerId) return;
    const dx = this.pointer.x - this.origin.x;
    this.targetX = this.side * clamp(dx * this.side * .7, -27, 115);
    this.targetY = clamp((this.pointer.y - this.origin.y) * .62, -75, 65);
    this.lastInteraction = this.t;
    const outward = (e.clientX - this.dragStart.x) * this.side;
    this.dragReady = outward >= 18 && outward > Math.abs(e.clientY - this.dragStart.y) * .8;
    this.reportGesture(true, this.dragReady);
  }
  endDrag(e) {
    if (!this.dragging || e.pointerId !== this.pointerId) return;
    if (e.type === 'pointerup') this.movePointer(e);
    const navigate = e.type === 'pointerup' && this.hasAttribute('app') && this.dragReady;
    const destination = this.side < 0 ? 'focus' : 'start';
    this.dragging = false; this.targetX = 0; this.targetY = 0; this.lastInteraction = this.t;
    if (this.svg.hasPointerCapture(e.pointerId)) this.svg.releasePointerCapture(e.pointerId);
    this.settleIfPaused();
    if (navigate) this.activate(destination);
    else this.reportGesture(false, false);
  }
  settleIfPaused() {
    if (this.paused || this.reduced.matches) { this.x = 0; this.y = 0; this.vx = 0; this.vy = 0; this.hair = 0; this.hairV = 0; }
  }
  onKey(e) {
    if (this.hasAttribute('app') && ['ArrowLeft', 'ArrowRight', 'Enter', ' '].includes(e.key)) {
      e.preventDefault(); if (!e.repeat) this.activate(e.key === 'ArrowLeft' ? 'focus' : e.key === 'ArrowRight' ? 'start' : 'remember'); return;
    }
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault(); this.side = e.key === 'ArrowLeft' ? -1 : 1;
      this.keyboardPull = true; this.targetX = this.side * 66; this.targetY = -28; this.lastInteraction = this.t;
    } else if (e.code === 'Space') { e.preventDefault(); this.setPaused(!this.paused); }
    else if (e.key.toLowerCase() === 'r') this.replay();
  }
  setPaused(value) {
    this.paused = value;
    if (value) { this.targetX = 0; this.targetY = 0; }
    this.dispatchEvent(new Event('playstatechange'));
  }
  replay() {
    this.t = 0; this.x = 0; this.y = 0; this.vx = 0; this.vy = 0; this.hair = 0; this.hairV = 0;
    this.lastInteraction = -100; this.targetX = 0; this.targetY = 0;
    this.dragging = false; this.keyboardPull = false; this.setPaused(false);
  }
  demo(t) {
    // Pull / hold / release beats measured from the 20.2 second recording.
    const beats = [ [4.25, 5.05, 5.48, 1, 55, 29], [6.5, 7.1, 7.72, -1, -62, 18], [10.3, 10.85, 11.12, -1, -25, -15], [12.95, 13.65, 14.47, 1, 30, -54], [15.5, 16.0, 16.4, -1, -30, 22] ];
    for (const [start, peak, end, side, x, y] of beats) {
      if (t >= start && t < end) {
        const p = clamp((t - start) / (peak - start), 0, 1);
        const eased = p * p * (3 - 2 * p);
        return { side, x: x * eased, y: y * eased, active: true };
      }
    }
    return { side: this.side, x: 0, y: 0, active: false };
  }
  tick(now) {
    const dt = Math.min((now - (this.lastFrame ?? now)) / 1000, .032);
    this.lastFrame = now;
    if (!this.paused) this.t += dt;
    this.auto = !this.hasAttribute('app') && !this.paused && !this.dragging && !this.keyboardPull && this.t - this.lastInteraction > 8;
    this.demoState = this.auto ? this.demo(this.t % 20.2) : null;
    if (this.auto) { this.side = this.demoState.side; this.targetX = this.demoState.x; this.targetY = this.demoState.y; }
    const userActive = this.dragging || this.keyboardPull;
    if (!this.paused || userActive) {
      const steps = 4, h = dt / steps;
      for (let i = 0; i < steps; i++) {
        const k = userActive ? 580 : 210, damping = userActive ? 35 : 10;
        this.vx += ((this.targetX - this.x) * k - damping * this.vx) * h;
        this.vy += ((this.targetY - this.y) * k - damping * this.vy) * h;
        this.x += this.vx * h; this.y += this.vy * h;
        this.hairV += ((-this.x * .42 - this.vx * .06 - this.hair) * 150 - this.hairV * 7) * h;
        this.hair += this.hairV * h;
        this.patV += (-this.pat * 190 - this.patV * 9) * h;
        this.pat += this.patV * h;
      }
    }
    if (this.reduced.matches && !userActive) { this.x = 0; this.y = 0; this.hair = 0; this.vx = 0; this.vy = 0; this.pat = 0; this.patV = 0; }
    this.render();
    this.frame = requestAnimationFrame(this.boundTick);
  }

  render() {
    const e = this.els;
    const x = this.x, y = this.y;
    const left = this.side < 0, lx = left ? x : 0, rx = left ? 0 : x;
    const ly = left ? y : 0, ry = left ? 0 : y;
    const f = n => Number(n.toFixed(2));
    const d = `M ${f(241 + lx*.06)} ${f(587 + ly*.15)} C 235 570 237 556 258 548 C 280 540 318 542 335 552 C 348 559 346 573 ${f(345+rx*.06)} ${f(587+ry*.15)} C ${f(366+rx*.6)} ${f(588+ry*.65)} ${f(389+rx)} ${f(592+ry)} ${f(397+rx)} ${f(607+ry)} C ${f(409+rx)} ${f(629+ry)} ${f(403+rx*.85)} ${f(662+ry*.5)} ${f(391+rx*.65)} ${f(676+ry*.25)} C ${f(378+rx*.4)} ${f(692+ry*.18)} 352 687 329 685 Q 294 681 261 684 C ${f(239+lx*.4)} ${f(687+ly*.18)} ${f(213+lx*.7)} ${f(691+ly*.24)} ${f(201+lx*.8)} ${f(679+ly*.3)} C ${f(186+lx)} ${f(664+ly*.5)} ${f(181+lx)} ${f(637+ly)} ${f(185+lx)} ${f(617+ly)} C ${f(188+lx)} ${f(599+ly)} ${f(208+lx*.5)} ${f(592+ly*.5)} ${f(241+lx*.06)} ${f(587+ly*.15)} Z`;
    e.head.setAttribute('d', d); e['head-clip'].setAttribute('d', d);
    e.hit.setAttribute('d', d);
    // A light whole-head rotation accompanies the local cheek deformation.
    const angle = x * .024 + this.vx * .009;
    const headTransform = `translate(294 681) scale(${f(1+this.pat*.38)} ${f(1-this.pat*.6)}) translate(-294 -681) rotate(${f(angle)} 294 681)`;
    e['head-rig'].setAttribute('transform', headTransform); e.hit.setAttribute('transform', headTransform);
    const h = this.hair + Math.sin(this.t * 1.7) * 2.2;
    e['leaf-back'].setAttribute('d', `M289 545 C286 523 ${285+h*.4} 491 ${298+h} 476 C${308+h} 463 ${326+h} 468 ${327+h} 482 C${328+h} 500 301 516 294 545 Z`);
    e['leaf-front'].setAttribute('d', `M290 545 C295 517 ${309+h*.6} 491 ${328+h*.9} 489 C${344+h} 483 ${354+h} 491 ${351+h} 504 C${348+h} 518 324 515 309 526 Q299 533 290 545 Z`);
    e['blush-left'].setAttribute('transform', `translate(${f(lx*.58)} ${f(ly*.52)})`);
    e['blush-right'].setAttribute('transform', `translate(${f(rx*.58)} ${f(ry*.52)})`);
    const stretch = clamp((Math.abs(x)*.55 + Math.abs(y)*.8) / 64, 0, 1);
    const gazeX = clamp((this.pointer.x-294)/70, -3.8, 3.8);
    const gazeY = clamp((this.pointer.y-595)/100, -2, 3);
    const blinkPhase = this.t % 5.7;
    const blink = blinkPhase > 3.15 && blinkPhase < 3.37 ? Math.sin((blinkPhase-3.15)/.22*Math.PI) : 0;
    // Both eyes move together so their egg shapes keep touching during a pull.
    const eyeTransform = `translate(${f(x*.025)} ${f(y*.025)}) translate(294 586) scale(1 ${f(1-blink*.92)}) translate(-294 -586)`;
    e['eye-left'].setAttribute('transform', eyeTransform);
    e['eye-right'].setAttribute('transform', eyeTransform);
    e['pupil-left'].setAttribute('transform', `translate(${gazeX} ${gazeY})`);
    e['pupil-right'].setAttribute('transform', `translate(${gazeX} ${gazeY})`);
    // A thick pink lip follows the cheek; its smile opens with the stretch.
    const ax = 270 + lx*.4, ay = 640 + ly*.4;
    const bx = 319 + rx*.4, by = 640 + ry*.4;
    const mx = (ax+bx)/2, my = (ay+by)/2, open = stretch*12;
    const mouth = `M${f(ax)} ${f(ay)} Q${f(mx)} ${f(my+14)} ${f(bx)} ${f(by)} C${f(bx+14)} ${f(by-9)} ${f(bx+9)} ${f(my+27+open)} ${f(mx)} ${f(my+27+open)} C${f(ax-9)} ${f(my+27+open)} ${f(ax-14)} ${f(ay-9)} ${f(ax)} ${f(ay)} Z`;
    e.mouth.setAttribute('d', mouth);
    const cycle = this.t % 20.2;
    const hintAlpha = this.dragging || this.keyboardPull || this.t-this.lastInteraction < 4 ? 0 : this.auto ? (cycle < 4 ? Math.min(1,cycle/.7) : cycle > 17.8 ? Math.min(1,(cycle-17.8)/.8) : 0) : 1;
    e.hint.style.opacity = hintAlpha;
    e['hint-text'].setAttribute('letter-spacing', f(1 + 13*(.5+.5*Math.sin(this.t*1.5-1))));
    const arrowPulse = Math.sin(this.t*4) * 3;
    e['arrow-left'].setAttribute('transform', `translate(${arrowPulse} 0)`);
    e['arrow-right'].setAttribute('transform', `translate(${-arrowPulse} 0)`);
    const cursor = this.demoState?.active && this.auto;
    e['demo-cursor'].style.opacity = cursor ? 1 : 0;
    if (cursor) e['demo-cursor'].setAttribute('transform', `translate(${f((left?188:399)+x)} ${f(630+y)}) scale(.72)`);
  }
}

customElements.define('mindloop-character', MindLoopCharacter);
