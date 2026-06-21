# 🎨 Visual Identity & Web Design System

This document defines a world-class visual identity system, layout engine, and interactive components inspired by premier modern websites like [landonorris.com](https://landonorris.com) (cinematic, bold, editorial) and [vercel.com](https://vercel.com) (clean, minimal, technically precise). It also incorporates key guidelines for high-density, dark-theme trading/financial platforms like TradeSense.

---

## 🎨 1. Visual Identity System

### Color Palette Strategy
Define these CSS custom properties (variables) in your global stylesheet (e.g., `globals.css` or `index.css`) to ensure theme consistency across components:

```css
:root {
  /* Brand Accent */
  --color-primary: #6366f1;          /* Default Indigo (change to match brand) */
  --color-primary-hover: #4f46e5;    /* ~10% darker/lighter for active state */
  --color-primary-muted: rgba(99, 102, 241, 0.15); /* 15% opacity */
  --color-primary-rgb: 99, 102, 241; /* For alpha calculations */

  /* Dark Theme Backgrounds */
  --color-bg: #0a0a0a;               /* Deep cinematic black (Lando-style) */
  --color-bg-elevated: #111111;      /* Card surfaces, widgets */
  --color-bg-overlay: #1a1a1a;       /* Modals, dropdowns, drawers */

  /* Typography & Text */
  --color-text-primary: #ffffff;     /* High emphasis */
  --color-text-secondary: #a1a1aa;   /* Medium emphasis */
  --color-text-muted: #52525b;       /* Low emphasis / Disabled */

  /* Borders & Dividers */
  --color-border: rgba(255, 255, 255, 0.08);
  --color-border-hover: rgba(255, 255, 255, 0.16);

  /* Semantic / Status Colors */
  --color-success: #22c55e;          /* Positive / Gain / Buy */
  --color-danger: #ef4444;           /* Negative / Loss / Sell */
  --color-warning: #f59e0b;          /* Alert / Pending */
}
```

### Typography Scale
Use responsive viewport-based text sizes to ensure typography looks editorial on all screens:

```css
/* Giant editorial headlines (landonorris.com style) */
.text-display {
  font-size: clamp(3rem, 10vw, 10rem);
  font-weight: 900;
  line-height: 0.9;
  letter-spacing: -0.04em;
  text-transform: uppercase;
}

/* Page/Section headers */
.text-heading {
  font-size: clamp(1.5rem, 4vw, 3.5rem);
  font-weight: 700;
  line-height: 1.1;
  letter-spacing: -0.02em;
}

/* Readable Body text */
.text-body {
  font-size: clamp(0.875rem, 1.5vw, 1.125rem);
  line-height: 1.7;
  color: var(--color-text-secondary);
}

/* Uppercased metadata/eyebrow labels */
.text-label {
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}
```

### Font Pairings by Project Type
Choose font pairings that match the personality of your application:

| Project Type | Display Font | Body Font |
| :--- | :--- | :--- |
| **Finance / Trading (TradeSense)** | `Space Grotesk` | `JetBrains Mono` |
| **SaaS / Tech (Vercel-style)** | `Geist` or `Cal Sans` | `Geist Mono` or `Inter` |
| **Portfolio / Personal Brand** | `Bebas Neue` or `Monument Extended` | `Inter` |
| **E-commerce / Lifestyle** | `Playfair Display` | `Söhne` |
| **Startups / Modern Landing** | `Syne` or `Clash Display` | `Plus Jakarta Sans` |

---

## 🏗️ 2. Grid & Layout System

Use fluid container padding and responsive column grid structures:

```css
.container {
  width: 100%;
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 clamp(1rem, 4vw, 4rem);
}

/* Multi-column grid structures */
.grid-12 {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 1.5rem;
}

.grid-3 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 2rem;
}

.grid-2 {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 2rem;
}

/* Viewport-dependent padding system */
.section-xl { padding: clamp(6rem, 12vw, 12rem) 0; }
.section-lg { padding: clamp(4rem, 8vw, 8rem) 0; }
.section-md { padding: clamp(2rem, 4vw, 4rem) 0; }
```

---

## 🎬 3. Hero Section Patterns

### Option A: Cinematic Hero (landonorris.com style)
Perfect for immersive portfolio, personal brand, or high-impact brand landing pages.

#### JSX / HTML Structure
```jsx
<section className="hero">
  {/* Background Media */}
  <div className="hero-media">
    <img src="/assets/hero-bg.jpg" alt="" className="hero-bg" />
    {/* Alternatively: <video autoPlay muted loop playsInline src="/hero.mp4" /> */}
  </div>

  {/* Vignette Overlay for readability */}
  <div className="hero-overlay" />

  {/* Content */}
  <div className="hero-content">
    <span className="text-label">[ established 2026 ]</span>
    
    <h1 className="text-display">
      <span className="block">TRADESENSE</span>
      <span className="block text-outline">INTELLIGENCE</span>
    </h1>

    <p className="text-body">AI-assisted Indian market trading intelligence.</p>

    <div className="cta-group">
      <a href="#explore" className="btn-primary">Explore Signals →</a>
    </div>
  </div>

  {/* Micro-interactive scroll indicator */}
  <div className="scroll-indicator">
    <span>scroll</span>
    <div className="scroll-line" />
  </div>
</section>
```

#### CSS Implementation
```css
.hero {
  position: relative;
  height: 100svh; /* Safari mobile friendly height */
  display: flex;
  align-items: flex-end;
  padding-bottom: 5rem;
  overflow: hidden;
}

.hero-media, .hero-bg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.hero-overlay {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    to top,
    rgba(10, 10, 10, 0.95) 0%,
    rgba(10, 10, 10, 0.4) 50%,
    rgba(10, 10, 10, 0.1) 100%
  );
  z-index: 1;
}

.hero-content {
  position: relative;
  z-index: 2;
  width: 100%;
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 clamp(1rem, 4vw, 4rem);
}

.text-outline {
  -webkit-text-stroke: 2px var(--color-text-primary);
  color: transparent;
}
```

---

### Option B: Minimal Tech Hero (vercel.com style)
Ideal for SaaS, developer platforms, and technical application landing pages.

#### JSX / HTML Structure
```jsx
<section className="saas-hero">
  {/* Visual FX Underlays */}
  <div className="bg-grid" />
  <div className="bg-glow" />

  <div className="hero-inner">
    <div className="badge">
      <span className="badge-dot" />
      New — Real-time Astrological Panchanga & Hora Timing
    </div>

    <h1 className="text-heading">
      Elevate Your Trade. <br />
      <span className="gradient-text">Sync with the Cosmos.</span>
    </h1>

    <p className="text-body max-w-xl mx-auto">
      Experience the intersection of advanced indicators, paper trading, and Vedic astronomical timings. Built for Indian market traders.
    </p>

    <div className="cta-group">
      <button className="btn-primary">Launch Dashboard</button>
      <button className="btn-ghost">View Pine Script Docs →</button>
    </div>

    <p className="social-proof">Monitored live by thousands of active traders</p>
  </div>
</section>
```

#### CSS Implementation
```css
.saas-hero {
  position: relative;
  min-height: 85vh;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 8rem 1rem 4rem;
  overflow: hidden;
  background-color: var(--color-bg);
}

.bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.02) 1px, transparent 1px);
  background-size: 40px 40px;
  background-position: center;
}

.bg-glow {
  position: absolute;
  top: -10%;
  left: 50%;
  transform: translateX(-50%);
  width: clamp(300px, 80vw, 800px);
  height: clamp(300px, 80vw, 800px);
  background: radial-gradient(circle, rgba(var(--color-primary-rgb), 0.12) 0%, transparent 70%);
  filter: blur(60px);
}

.gradient-text {
  background: linear-gradient(135deg, #22c55e, #10b981, #6366f1);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
```

---

## 🧩 4. Core Component Library

### Buttons & Call-to-Actions

```css
/* Primary Button */
.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1.5rem;
  background: var(--color-primary);
  color: #000000;                     /* Contrast against color-primary */
  font-weight: 600;
  font-size: 0.875rem;
  border-radius: 0.5rem;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.btn-primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 24px var(--color-primary-muted);
  filter: brightness(1.1);
}

/* Ghost Outline Button */
.btn-ghost {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1.5rem;
  background: transparent;
  color: var(--color-text-primary);
  font-weight: 500;
  border: 1px solid var(--color-border);
  border-radius: 0.5rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-ghost:hover {
  background: var(--color-bg-elevated);
  border-color: var(--color-border-hover);
}
```

### Premium UI Cards

```css
/* Glassmorphism card for real-time market tickers / astrology widgets */
.card-glass {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 1rem;
  padding: 2rem;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.card-glass:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.16);
  transform: translateY(-4px);
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
}

/* Minimal Elevated Grid Feature Card */
.card-feature {
  padding: 2rem;
  border: 1px solid var(--color-border);
  border-radius: 0.75rem;
  background: var(--color-bg-elevated);
  transition: border-color 0.2s ease, transform 0.2s ease;
}

.card-feature:hover {
  border-color: var(--color-border-hover);
  transform: translateY(-2px);
}
```

### Blurred Sticky Header Navigation

```css
.navbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.25rem clamp(1rem, 4vw, 4rem);
  background: rgba(10, 10, 10, 0.75);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--color-border);
  transition: padding 0.3s ease;
}

.navbar.scrolled {
  padding: 0.875rem clamp(1rem, 4vw, 4rem);
}

.nav-link {
  font-size: 0.875rem;
  color: var(--color-text-secondary);
  text-decoration: none;
  transition: color 0.2s ease;
}

.nav-link:hover, .nav-link.active {
  color: var(--color-text-primary);
}
```

---

## ⚡ 5. Micro-Animations & Scroll Effects

### A. IntersectionObserver Scroll Reveal
Apply a subtle upward fade to elements as the user scrolls them into viewport.

#### JavaScript Setup
```javascript
const revealOnScroll = () => {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('revealed');
        // Unobserve to run animation only once:
        observer.unobserve(entry.target);
      }
    });
  }, {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px' /* Starts slightly before viewport entry */
  });

  document.querySelectorAll('[data-reveal]').forEach(el => observer.observe(el));
};

// Initialize after DOM load
document.addEventListener('DOMContentLoaded', revealOnScroll);
```

#### CSS Transition Rules
```css
[data-reveal] {
  opacity: 0;
  transform: translateY(30px);
  transition: opacity 0.8s cubic-bezier(0.16, 1, 0.3, 1), 
              transform 0.8s cubic-bezier(0.16, 1, 0.3, 1);
  will-change: transform, opacity;
}

[data-reveal].revealed {
  opacity: 1;
  transform: translateY(0);
}

/* Stagger sequence utility */
[data-reveal].delay-1 { transition-delay: 100ms; }
[data-reveal].delay-2 { transition-delay: 200ms; }
[data-reveal].delay-3 { transition-delay: 300ms; }
```

### B. Magnetic Button Effect (Lando-style)
An elegant interaction where elements pull toward the cursor when hovered.

```javascript
document.querySelectorAll('.btn-magnetic').forEach(btn => {
  btn.addEventListener('mousemove', (e) => {
    const rect = btn.getBoundingClientRect();
    // Calculate cursor distance from center of the button
    const x = e.clientX - rect.left - rect.width / 2;
    const y = e.clientY - rect.top - rect.height / 2;
    
    // Pull the button slightly (30% intensity)
    btn.style.transform = `translate(${x * 0.3}px, ${y * 0.3}px)`;
  });

  btn.addEventListener('mouseleave', () => {
    // Reset smoothly via CSS transition
    btn.style.transform = 'translate(0px, 0px)';
  });
});
```

### C. Live Ticker / Value Flash (TradeSense Specific)
Apply micro-animations to indicate price changes or state updates dynamically.

```css
@keyframes flashGreen {
  0% { background-color: rgba(34, 197, 94, 0.25); }
  100% { background-color: transparent; }
}

@keyframes flashRed {
  0% { background-color: rgba(239, 68, 68, 0.25); }
  100% { background-color: transparent; }
}

.flash-up {
  animation: flashGreen 0.8s ease-out;
}

.flash-down {
  animation: flashRed 0.8s ease-out;
}
```

---

## 🍱 6. Modern Layout Patterns

### Bento Grid Configuration
A modular, grid-like composition layout popular in modern tech websites.

```css
.bento-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1.25rem;
}

.bento-cell {
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border);
  border-radius: 1rem;
  padding: 2rem;
  position: relative;
  overflow: hidden;
}

/* Bento cell size modifiers */
.bento-col-2 { grid-column: span 2; }
.bento-col-3 { grid-column: span 3; }
.bento-row-2 { grid-row: span 2; }

@media (max-width: 768px) {
  .bento-grid {
    grid-template-columns: 1fr;
  }
  .bento-col-2, .bento-col-3 {
    grid-column: span 1;
  }
}
```

### Infinite Logo / Partner Marquee

#### HTML
```html
<div className="marquee">
  <div className="marquee-track">
    {/* Duplicate logo items twice to guarantee wrapping continuity */}
    <div className="logo-item">NSE</div>
    <div className="logo-item">BSE</div>
    <div className="logo-item">NIFTY</div>
    <div className="logo-item">ZERODHA</div>
    {/* Repeat items */}
    <div className="logo-item">NSE</div>
    <div className="logo-item">BSE</div>
    <div className="logo-item">NIFTY</div>
    <div className="logo-item">ZERODHA</div>
  </div>
</div>
```

#### CSS
```css
.marquee {
  overflow: hidden;
  width: 100%;
  mask-image: linear-gradient(to right, transparent, black 15%, black 85%, transparent);
}

.marquee-track {
  display: flex;
  gap: 4rem;
  width: max-content;
  animation: marqueeLoop 25s linear infinite;
}

@keyframes marqueeLoop {
  0% { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}

.marquee:hover .marquee-track {
  animation-play-state: paused;
}
```

---

## 📈 7. Indian Markets & TradeSense UI Specifications

To keep dashboard experiences optimized for professional financial trading workflows:

1. **Dark Theme Supremacy**: Active charts and tickers must default to dark background variations (`--color-bg` and `--color-bg-elevated`). This minimizes eye strain during extended, low-light trading sessions (9:15 AM - 3:30 PM IST).
2. **Dense Data Presentation**: Optimize spacing inside trading lists and charts. Favor high information density over empty whitespace. Ensure data grids align to monospaced text sizes (`JetBrains Mono` or similar).
3. **Strict Color Semantics**: 
   - Green (`#22c55e`) must represent gains, bullish trends, buy signals, or positive P&L.
   - Red (`#ef4444`) must represent losses, bearish trends, sell signals, or negative P&L.
   - *Never* cross-purpose these colors for neutral indicators.
4. **Micro-indicators**: Use green/red border blinks or flashing animations on cards when price updates or new signals stream in via WebSockets.
5. **AST Timeline Visualization**: Astro timing charts (Hora/Panchanga status tracks) should use astrological color identifiers (e.g., golden highlight gradients for positive planetary hours) alongside traditional trading elements.

---

## ✅ 8. Pre-Launch Verification Checklist

Before deploying any feature to production, evaluate the implementation against the following standards:

### Performance & Core Web Vitals
- [ ] **LCP (Largest Contentful Paint)** under 2.5s.
- [ ] **Image Optimization**: Convert assets to WebP format, implement lazy loading (`loading="lazy"`), and specify explicit width/height sizes to eliminate Layout Shifts.
- [ ] **Typography**: Preload display fonts, and enforce `font-display: swap` or `font-display: optional` (preferred for display fonts) in CSS `@font-face` declarations.
- [ ] **Tailwind / CSS Cleaning**: Ensure clean builds containing no unused utility styles.

### Interaction Polish
- [ ] Ensure all hover, focus-visible, active, and disabled states are fully styled for links, buttons, inputs, and card containers.
- [ ] Build beautiful skeleton templates for all async data loading sequences. Never display a stark, completely empty component container while fetching.
- [ ] Create dedicated error boundary UI layouts for failed API requests or network drops.
- [ ] Apply `scroll-behavior: smooth` for viewport page jumps.

### Mobile & Cross-Browser
- [ ] Test layout responsive breakpoints down to `375px` (mobile), `768px` (tablets), and up to `1440px` (standard desktop monitor scales).
- [ ] Eliminate `100vh` viewport size issues on mobile devices (e.g. Chrome/Safari URL bar jumping) by using `100dvh` or `100svh`.
- [ ] Test tactile components on real mobile devices to verify tap event targets meet standard touch dimensions (minimum `44x44px`).

### Accessibility (a11y)
- [ ] Confirm all color pairings meet the minimum **WCAG AA** contrast ratio threshold (`4.5:1` for regular text, `3:1` for large text).
- [ ] Structure the page semantically with one single `<h1>` tag followed by logical headers (`<h2>` to `<h6>`).
- [ ] Ensure full screen-reader compliance (add `aria-label` tags to visual-only indicators and `alt` properties to imagery).
- [ ] Respect client-side system animations settings: wrap motion code inside `prefers-reduced-motion` media targets.
