# GuavaMango Flight Deck — Design QA

**Source visual truth**

- `/home/john/Alpacaman/docs/design/guavamango-flight-deck-reference.png`
- Source pixels: `1487 × 1058`
- Selected state: white desktop cockpit, paused agent, market closed, connected Alpaca paper account.

**Rendered implementation**

- `/home/john/Alpacaman/docs/design/guavamango-flight-deck-implementation-matched-final.png`
- Browser-rendered pixels: `1487 × 1057`
- CSS viewport used for pixel-matched capture: `1502 × 1068`, desktop, density 1.
- A one-pixel white row was added to the bottom of the rendered capture for a non-distorting `1487 × 1058` comparison. No scaling was applied.
- The intended `1536 × 1024` CSS viewport was also captured at `/home/john/Alpacaman/docs/design/guavamango-flight-deck-implementation-final.png`; it rendered without horizontal document overflow.
- Comparison state: accepted signed replay, scroll position 0, deterministic gate detail collapsed.

**Comparison evidence**

- Full view: `/home/john/Alpacaman/docs/design/guavamango-flight-deck-comparison-full.jpg`
- Focused hero/account/decision/pipeline: `/home/john/Alpacaman/docs/design/guavamango-flight-deck-comparison-hero.jpg`
- Focused positions/risk/options/history/architecture: `/home/john/Alpacaman/docs/design/guavamango-flight-deck-comparison-lower.jpg`
- Mobile capture: `/home/john/Alpacaman/docs/design/guavamango-flight-deck-mobile-final.png`

**Findings**

- No actionable P0, P1, or P2 findings remain.
- Fonts and typography: Barlow Condensed recreates the source's narrow editorial display face; DM Sans and JetBrains Mono preserve legibility for body copy and telemetry. Heading scale, optical hierarchy, tracking, truncation, and wrapping match the source closely.
- Spacing and layout rhythm: header, split cockpit, six-stage workflow, and lower instrument grid retain the source proportions and precision-rule rhythm. The responsive implementation collapses cleanly without document-level horizontal overflow.
- Colors and visual tokens: white paper, near-black ink, mango yellow, coral, cobalt, and semantic green closely match the source. Borders remain deliberately thin and shadow-free.
- Image quality and asset fidelity: the source-generated mango arc, decision radar, and coral orbit are used as measured raster assets. Phosphor supplies all functional icons; no handmade SVG, emoji, CSS illustration, or placeholder asset is used.
- Copy and content: intentional truth-preserving deviations replace the mock's fictional `94%` confidence with `UNSCORED`, distinguish research statistics from broker P&L, label the active strategy as long-only equity, and describe Options Lab as an integrated capability with no active order. These deviations improve product integrity without changing the visual hierarchy.

**Interaction and runtime checks**

- Accepted proof button loads the accepted signed replay and active state.
- Rejection proof button loads the rejected explanation, then successfully returns to the accepted proof.
- Deterministic risk-gate disclosure opens and closes.
- Live shadow is visibly disabled in public replay mode and remains available in the authenticated local cockpit.
- Mobile viewport `390 × 844` has no document-level horizontal overflow; navigation remains horizontally discoverable without a visible scrollbar.
- Browser console warnings/errors checked after the final build: none.
- Intermediate desktop width `~1265px` was rechecked after the final header breakpoint patch: wordmark, navigation, agent status, and broker badge remain separated and aligned.
- `pnpm --dir apps/web lint`: passed.
- `pnpm --dir apps/web build`: passed.

**Comparison history**

1. Initial implementation showed source-crop residue over the account P&L and black scroll artifacts beside the radar/options imagery (P2). The three raster crops were tightened and remeasured. Post-fix desktop evidence shows clean UI text and isolated decorative assets.
2. Initial Options Lab title wrapped into two lines at desktop width (P2). The title row was allowed to span the options instrument while the copy and payoff stay in their measured columns. Post-fix evidence shows a single-line `OPTIONS LAB` title, matching the source.
3. Initial mobile capture exposed a native horizontal navigation scrollbar (P2). The nav keeps touch scrolling but hides the visual scrollbar. Post-fix mobile evidence has no document overflow or visible scrollbar.
4. A follow-up check at the Codex app's `~1265px` content width found the GuavaMango wordmark touching the Cockpit navigation label (P2). The `1201–1350px` header now uses explicit compact column bounds, while `≤1200px` moves navigation to a dedicated row. Independent post-fix browser inspection confirmed all four header regions are separated and visually aligned.

**Open Questions**

- None blocking. Live paper content will naturally replace empty broker states when Alpaca returns real positions, fills, and equity movement.

**Implementation Checklist**

- [x] Source visual recreated as the single selected concept.
- [x] Honest broker, AI, risk, options, research, and architecture states wired.
- [x] Desktop and mobile browser verification complete.
- [x] Core replay interactions verified.
- [x] Lint and production build pass.

**Follow-up Polish**

- P3: after real broker fills exist, re-check dense table rows at the smallest supported viewport with production-length option symbols.

final result: passed
