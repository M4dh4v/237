# SĀKṢYA — Frontend Playbook
### How to build the design plan into a real, non-slop, 3D frontend with Claude Code — without losing your mind or your tokens

> This is the *how*. `SAKSHYA-MASTER-DESIGN-PLAN.md` is the *what*. Read this once end to end, then live in Part 6 (the lanes) and Part 7 (the copy-paste prompts). Everything is written so you paste a prompt and go — you should almost never have to type "read this file, read that file"; the prompts and the `CLAUDE.md`/skills do that for you.

---

## 0. Do this now (the essentials, in order — ~30–40 min of setup, then you build)

You're on a deadline, so here is the critical path. Extras come later.

1. **Move the kit into place.** I generated a `frontend-kit/` folder in your repo. Move its pieces to where Claude Code reads them:
   ```bash
   cd /path/to/sakhsya
   # project brief Claude auto-loads every session:
   mv frontend-kit/CLAUDE.md ./CLAUDE.md
   # the three project skills (auto-load on matching work):
   mkdir -p .claude/skills
   mv frontend-kit/skills/sakshya-design  .claude/skills/
   mv frontend-kit/skills/sakshya-3d      .claude/skills/
   mv frontend-kit/skills/sakshya-honesty .claude/skills/
   # the frozen contract (lives in the design system):
   mkdir -p web/src/design-system
   mv frontend-kit/contract.md web/src/design-system/contract.md
   ```
2. **Install the two general design skills** (Part 4): Anthropic `frontend-design` (already available) + `pbakaus/impeccable`. Optionally the `awwwards-3d` skill for the landing.
3. **Pick your theme** (Part 2). Tell Claude which one; it writes `tokens.css`.
4. **Install the Playwright MCP** so Claude can screenshot its own work (Part 5.4). This is the single biggest quality multiplier for non-slop UI.
5. **Run the P0 bootstrap prompt** (Part 7) on `main`. It scaffolds the design system, the app shell, stubbed API, and shared component skeletons — the frozen contract made real.
6. **Create the three worktrees** (Part 6) and paste the three lane prompts.
7. **Iterate at checkpoints** with screenshots (Part 7's checkpoint prompt), not element-by-element.

That's the whole game. The rest of this doc is the reasoning and the exact text to paste.

---

## Part 1 — AI slop: know the enemy exactly so you never ship it

"AI slop" is what a frontend looks like when a model builds from a vague prompt with no taste constraint: it reaches for the statistical average of every landing page it ever saw. The tells are specific and well-catalogued. A page reads as slop when it stacks **3+** of these; one alone is survivable. Here is the field guide, and the antidote for each.

### 1.1 Color tells
- **The purple/indigo→blue gradient.** The single most notorious tell — a `#6366F1 → #8B5CF6 → #3B82F6`-ish violet-to-blue wash, usually as a big blurry hero blob or full-section background. Also the "purple button + purple glow" default.
- **Oversaturated, evenly-spread palettes** — five colors at equal weight, none dominant, all at full saturation. Neon-on-dark with no restraint.
- **Blurred gradient "blobs"** floating behind the hero.
- **The antidote:** one dominant color + sharp, sparing accents pulled from a *real* source (a print reference, a material, an instrument). Our themes (Part 2) do this: cool structure, **one** accent used once per screen. Our indigo→cyan is only for *lines and "thinking" states*, never a full-bleed background wash. That one rule alone dodges the #1 tell.

### 1.2 Typography tells
- **Inter everywhere**, one weight, no pairing — the default font of ten thousand generated pages.
- **Gradient text** on headlines. **Oversized centered hero** text. **Emoji in headings** (🚀 ✨).
- Everything the same size; no real type scale; no mono for code/data.
- **The antidote:** a real pairing — a geometric *display* face (Space Grotesk / Sora) for headings, Inter for body, and a **mono for every hash/key/ID**. A committed type scale. Type carries the personality; make the heading treatment memorable, not defaulted. (Inter for body is fine — Inter as your *only* font is the tell.)

### 1.3 Layout / component tells
- **The template:** centered hero + one line of subtext + two CTAs → a **3-feature-card grid** (each card: an icon, a bold line, two lines of grey text) → logo cloud → pricing → FAQ accordion → footer. When you can predict the next section, it's slop.
- **Glassmorphism everywhere** — frosted translucent cards with `backdrop-blur` as the *default* surface. **Bento grids** used with no reason. **`rounded-2xl` on everything.** Drop-shadow soup. Perfect symmetry everywhere. The "shadcn defaults, untouched" look.
- **The antidote:** asymmetry with intent, a real layout idea per screen. Ours are not templates: the landing is a *scroll journey*; the dashboards are *asymmetric workspaces* (rail → stage → pulse strip). Solid quiet panels, small consistent corners (2–6px — sharp reads as "instrument"), one considered shadow, mostly flat. Blur is a rare purposeful effect, not the wallpaper.

### 1.4 Copy tells (the words themselves)
- **Banned vocabulary:** *Unleash, Supercharge, Seamless(ly), Elevate, Empower, Revolutionize, Effortless, game-changing, cutting-edge, "in seconds", "Say goodbye to ___", "The future of ___ is here", "Built for the modern ___", "Your ___, reimagined".* Plus: sparkle ✨ emoji, exclamation-everything, and the em-dash-in-every-sentence tic.
- **Vague value props** ("The all-in-one platform to grow your business"), three-word taglines that say nothing, feature lists that are adjectives not facts.
- **The antidote:** say the true, specific mechanism. Our voice is terse, exact, quietly confident: *"The key is never released until the recipient's own post-quantum signature is written to the ledger."* That sentence sells harder than "Ultimate uncompromising security" *because* it's concrete. Name the thing; state what it does; stop. (Full banned list lives in the `sakshya-design` skill so Claude enforces it automatically.)

### 1.5 Motion tells
- **Everything fades-up on scroll.** Spinning logos. Parallax with no meaning. Count-up number tickers on every stat. Hover-scale on every card. Motion applied uniformly = motion that means nothing.
- **The antidote:** motion only where it *explains* something. Our 3D earns its place — the gate's sideways-then-open **is** the pitch; the witness ring **is** the argument. If an animation doesn't teach the eye something true, cut it. (This is enforced in the `sakshya-3d` skill.)

### 1.6 The one-line test
Before shipping any screen, ask: *"If I stripped the words, would a stranger know this is a defence forensic instrument and not a Series-A SaaS?"* If the skeleton is centered-hero + 3 cards + gradient, it's slop no matter how you paint it. If it's rail + stage + a ledger that behaves like an instrument, you're clear. Claude will run this check itself via the skills, but you're the final eye at checkpoints.

---

## Part 2 — Three themes (pick one). No orange anywhere.

All three are dark, cool-structured, "restrained power". Each keeps your reserved green (checked) and red (failure). They differ in the **one accent** and the overall temperature. Tell Claude the letter; it writes `tokens.css`. You can also mix — e.g. Theme A base with Theme B's accent — but pick one to start.

### Theme A — "Abyssal Sonar"  ·  coldest, most instrument, zero warm
The safest anti-slop choice: reads unmistakably as a naval console. The accent is a signal-cyan/ice, so nothing warm ever appears.
```
--bg         #05070A   --bg-panel  #0B111A   --bg-elevated #111A26   --hairline #1B2733
--ink        #E6EDF3   --ink-muted #7D8896   --ink-faint   #4A5563
--struct-1   #3D5AFE   --struct-2  #22D3EE          (indigo → cyan, lines/thinking only)
--accent     #7DF9FF   --accent-soft #2FB6C4        (ice signal — the one glow per screen)
--verified   #34D399   --alert      #FF5470
```
Inspiration: Active Theory scene lighting, real sonar/ATC HUDs, `linear.app` restraint. **Recommended if you want the surest "this is serious defence kit" read.**

### Theme B — "Cryptographic Violet"  ·  most striking & memorable, used carefully
Yes, violet is *the* slop color — **but slop is a blurry violet gradient washed over a white hero.** A precise violet-magenta glyph used *once per screen* on a near-black forensic console is the opposite: it reads as cryptographic energy, not template. Use only if you'll hold the discipline (the skills enforce "accent once, never a background wash").
```
--bg         #09070F   --bg-panel  #120E1F   --bg-elevated #1A1330   --hairline #241B38
--ink        #ECE8F5   --ink-muted #8B84A3   --ink-faint   #564E6B
--struct-1   #4C6FFF   --struct-2  #22D3EE
--accent     #A855F7   --accent-soft #E879F9        (plasma violet → magenta, once per screen)
--verified   #34D399   --alert      #FB5779
```
Inspiration: Lusion material polish, Igloo Inc depth, cryptographic/quantum visual language. **Most distinctive; slightly higher slop risk if discipline slips.**

### Theme C — "Evidence Archive"  ·  most restrained, courtroom-credible, premium
Near-monochrome blue-slate, the quietest of the three. The through-line paper sheet uses a bone/parchment tone (`--paper`) that reads as *document warmth* without ever being orange. Feels like an archive, a courtroom exhibit, a serious instrument that has nothing to prove.
```
--bg         #0C1117   --bg-panel  #11161D   --bg-elevated #161C24   --hairline #212A34
--ink        #E8EEF4   --ink-muted #7A8794   --ink-faint   #47525E
--struct-1   #2F6FEB   --struct-2  #39C5CF
--accent     #56D4DD   --accent-soft #2C8F97       (cold teal — the one glow)
--paper      #ECE6D6                                (reserved: ONLY the document sheet)
--verified   #3FB950   --alert      #F85149
```
Inspiration: `linear.app`, `vercel.com` dark, technical documentation tools, print/archive aesthetics. **Recommended if you want maximum credibility with defence evaluators and the lowest slop risk of all.**

> My pick if you want *safe + unmistakably serious*: **A**. If you want *most memorable in a demo room*: **B**. If you want *most credible to a technical judge*: **C**. All avoid orange. The design plan's original gold is available as a swap-in accent (gold ≠ orange), but since you're slop-averse I've defaulted the three to cool accents.

**Fonts for all three:** display = **Space Grotesk** (or Sora), body = **Inter**, mono = **JetBrains Mono** (or IBM Plex Mono). All vendored locally into `web/public/fonts/` — never a CDN link (air-gap).

---

## Part 3 — Reference sites to steal from (non-cringe 3D)

Study these, name them to Claude in prompts ("in the spirit of X"), and steal the *technique*, not the look. Grouped by what to take.

**Cinematic scroll & camera-as-narrator** (for the landing, Pravāha):
- **Active Theory** — the camera never cuts, it flows; scenes assemble and dissolve. Exactly our "one continuous journey" thesis.
- **Studio Freight / Lenis** (they *make* Lenis) — buttery scroll storytelling; the reference for how scroll should *feel*.
- **Igloo Inc** (Awwwards Site of the Year) — a scroll-driven 3D journey with depth and restraint.
- **Lusion** — material quality and tasteful WebGL polish; proof that 3D can be elegant, not a tech-demo.

**Instrument / dashboard UI** (for Dvārapāla, Sūchī, Anveṣaṇa):
- **linear.app** — the gold standard for dark "instrument" UI: restraint, keyboard-first, purposeful motion, a real type system. Steal the calm.
- **vercel.com / resend.com** — dark, precise, type-driven, generous space. No slop anywhere.
- **Raycast / Cursor / Cobalt** — dev-tool density done tastefully; good for the ledger inspector and evidence panels.

**3D done right technically** (for the four scenes):
- **Bruno Simon / Three.js Journey** — the canonical R3F learning source; instancing, scroll-binding, performance.
- **14islands, Basement Studio** — production-grade R3F patterns and repos.
- **Oakley Encoder / product-configurator Awwwards sites** — how to make *one hero object* (our paper sheet, our crystal) feel premium at 60fps.

**What to take for each SĀKṢYA moment:**
- *Gate (Dvārapāla):* a security-scanner doorway, a glyph that flies sideways and *locks* with a satisfying settle. Study easing and the "weight" of the lock.
- *Witness ring:* orbiting nodes + synced pulsing light-lines; study instanced meshes and additive glow (cheap, not post-heavy).
- *Seal (crystal):* strands wrapping a core → a faceted crystal dropping with weight. Study refraction-fake (matcap) instead of real transmission (expensive).
- *Trace:* a magnifier revealing hidden marks that assemble into a token. Study staged reveals timed to scroll/click.

> The tell of *cringe* 3D is: spinning for no reason, a floating logo, physics gimmicks, low-fps stutter, mobile breakage. The tell of *tasteful* 3D is: it explains the product, holds 60fps, and degrades to a beautiful still. Your `sakshya-3d` skill encodes exactly this.

---

## Part 4 — Skills: what to install, verdict, and how

**How skills work (why you keep them lean):** a skill is a folder with a `SKILL.md`. Claude preloads only each skill's `name`+`description` (a few dozen tokens); the body loads only when your request matches the description; bundled reference files load only on demand. So having several installed is nearly free — the cost is a bloated *body*, not the count.

**Install locations:** personal `~/.claude/skills/<name>/` (everywhere) or project `.claude/skills/<name>/` (this repo, committable). Your three custom skills go in the project.

### Verdict on the ones you linked
- ✅ **anthropics/frontend-design** — the lean, official baseline; the source the others were built on. Already available in this environment. **Keep it.** It even warns against the exact terracotta/cream cliché (`#D97757`, Anthropic's own accent) — good instincts baked in.
- ✅ **pbakaus/impeccable** — by the creator of jQuery UI; the most complete: a **61-rule deterministic slop detector**, per-platform reference playbooks, live-browser iteration, subagents. Well-engineered progressive disclosure. **Install as your primary taste engine.** It's derived from the official skill, Apache-2.0, actively maintained.
  ```bash
  npx impeccable install      # run in repo root
  # then inside Claude Code:  /impeccable init
  ```
  Don't hand-copy its raw `SKILL.md` — it has template variables the installer resolves.
- ⚠️ **nextlevelbuilder/ui-ux-pro-max-skill** — genuinely different (a searchable JSON design-intelligence DB queried via a script; complements rather than competes). Useful, **but** has reproduced install bugs (partial installs, broken symlinks). Optional; if you install it, verify the `data/` and `scripts/` actually landed.
- ❌ **leonxlnx/taste-skill** — same job as impeccable but with documented portability bugs (hardcoded Windows paths, missing assets), a promotional/crypto-token layer around the repo, and heavy version sprawl. **Skip** — impeccable does this better with cleaner provenance.

### Better / additional, worth a look
- **`tsogjavklann/awwwards-3d`** — a Claude Code skill *specifically* for Awwwards-style scroll-driven 3D (Three.js + GSAP + Lenis) in the visual language of Active Theory / Lusion / Studio Freight. **This is the closest match to your landing.** Strongly consider it for Lane A.
- **`Nutlope/hallmark`** (MIT, well-regarded author) or **`superdesigndev/superdesign-skill`** — solid lighter alternatives to impeccable. Pick *one* taste engine, don't stack two (their triggers collide).
- **`claudiusararu/unslop-ui-skill`** — a catalog of ~100 named AI "tells" turned into hard rules. Good reference if you want an even more exhaustive slop list than Part 1.

### The rule for skills
**One general taste engine (impeccable) + the official baseline + your three project skills + optionally awwwards-3d.** Do not install three overlapping taste skills — they fight over the same triggers and bloat nothing but confusion. Your project skills (`sakshya-design`, `sakshya-3d`, `sakshya-honesty`) are the ones that make the output *yours*, not generic-tasteful.

---

## Part 5 — The Claude Code workflow (use Opus well, don't waste it)

You have Opus and credits, but tokens still buy you *quality per context window*: the fuller and messier the context, the worse the output. The whole game is **keep each session's context clean and pointed.** Here's the operating manual.

### 5.1 CLAUDE.md is your always-on brief
Claude auto-loads `CLAUDE.md` (repo root) into every session. I wrote yours — it's lean on purpose: the golden rules, the structure, the lane ownership, and pointers to the two big docs. **Keep it short.** A bloated CLAUDE.md taxes every message. Put detail in the skills and the design plan; CLAUDE.md just points there. (`#` at the start of any message in Claude Code appends a memory to CLAUDE.md on the fly.)

### 5.2 Plan mode before any real build
Press **Shift+Tab** to enter plan mode (read-only: Claude explores and proposes, doesn't edit). Use it to get a plan you approve *before* it writes code. For a big surface, tell it to **write the plan to a file** (`web/PLAN-lane-a.md`) so it survives a context reset and a fresh session can resume from it. Approve, then let it execute. This is your "autonomous + checkpoints" model: plan → approve → build a whole surface → screenshot → you approve/redirect.

### 5.3 Context management: /clear, /compact, and handoffs
- **`/clear`** between unrelated surfaces (finished the landing, moving to the recipient dashboard → clear). A fresh window is faster and sharper than a bloated one.
- **`/compact`** when you're mid-task but the context is getting long — it summarizes and continues. Claude also auto-compacts near the limit, but a deliberate `/compact` at a clean moment is better than an automatic one mid-thought.
- **`/rewind` (or Esc-Esc)** restores an earlier checkpoint (code, conversation, or both) if a run went sideways. Your safety net for autonomous runs.
- **Handoff notes.** Before ending a session or clearing, have Claude append to a `PROGRESS-lane-x.md`: what's done, what's next, key decisions, any gotcha. The next session reads that first (the lane prompts below do this automatically). This is how "context shares" across sessions — not magic, just a disciplined scratchpad file.

### 5.4 Give Claude eyes: the Playwright MCP (biggest quality lever)
Claude building UI blind is how slop happens. With the **Playwright MCP server**, Claude opens your running dev server, screenshots it, and *looks* — then iterates against the mock and the anti-slop rules. Install once:
```bash
claude mcp add playwright npx '@playwright/mcp@latest'
```
Then your prompts can say "run the dev server, screenshot `/`, compare to the design plan station-by-station, and fix what's off." The **screenshot → critique → fix** loop, run 2–3 times per surface, is what separates tasteful from generated. Impeccable's live-browser mode does the same. This is non-negotiable for your quality bar.

### 5.5 Subagents: keep the main thread clean
When you need broad research or verification (e.g. "check all four scenes hold 60fps", "audit every proof surface for the present-not-verified rule"), spawn a **subagent** (the Task tool, or a custom agent in `.claude/agents/`). It works in its *own* context and returns just the conclusion — your main session stays lean. Use subagents for: research, multi-file audits, test runs, and a **design-review agent** that screenshots and scores against the slop rules. Don't use them for the core building you want to watch.

### 5.6 Parallelism: git worktrees (the real answer to "3 lanes")
Subagents share one repo checkout — fine for research, dangerous for three agents *writing* at once. For true parallel building, use **git worktrees**: each lane gets its own directory + branch, so no two sessions ever touch the same working files. This is the officially-recommended pattern (and Boris Cherny, Claude Code's creator, literally lists "spin up 3–5 worktrees, each its own Claude session" as tip #1). Exact commands in Part 6.

### 5.7 Guardrails for autonomous runs
- **Permissions/allowlist:** pre-approve safe commands (`npm run build`, `npm run dev`, `git status`) so Claude doesn't stop to ask, but keep destructive ops gated. `/permissions` to manage.
- **Hooks** (`.claude/settings.json`): e.g. a post-edit hook that runs the build or a lint, so mistakes surface immediately. Optional but nice for long runs.
- **Checkpoints:** `/rewind` is your undo. Commit often (each lane on its branch) so a bad autonomous stretch is `git reset` away.

### 5.8 What actually burns tokens (and how to not)
- **Re-reading huge files repeatedly** — let Claude read once; don't paste big files inline if they're on disk (use `@path` references or just let it open them).
- **Bloated context** — `/clear` and `/compact` are free quality. A 200k-token muddled window produces worse code than a 40k-token clean one.
- **Subagents for noisy work** — research/audits dump tokens; isolate them in a subagent so the summary (not the noise) lands in your main thread.
- **Model choice per lane** — Opus for the hard, taste-critical frontend (Lanes A/B); the backend glue (Lane C) is mechanical and can run on a cheaper/faster model if you want to stretch credits. Set with `/model`.

---

## Part 6 — The three lanes (parallel, non-colliding, by layer)

The split is **by layer** so two frontend sessions never edit the same file:

| Lane | Owns (writes only these) | Consumes |
|---|---|---|
| **A — Foundation & landing** | `web/src/design-system/**`, `web/src/scenes/**`, `web/src/components/**` (shared honesty layer + WitnessRing), the app shell (`App.jsx`, router, role context, StatusStrip mount, Suspense), the landing route | the frozen contract |
| **B — Dashboards** | `web/src/dashboards/**` (Dvārapāla, Sūchī, Anveṣaṇa, Pramāṇapatra) | A's components (import only), C's api methods |
| **C — Backend glue** | `logfirst/authority/**` (new adapter routes), `web/src/api.js` (new methods) | existing pipeline (feeds, never touches) |

### The critical sequencing insight
Lanes B and C depend on interfaces Lane A and the contract define. So **do not fan out on day one.** Instead:

1. **P0 bootstrap on `main`** (one session, ~1–2 hrs): install deps, write `tokens.css` from your chosen theme, build the app shell + routing + role context, create **stub** shared components (real props, placeholder visuals) and **stub** api methods (mock data). This makes the frozen contract *real and importable*. Commit to `main`.
2. **Only now branch the three worktrees.** Each starts from a `main` that already has the contract, stubs, and tokens — so Lane B can `import { WitnessRing } from '@/components'` on day one even though Lane A hasn't built the real one yet, and Lane C can replace stub api methods without B noticing.
3. **Merge order:** C (backend real) → A (real components/scenes) → B (dashboards) → integrate on `main`. Because everyone coded against the frozen contract, merges are mostly clean.

### Worktree commands (copy-paste)
```bash
cd /path/to/sakhsya
# after P0 is committed to main:
git worktree add ../sakshya-lane-a -b lane-a-foundation
git worktree add ../sakshya-lane-b -b lane-b-dashboards
git worktree add ../sakshya-lane-c -b lane-c-backend

# open three terminals, one per dir, run `claude` in each:
cd ../sakshya-lane-a && claude      # paste Prompt A
cd ../sakshya-lane-b && claude      # paste Prompt B
cd ../sakshya-lane-c && claude      # paste Prompt C

# each lane commits to its own branch as it goes. When a lane is done:
#   git push -u origin <branch>   (or merge locally)
# integrate on main in the merge order above; then clean up:
git worktree remove ../sakshya-lane-a   # etc.
```
Each worktree is a full checkout on its own branch; edits in one never touch another. Run `npm install` inside each frontend worktree (A and B) the first time. Lane C's frontend edits are tiny (just `api.js`), so it mostly lives in Python.

> If juggling three terminals is too much on the deadline, run them **sequentially in the same clean session** with `/clear` between lanes — you lose wall-clock parallelism but keep the same clean-context discipline. The worktree setup is strictly better if you can spare the terminals.

---

## Part 7 — Copy-paste prompts

Paste these verbatim. They assume `CLAUDE.md`, the three `sakshya-*` skills, and `web/src/design-system/contract.md` are in place (Part 0), and that impeccable + Playwright MCP are installed. You should not need to add "read this, read that" — the prompts and skills handle it.

### P0 — Bootstrap (run once, on `main`)
```
We are building the SĀKṢYA frontend per SAKSHYA-MASTER-DESIGN-PLAN.md and SAKSHYA-FRONTEND-PLAYBOOK.md. This is the P0 foundation pass on main — get the frozen contract in web/src/design-system/contract.md into real, importable code so three parallel lanes can then build without colliding.

Use plan mode first: read the design plan (§4 look/feel, §5 IA, §12 cross-cutting, §14 stack), the playbook Part 6, the contract, and the sakshya-design / sakshya-3d / sakshya-honesty skills. Then propose a plan and wait for my approval before editing.

The chosen theme is THEME_A ("Abyssal Sonar").  [<-- change to your pick]

When approved, do exactly this and no more:
1. Add deps to web/: @react-three/fiber @react-three/drei three lenis framer-motion. Set up a Vite alias '@' -> web/src. Do NOT remove cytoscape yet (Lane A retires it later).
2. Vendor fonts locally into web/public/fonts/: Space Grotesk (display), Inter (body), JetBrains Mono (mono). Add @font-face; no CDN links.
3. Write web/src/design-system/tokens.css with EVERY variable named in the contract, valued for the chosen theme. Import it globally.
4. Build the app shell: App.jsx with the router and routes from the contract (/ , /darsana, /dvarapala, /suchi, /anvesana, /ledger), a RoleContext provider with a demo god-mode toggle, the StatusStrip mounted on every authed route, a lite-mode state, and <Suspense> + React.lazy boundaries ready for scene code-splitting.
5. Create STUB shared components in web/src/components/ with the EXACT props from the contract (StatusStrip, PresentNotVerified, FailClosed, Caveat, ClassificationBanner, WitnessRing, SceneFallback). Real props, minimal placeholder visuals using tokens. Add a barrel export index.js.
6. Create STUB scenes in web/src/scenes/ (GateScene, WitnessRing scene, SealScene, TraceScene) each with a *.static.jsx sibling — placeholder posters for now.
7. Extend web/src/api.js with the new methods from the contract (uploadSource, composeSource, createRecipient, uploadLeak, sourceCapacity, certificate) returning realistic MOCK data behind a DEMO_STUBS flag, so Lanes A/B are unblocked. Keep all existing methods and error shapes untouched.
8. Create empty dashboard route components in web/src/dashboards/ (placeholders that say "Lane B builds this") so routing works.

Then: run the dev server, use Playwright MCP to screenshot / and /darsana, confirm the shell renders with tokens applied, and show me the screenshots. Run `npm run build` and confirm it passes. Do not build real dashboards or real 3D yet — that's the lanes. Commit to main with a clear message.
```

### Prompt A — Foundation & landing (worktree `lane-a-foundation`)
```
You are Lane A of the SĀKṢYA frontend build (see SAKSHYA-FRONTEND-PLAYBOOK.md Part 6). You own web/src/design-system/, web/src/scenes/, web/src/components/, and the app shell + landing route. You must NOT edit web/src/dashboards/, web/src/api.js, or logfirst/ — other lanes own those. Treat web/src/design-system/contract.md as frozen; if you think it must change, stop and tell me.

Read: the design plan §4 (look/feel), §6 (the landing, all stations), §10 (the shared ledger), §12 (cross-cutting honesty), §14 (3D discipline); and the sakshya-design, sakshya-3d, sakshya-honesty skills. Use the impeccable skill for taste critique.

Work in plan mode first, write your plan to web/PLAN-lane-a.md, and get my approval. Then build in this order, committing after each:

1. Finalize the design system: real primitives (Button, Panel, Chip, Banner, mono Hash display), the shadow/spacing/type scale, all from tokens.css. Retire cytoscape.
2. Build the REAL shared honesty components to their contract props: StatusStrip (live-polling-ready via props), PresentNotVerified, FailClosed (green guarantee, fed an ApiError), Caveat (all four kinds), ClassificationBanner, SceneFallback.
3. Build the REAL WitnessRing as ONE R3F component at three scales (strip/widget/full) driven by props, with its *.static.jsx fallback. Instanced blocks + witness nodes, capped dpr, demand frameloop for the full inspect view. This is the shared "Bitcoin-feeling-told-true" artefact — honest framing per the skill.
4. Build the four landing scenes (GateScene, SealScene, TraceScene, plus WitnessRing reused) as the scroll journey Pravāha: Lenis smooth scroll, one 0→1 progress value, each station a range, camera flows never cuts, the single paper sheet is the through-line. Each scene ships its *.static.jsx poster; reduced-motion / lite-mode renders posters with identical copy. Station copy verbatim-in-spirit from the design plan §6. End at the three-door Darśana CTA.
5. Wire the app shell's landing route, skip-to-app affordance, and lite-mode toggle in StatusStrip.

Rules: no external network/CDN (air-gap); ~60fps on a weak laptop (instancing, dispose on unmount, lazy-mount per route); one accent per screen; run the anti-slop self-check from the sakshya-design skill and count tells before declaring any screen done. After each major surface, run the dev server, screenshot it via Playwright MCP, compare to the design plan station-by-station, iterate twice, then show me. Update web/PROGRESS-lane-a.md as you go.
```

### Prompt B — Dashboards (worktree `lane-b-dashboards`)
```
You are Lane B of the SĀKṢYA frontend build (see SAKSHYA-FRONTEND-PLAYBOOK.md Part 6). You own web/src/dashboards/ only: Dvārapāla (sender), Sūchī (recipient), Anveṣaṇa (investigator), and Pramāṇapatra (certificate). You must NOT edit web/src/design-system/, web/src/scenes/, web/src/components/, web/src/api.js, or logfirst/. Import shared components from '@/components' and design tokens/primitives from '@/design-system' exactly as the frozen contract (web/src/design-system/contract.md) defines them — they exist as real props even if still stubbed; do not reach past the contract. Call the backend via api.* (methods are stubbed with mock data until Lane C lands them — build against the stubs).

Read: the design plan §7 (Dvārapāla), §8 (Sūchī), §9 (Anveṣaṇa), §11 (Pramāṇapatra), §12 (cross-cutting); and the sakshya-design + sakshya-honesty skills. Use impeccable for taste.

Plan mode first, write web/PLAN-lane-b.md, get my approval. Then build, committing after each dashboard:

1. Dvārapāla (sender): the four-step rail (source → recipients → classification → seal), the four source modes (upload/compose/corpus/paste), recipient cards with inline "+ new recipient", classification banded chips, the capacity meter, and the seal step (embed the SealScene from '@/scenes' — do not rebuild it) ending unopened with the honest "nothing written until open" caption. Right-side ledger-pulse strip uses WitnessRing scale="strip".
2. Sūchī (recipient): identity chip, polling inbox list with animated new rows and state pills (sealed/opened/unavailable), the open flow that plays the compact gate in-pane (WitnessRing scale="widget"), the reader with Copy-text and Screenshot actions and the marked-copy overlay toggle, and the fail-closed-as-green-guarantee path via the shared FailClosed component.
3. Anveṣaṇa (investigator): three-mode evidence intake (paste/image/upload-whole-doc), the honest step-by-step pipeline progress trail, the TWO separated confidences (document match vs recipient attribution) never merged, the collusion ranking mode with the real-numbers caveat, and the link into the full WitnessRing with the matched leaf highlighted.
4. Pramāṇapatra: the wax-sealed certificate view with the "present" (not "verified") checks, the fixed proves-key caveat, and export to PDF/JSON; inconclusive findings export as an honest "inconclusive" report, never a firm certificate.

Rules: every async surface handles loading (show pipeline step names, never a bare spinner), error (with retry), and a meaningful empty state. Honesty rails are sacred (sakshya-honesty skill). Run the anti-slop self-check; screenshot each dashboard via Playwright MCP, iterate twice, show me. Update web/PROGRESS-lane-b.md.
```

### Prompt C — Backend glue (worktree `lane-c-backend`)
```
You are Lane C of the SĀKṢYA build (see SAKSHYA-FRONTEND-PLAYBOOK.md Part 6 and the design plan §13). You add THIN GLUE endpoints only, and the matching web/src/api.js methods. You must NOT touch logfirst/crypto, logfirst/ledger, logfirst/witness, logfirst/watermark, logfirst/forensics, or verifier/ — the do-not-touch list in §13.1 is a hard boundary. No new cryptographic behaviour, no new watermark channel, no change to what/when gets committed. Every new route feeds EXISTING pipeline functions and fails closed with the existing error shape.

Read: design plan §13 (all of it), the existing logfirst/authority/demo_api.py and web/src/api.js, and web/src/design-system/contract.md §2 (the frozen method signatures A/B are already calling against stubs).

Plan mode first, write PLAN-lane-c.md, get my approval. Then implement the §13.2 endpoints as adapters in logfirst/authority/:
1. POST /demo/source/upload — file (PDF/image/text) -> extract text body (PDF text extract; existing tesseract OCR fallback; text passes through) -> register via the EXISTING seal/distribute path. Return docId + preview + watermark-capacity from existing watermark utilities.
2. POST /demo/source/compose — {title, body} -> same existing path.
3. POST /demo/admin/recipients/create — enroll a recipient via EXISTING key-gen/enrollment; return the new card data. Companion to existing revoke/reinstate.
4. POST /leakcheck/upload — whole document (PDF/doc), extract text (layer or OCR fallback), run the EXISTING unchanged forensic pipeline; multi-page.
5. (optional) GET /demo/source/{id}/capacity ; (optional) POST /evidence/certificate rendering from an EXISTING evidence bundle.

Then replace the stubbed methods in web/src/api.js (uploadSource, composeSource, createRecipient, uploadLeak, sourceCapacity, certificate) with real calls to these routes, keeping the exact frozen signatures and the ApiError / isFailClosed / isUnreachable contract. Remove the DEMO_STUBS mock path.

Verify: `python -m pytest` stays green and the do-not-touch modules are byte-for-byte unchanged (git diff proves it). File handling stays offline/local. Update PROGRESS-lane-c.md.
```

### Checkpoint prompt (paste when a lane shows you a surface)
```
Design review this surface before we call it done. 
1. Screenshot it via Playwright MCP at desktop width, and again with prefers-reduced-motion forced (the static fallback).
2. Run the anti-slop self-check from the sakshya-design skill: count the tells (purple gradient wash, glassmorphism-default, 3-card grid, rounded-everything, gradient text, hype copy, uniform fade-up motion, pure-white-on-black). List each hit. 2+ = revise now.
3. Check the honesty rails from the sakshya-honesty skill: is any "verified" printed that should be "present"? is fail-closed green not red? are the two confidences separated? is a caveat missing where material?
4. Compare against the matching design-plan section point by point; list what's missing or off.
Then fix everything you found, re-screenshot, and show me before/after.
```

### Handoff prompt (paste before you /clear or end a session mid-lane)
```
We're pausing this lane. Update web/PROGRESS-lane-x.md so a fresh session resumes with zero context loss: (1) what's built and working, (2) the exact next step, (3) key decisions made and why, (4) any gotcha / half-finished edit / failing thing, (5) which files you were editing. Be concrete enough that a new session reads only this file + CLAUDE.md + the plan and continues. Then commit.
```

### Integration prompt (on `main`, after lanes merge)
```
All three lanes are merged. Do the integration pass: run the dev server, walk the full flow with Playwright MCP — landing scroll journey → Darśana → seal a composed doc in Dvārapāla → switch role → watch it arrive and open in Sūchī → copy the text → trace it in Anveṣaṇa → export the Pramāṇapatra. Screenshot each step. Fix any contract mismatch, styling drift, or console error. Confirm: `npm run build` passes; disconnect network and reload (no 404/hang, air-gap holds); `python -m pytest` green; do-not-touch modules unchanged. Report the walk-through with screenshots.
```

---

## Part 8 — Images & assets (what to grab from Canva, where to put them)

Everything must be **vendored locally** (air-gap) in `web/public/`. Keep it minimal — this aesthetic is mostly CSS/WebGL, not stock imagery. What's genuinely useful:

- **Backgrounds:** you rarely need a photo — the dark base + subtle WebGL is the background. If you want texture, a *very* faint noise/grain PNG (2–3% opacity) over the base kills banding and reads premium. One 512×512 tiling grain is enough. (Canva: export a subtle noise texture, or generate one in-app.)
- **The paper sheet (through-line):** a clean, slightly off-white page texture for the 3D document — subtle paper grain, no logo. Theme C's `--paper` tone. One texture, reused.
- **Fonts:** download Space Grotesk, Inter, JetBrains Mono from Google Fonts (the files, not the CDN link) into `web/public/fonts/`. This is the one asset you *must* fetch and vendor.
- **Logos/seal:** a simple SĀKṢYA wordmark/seal (for the status strip and the Pramāṇapatra wax seal). An SVG is best — crisp, tiny, tintable with tokens. Canva or a quick vector; keep it monochrome so the accent tints it.
- **Classification banners, witness/node glyphs, the gate:** all better as **CSS/SVG/WebGL**, not images — they need to animate and tint. Don't import PNGs for these.

Drop anything you make into `web/public/refs/` and tell the relevant lane "use the grain at /refs/grain.png" — the prompts already expect local assets. **Don't** pull icon packs with a house style (that's a slop vector); if you need icons, one consistent line-icon set (e.g. Lucide, vendored) tinted to `--ink-muted`.

> You do **not** need to gather images before starting. The build works with zero imagery; add the grain and the paper texture when a lane asks. Fonts are the only day-one asset.

---

## Part 9 — What I made for you, and the exact next moves

**Files I created in your repo (in `frontend-kit/`, move them per Part 0):**
- `frontend-kit/CLAUDE.md` → repo root. The always-loaded project brief.
- `frontend-kit/skills/sakshya-design/SKILL.md` → `.claude/skills/`. Visual language + anti-slop rules + Sanskrit names + copy voice.
- `frontend-kit/skills/sakshya-3d/SKILL.md` → `.claude/skills/`. R3F/Lenis performance budget + mandatory static fallbacks + the four scenes.
- `frontend-kit/skills/sakshya-honesty/SKILL.md` → `.claude/skills/`. The credibility rails (present-not-verified, fail-closed, caveats, truthful framing).
- `frontend-kit/contract.md` → `web/src/design-system/contract.md`. The frozen treaty between the three lanes.
- `SAKSHYA-FRONTEND-PLAYBOOK.md` → this doc (already at repo root).

**Your critical path (repeat of Part 0, now that you've read the reasoning):**
1. Move the kit into place (Part 0 commands).
2. Install skills: `npx impeccable install` + `/impeccable init`; keep the built-in `frontend-design`; optionally `awwwards-3d` for Lane A.
3. Install Playwright MCP: `claude mcp add playwright npx '@playwright/mcp@latest'`.
4. **Pick your theme letter** (A / B / C) and edit it into the P0 prompt.
5. Run **P0 bootstrap** on `main`, approve its plan, let it scaffold, review the screenshots, commit.
6. Create the **three worktrees** (Part 6), paste **Prompts A / B / C**.
7. Use the **checkpoint prompt** at each surface; the **handoff prompt** before any `/clear`; the **integration prompt** at the end.

**Sequencing for the deadline (essentials before extras):**
- Must-have for a demo: P0 shell + theme + Lane C endpoints + Lane B's Sūchī (open→gate→fail-closed) and Anveṣaṇa (trace→result) + one landing hero (Stations 0–2). That's the spine of the pitch.
- Nice-to-have: full six-station landing, seal crystal polish, collusion ranking view, certificate PDF styling, recipient groups, evidence log.
- If time is tight, build the **static fallbacks first** for the 3D moments — they're the demo-safe floor, and the live 3D becomes an upgrade, not a risk.

**Open calls worth confirming (design plan §16) before lanes harden — none block P0:** role auth = frictionless UI select (assumed yes); exact Navy classification labels; scroll lib = Lenis+Framer (assumed); retire cytoscape (assumed yes); certificate = PDF+JSON (add .docx?).

---

*You now have the what (design plan), the how (this playbook), the guardrails (three skills + CLAUDE.md), and the treaty (frozen contract). Paste P0 and go. Ping me for anything — a theme tweak, a fourth skill, or if a lane hits a wall.*
