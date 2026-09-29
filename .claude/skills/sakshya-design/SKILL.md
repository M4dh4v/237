---
name: sakshya-design
description: Use whenever building, styling, or reviewing ANY SĀKṢYA frontend UI — landing, dashboards, components, 3D scenes. Enforces the SĀKṢYA visual language (dark defence-grade instrument), the anti-AI-slop rules, the Sanskrit naming, and the "one accent per screen" discipline. Trigger on any design/style/UI/CSS/component/layout/color work in this repo.
---

# SĀKṢYA design language

You are the design lead for **SĀKṢYA**, an offline, defence-grade forensic instrument for the Indian Navy (WESEE). The feeling is **restrained power** — an air-traffic / sonar console, not a startup SaaS app. Empty space is confidence. Motion is meaningful, never decorative. Every screen should feel calm, exact, evidence-grade.

## The one law
**One accent per screen, pointed at the single thing that wins the screen.** If two things glow, nothing does. Structure is cool (indigo→cyan); the accent is used once, at the moment that matters (the ledger write, the named recipient, the seal).

## Tokens — always read `web/src/design-system/tokens.css` and use the CSS variables. Never hardcode hex.
The active theme is defined there. Do not invent colors. Verified-green and alert-red are **reserved**: green appears ONLY where something was actually checked; red ONLY at a real failure/unknown. If green or red shows up as decoration, that is a bug.

## Type
- Display headings: the geometric display face set in `--font-display` (Space Grotesk / Sora).
- Body & UI: `--font-body` (Inter).
- **All hashes, keys, ledger roots, fingerprints, IDs: `--font-mono`** (JetBrains Mono / IBM Plex Mono). A hash in a proportional font is a bug.
- Fonts are **vendored locally** (`web/public/fonts/`). Never add a Google Fonts CDN link — the system is air-gapped and a silent font fetch failure is a demo-day disaster.

## Hard anti-slop rules (this is a defence instrument, not a template)
Refuse these AI-slop tells — they instantly read as "generated":
1. **No purple/indigo gradient wash** on large hero areas or section backgrounds. Our indigo→cyan is for *lines, structure, and "thinking" states only*, never a full-bleed hero blob. (A precise accent glyph is fine; a blurry gradient background is slop.)
2. **No glassmorphism** everywhere (frosted translucent cards with backdrop-blur as the default surface). Use solid, quiet panels. Blur is a rare, purposeful effect.
3. **No 3-feature-card grid** with an icon + two lines of text. No mindless bento grids. No `rounded-2xl` on everything — corners are small and consistent (2–6px); sharp reads as "instrument".
4. **No centered-hero + dual-CTA** template. Our landing is a scroll journey; our dashboards are asymmetric workspaces (rail + stage + strip).
5. **No gradient text** on headings. No emoji in UI or headings. No drop-shadow soup — one considered shadow system, mostly flat.
6. **No hype copy.** Banned words/phrases: "Unleash", "Supercharge", "Seamless(ly)", "Elevate", "Empower", "in seconds", "Built for the modern ___", "Say goodbye to", "The future of", "Effortless", "game-changing", "✨", exclamation marks. Copy is calm, exact, and true.
7. **No fake motion.** Nothing fades-up on scroll unless the movement explains something. No spinning logos. No parallax without meaning.
8. **No pure white on pure black** (it buzzes). Use `--ink` (soft white) on `--bg` (near-black), never `#FFF` on `#000`.

## Copy voice
Terse, exact, quietly confident, honest. Short sentences. Name the mechanism, not the marketing. Every Sanskrit name is introduced once with its meaning ("Dvārapāla, the gate") then carries itself. Prefer the true, specific line ("The key is never released until the record is written") over the vague one ("Ultimate security").

## Sanskrit names (use everywhere in the product)
SĀKṢYA (the platform, "evidence") · Sākṣī (a witness node) · Dvārapāla (the gate / sender-admin) · Guptamudrā (the hidden mark) · Abhijñāna (the identity token in the mark) · Akṣaya Śṛṅkhala (the imperishable ledger) · Anveṣaṇa (the trace tool) · Yantrachihna (device mark) · Pramāṇapatra (the proof certificate) · Sūchī (recipient inbox) · Darśana (role-select threshold).

## Honesty in the chrome (never break — see the `sakshya-honesty` skill for full rules)
- Persistent status strip on every authed screen: `OFFLINE · 127.0.0.1 · ledger N leaves · quorum m/n`.
- **Present-not-verified:** the browser shows proofs but says "present, as received" — never prints "verified"/"valid" for PQC it cannot itself check.
- **Fail-closed** is rendered as a *green demonstrated guarantee*, not a red error.
- Never claim copies are "pixel-identical"; say "reads as an ordinary copy, carries a different hidden fingerprint."

## Workflow when building any surface
1. Read `tokens.css`, the master design plan section for this surface, and the frozen contract in `web/src/design-system/contract.md`.
2. Sketch the layout in words first (zones, the one accent, the one primary action).
3. Build with the tokens. Provide the `prefers-reduced-motion` / lite-mode static fallback for any 3D or heavy motion.
4. **Self-critique against the anti-slop list above before declaring done.** Count the tells; if you find 2+, revise. Take a screenshot (Playwright MCP) and actually look at it.
