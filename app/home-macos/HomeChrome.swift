// VESPER's home — the chrome layer. First light.
//
// HOME-ARCHITECTURE §1.1: the home is one window with two layers, a Metal field
// below carrying the ambience and the face, and a TRANSPARENT WEBVIEW above
// carrying the widgets, the cards and the main menu. The field has existed
// since F1. This is the first time anything has been mounted on top of it.
//
// WHAT HAD TO BE TRUE FIRST, and was not. `SPIKE-013` §0, measured 2026-08-23:
// a `WKWebView` cannot be made transparent with public API on macOS 26.5. Every
// public configuration paints #FFFFFF over the ground. §0.5 then measured that
// once transparency exists by any route, `backdrop-filter` genuinely does blur
// what is behind the webview -- 41-42 pt of smeared edge inside a card against
// 0 pt outside, over a real CAMetalLayer. That is what makes this layer worth
// having: the cards are glass over the LIVE FIELD, not glass over a picture of
// it.
//
// So the chrome mounts through `GlassGuard`, and it mounts CONDITIONALLY.
// GlassGuard.verify runs three controls and answers TRANSPARENT, OPAQUE or
// UNREADABLE, and only the first of those is allowed to mount anything.
// UNREADABLE is not a pass: a reader that cannot see WebKit content reports a
// clear chrome and an opaque one identically, and the failure it would wave
// through is a white rectangle over the owner's whole screen.
//
// THE CARD SAYS `UNAVAILABLE`, AND THAT IS THE POINT. `INV-HW-2` and the
// projection's own rule: a surface renders its reading or it renders nothing,
// and a number with no producer behind it is not a reading. There is no
// producer wired to the home yet, so the card says so in the place where the
// number will go. A plausible-looking figure here would be the exact defect the
// island's `projection-unknown-is-absent` check exists to refuse.

import AppKit
import WebKit

final class HomeChrome {

    private(set) var web: WKWebView?
    private(set) var mounted = false
    /// Where the card landed, in the HOST's coordinates, so the region can be
    /// READ. "mounted" is the chrome's own word for what it did; whether a card
    /// is painting is a question for the window server.
    private(set) var cardRect: CGRect = .zero

    /// Sheet tier out of `DESIGN-FOUNDATION` §4 -- blur 24px, saturate 180%,
    /// fill α .055, radius 22px -- because these are cards, and §4 names Sheet
    /// for cards. The plate behind the face is Dock tier for the opposite
    /// reason: it is the largest surface in the composition.
    ///
    /// The card is placed in the left cluster of §14.1's ring, clear of the
    /// face's own square, so first light shows the two layers COEXISTING rather
    /// than one covering the other.
    /// The ink the card writes in — `DESIGN-FOUNDATION`'s warm off-white.
    static let inkLuma = 0.855      // relative luminance of #f4e6dc
    /// What the card's composited surface has to come down to for that ink to
    /// be readable on it. Solved from the ratio below, not chosen.
    static let inkContrastTarget = 4.5

    /// SOLVE THE CARD'S FILL, the same way the plate's was solved, for a
    /// different reason.
    ///
    /// The plate is solved so the FACE has a ground. A card is solved so its
    /// TEXT does. `DESIGN-FOUNDATION` §3 step 3 is explicit that lightness moves
    /// until the contrast target is met and that the target is measured against
    /// the COMPOSITED glass rather than the raw backdrop -- which is why a card
    /// that simply carries §4's `.055` fill is unadapted by definition: .055 is
    /// the tier's look, not an answer to what is behind it.
    ///
    /// NOT APCA, AND SAID SO. §3 names APCA `Lc ≥ 60` for text. This solves a
    /// WCAG-style luminance ratio instead, because APCA's exponents and
    /// coefficients are not something to reproduce from memory -- a contrast
    /// figure that is confidently wrong is worse than one that is honestly
    /// approximate. The ratio is a proxy, it is named as one here and in the
    /// readout, and §3's real target needs APCA's constants from source before
    /// this can claim to meet it.
    static func solvedFill(backdrop L: Double) -> Double {
        // (inkL + .05) / (groundL + .05) >= target  =>  groundL <= ...
        let ground = (inkLuma + 0.05) / inkContrastTarget - 0.05
        guard L > ground else { return 0 }
        return min(0.90, max(0, 1 - ground / max(L, 0.001)))
    }

    /// The eight slots the main menu holds, as NAMES not pictures.
    ///
    /// Owner, 2026-08-24: "same style as macos, only change is icons (we'll have
    /// to define them, then get them or build them)." So the geometry, the
    /// glass, the spacing and the behaviour are built to §10 and §14.2, and
    /// every slot carries a PLACEHOLDER glyph that is obviously one. Inventing
    /// eight icons and shipping them as though they were decided is how a
    /// placeholder becomes a design nobody chose.
    static let menuSlots = ["talk", "work", "make", "know",
                            "watch", "places", "time", "self"]

    /// The metrics card's rows, from the projection snapshot on disk.
    ///
    /// WHAT CHANGED, AND WHY THE ROWS ARE NOT HARDCODED `UNAVAILABLE` ANY MORE.
    /// This card carried five literal `UNAVAILABLE` rows since it was drawn, and
    /// the header above explains why that was right: a number with no producer
    /// behind it is not a reading. There is a producer now --
    /// `tools/home_snapshot.py` -- and it writes exactly the rows that resolved
    /// from a real routed call.
    ///
    /// OMISSION, NOT A PLACEHOLDER. `core/projection.py`'s `to_scene` already
    /// drops an unavailable reading rather than rendering one, "so the absent
    /// case cannot be styled into looking like the present case". Re-adding a
    /// row here for a key the snapshot omitted would rebuild in the surface
    /// exactly what the projection removed, and it would be this surface
    /// deciding what unknown looks like -- which is the coupling that file
    /// exists to prevent. So this renders what it is given and nothing else.
    ///
    /// WITH NOTHING TO SHOW IT SAYS SO ONCE. An empty card reads as broken and
    /// a card full of `UNAVAILABLE` reads as five failures; neither is true.
    /// One line naming the missing producer is a statement about the SYSTEM
    /// rather than a fake reading about the model, and it is the same choice
    /// `tools/island_snapshot.py` made when it wrote three columns instead of
    /// six.
    static func metricRows() -> String {
        let url = FileManager.default
            .homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/home.json")
        var rows: [(String, String)] = []
        if let data = try? Data(contentsOf: url),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let raw = obj["rows"] as? [[String: Any]] {
            for r in raw {
                if let k = r["label"] as? String, let v = r["value"] as? String {
                    rows.append((k, v))
                }
            }
        }
        if rows.isEmpty {
            return "<div class=\"row\"><span class=\"k\">no producer</span>"
                 + "<span class=\"v\">run home_snapshot.py</span></div>"
        }
        return rows.map { k, v in
            "<div class=\"row\"><span class=\"k\">\(esc(k))</span>"
          + "<span class=\"v\">\(esc(v))</span></div>"
        }.joined(separator: "\n          ")
    }

    /// The snapshot is data VESPER produced, but it is still interpolated into
    /// a page. Escaped because a value is not markup, and the day one carries a
    /// model's output is the day that stops being theoretical.
    private static func esc(_ s: String) -> String {
        s.replacingOccurrences(of: "&", with: "&amp;")
         .replacingOccurrences(of: "<", with: "&lt;")
         .replacingOccurrences(of: ">", with: "&gt;")
    }

    static func page(cardWidth: Int, cardHeight: Int, left: Int, top: Int,
                     fill: Double) -> String {
        let slots = menuSlots.enumerated().map { i, name in
            """
            <button class="slot" title="\(name) — placeholder">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <rect x="3.5" y="3.5" width="17" height="17" rx="5"/>
                <circle cx="12" cy="12" r="\(3 + i % 3)"/>
              </svg>
            </button>
            """
        }.joined()
        let t = template()
        return t.source
            .replacingOccurrences(of: "{{cardWidth}}",  with: String(cardWidth))
            .replacingOccurrences(of: "{{cardHeight}}", with: String(cardHeight))
            .replacingOccurrences(of: "{{left}}",       with: String(left))
            .replacingOccurrences(of: "{{top}}",        with: String(top))
            .replacingOccurrences(of: "{{fill}}",       with: String(fill))
            .replacingOccurrences(of: "{{slots}}",      with: slots)
            .replacingOccurrences(of: "{{METRIC_ROWS}}", with: metricRows())
    }

    /// Where the chrome's markup came from, and it is REPORTED rather than
    /// assumed.
    struct Template { let source: String; let origin: String }

    /// The shipped fallback. Byte-identical to the file at the time it was
    /// extracted.
    ///
    /// A MISSING TEMPLATE MUST NOT BLANK THE CHROME. This layer sits over the
    /// owner's whole Desktop; the failure mode of "file not found" cannot be a
    /// transparent webview with nothing in it, because that is indistinguishable
    /// from a working home with no cards. So the binary always carries a copy it
    /// can paint, and says when it fell back to it.
    static func fallbackTemplate() -> String {
        return """
        <!doctype html><meta charset="utf-8">
        <style>
          html,body{margin:0;height:100%;background:transparent;overflow:hidden;
                    font-family:-apple-system,system-ui,sans-serif;
                    -webkit-font-smoothing:antialiased;
                    color:#f4e6dc}

          /* ---- the metrics card (§14.2) ---------------------------------- */
          .card{position:absolute;left:{{left}}px;top:{{top}}px;
                width:{{cardWidth}}px;height:{{cardHeight}}px;box-sizing:border-box;
                padding:22px 24px;border-radius:22px;
                background-color:rgba(255,255,255,.055);
                background-image:linear-gradient(rgba(0,0,0,{{fill}}),
                                                 rgba(0,0,0,{{fill}}));
                -webkit-backdrop-filter:blur(24px) saturate(180%);
                backdrop-filter:blur(24px) saturate(180%);
                border:1px solid rgba(255,255,255,.14);
                box-shadow:0 8px 32px rgba(0,0,0,.22),
                           inset 0 1px 0 rgba(255,255,255,.22)}
          .t{font-size:10px;letter-spacing:.16em;text-transform:uppercase;
             color:rgba(244,230,220,.55);margin-bottom:16px}
          .row{display:flex;justify-content:space-between;align-items:baseline;
               padding:7px 0;border-top:1px solid rgba(255,255,255,.07)}
          .row:first-of-type{border-top:0}
          .k{font-size:12px;color:rgba(244,230,220,.72)}
          .v{font-size:12px;letter-spacing:.04em;color:rgba(244,230,220,.38)}

          /* ---- the main menu (§10, §14.2) -------------------------------- */
          /* Dock tier: blur 42, saturate 200%, fill .085, radius 34. The bar
             sits at the Dock's own position, bottom-centre, because §10 says
             VESPER's main menu TAKES that position rather than sharing it. */
          .dockrow{position:absolute;left:0;right:0;bottom:10px;
                   display:flex;justify-content:center;align-items:flex-end;
                   gap:14px;
                   transition:opacity .28s cubic-bezier(.32,.72,0,1)}
          /* §10: "It dims to 30% while occluded so it is visibly still there
             rather than apparently gone." Driven from Swift, which reads the
             Dock's own window rather than guessing from the cursor. */
          body.dock-up .dockrow{opacity:.30}
          .bar,.tile{box-sizing:border-box;
                     background-color:rgba(255,255,255,.085);
                     background-image:linear-gradient(rgba(0,0,0,.34),
                                                      rgba(0,0,0,.34));
                     -webkit-backdrop-filter:blur(42px) saturate(200%);
                     backdrop-filter:blur(42px) saturate(200%);
                     border:1px solid rgba(255,255,255,.13);
                     border-radius:34px;
                     box-shadow:0 10px 34px rgba(0,0,0,.30),
                                inset 0 1px 0 rgba(255,255,255,.20)}
          .bar{display:flex;align-items:center;gap:10px;padding:9px 12px}
          .tile{display:flex;align-items:center;justify-content:center;
                width:64px;height:64px;padding:0}
          .slot{width:52px;height:52px;padding:0;border:0;border-radius:15px;
                background:rgba(255,255,255,.05);
                display:flex;align-items:center;justify-content:center;
                cursor:default;
                transition:transform .22s cubic-bezier(.32,.72,0,1),
                           background .22s ease}
          .slot:hover{transform:translateY(-6px) scale(1.06);
                      background:rgba(255,255,255,.11)}
          .slot svg{width:26px;height:26px;fill:none;
                    stroke:rgba(244,230,220,.62);stroke-width:1.4}
          /* The owner's avatar (§14.2), separated from the actions the way the
             system Dock separates its trash. */
          .sep{width:1px;height:34px;background:rgba(255,255,255,.13);margin:0 4px}
          .avatar{width:52px;height:52px;border-radius:50%;
                  background:linear-gradient(160deg,rgba(255,255,255,.20),
                                                    rgba(255,255,255,.05));
                  border:1px solid rgba(255,255,255,.18);
                  display:flex;align-items:center;justify-content:center;
                  font-size:15px;letter-spacing:.06em;
                  color:rgba(244,230,220,.78)}
          .tile svg{width:24px;height:24px;fill:none;
                    stroke:rgba(244,230,220,.62);stroke-width:1.5}
          /* Every glyph in this bar is a placeholder and says so on hover.
             The dotted underline is the tell. */
          .slot,.tile{position:relative}
        </style>

        <div class="card">
          <div class="t">host</div>
          {{METRIC_ROWS}}
        </div>

        <div class="dockrow">
          <div class="bar">
            {{slots}}
            <div class="sep"></div>
            <div class="avatar" title="the owner's avatar — placeholder">A</div>
          </div>
          <!-- §14.2: "a SEPARATE expandable menu tile at its right end". Separate
               is the point: it is not a ninth slot in the bar. -->
          <div class="tile" title="expandable menu — placeholder">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 8h16M4 12h16M4 16h10" stroke-linecap="round"/>
              <path d="M17.5 15.5l2.5 2.5-2.5 2.5" stroke-linecap="round"
                    stroke-linejoin="round"/>
            </svg>
          </div>
        </div>

        """
    }

    /// Load the markup: repo first for a live loop, bundle second, inline last.
    ///
    /// WHY THE REPO PATH IS TRIED FIRST, and why that is not a hazard in a
    /// shipped build. Every CSS change cost a 19-second `swiftc` rebuild while
    /// this markup was a string literal, and iteration speed is what actually
    /// limits how good a surface looks -- a designer at 19 s per attempt
    /// produces worse work than the same designer at one second, whatever
    /// renderer is underneath. A shipped copy has no repo beside it, so the
    /// branch simply does not fire; an installed VESPER reads its own bundle.
    static func template() -> Template {
        let fm = FileManager.default
        let devPath = URL(fileURLWithPath: fm.currentDirectoryPath)
            .appendingPathComponent("app/home-macos/chrome/home.html")
        if let s = try? String(contentsOf: devPath, encoding: .utf8), !s.isEmpty {
            return Template(source: s, origin: "repo:\(devPath.path)")
        }
        if let u = Bundle.main.url(forResource: "home", withExtension: "html"),
           let s = try? String(contentsOf: u, encoding: .utf8), !s.isEmpty {
            return Template(source: s, origin: "bundle")
        }
        return Template(source: fallbackTemplate(), origin: "inline-fallback")
    }

    /// Mount the chrome over `host`, but only if the glass is actually clear.
    ///
    /// `onVerdict` is called with the guard's answer either way, so a refusal is
    /// reported rather than being a chrome that quietly never appeared.
    private(set) var cardBackdropLuma = 0.0
    private(set) var cardFill = 0.0
    private(set) var cardAdapted = false

    func mount(over host: NSView, faceRect: CGRect, screen: NSScreen,
               backdrop: URL?,
               onVerdict: @escaping (GlassGuard.Verdict) -> Void) {
        GlassGuard.verify { [weak self] verdict in
            // ONVERDICT FIRES LAST ON THE SUCCESS PATH, and it has to. Called
            // first, it ran before the card had been solved and reported the
            // struct's defaults -- "backdrop UNSAMPLED, unadapted" -- for a
            // card that was adapting correctly. The same shape as the phantom
            // dropout §2.2 records: a sampler started before the thing it
            // samples exists reads a world that does not contain it yet.
            guard let self, verdict.mayMountChrome else { onVerdict(verdict); return }

            let w = WKWebView(frame: host.bounds)
            w.autoresizingMask = [.width, .height]
            GlassGuard.makeTransparent(w)
            // The chrome sits ABOVE the field. The face's Metal layer carries
            // zPosition 10 on the host's own layer, so the webview's layer has
            // to be told to go higher -- ordering between a subview's layer and
            // a directly-added sublayer is not something to leave to insertion
            // order.
            w.wantsLayer = true
            w.layer?.zPosition = 20
            host.addSubview(w)
            self.web = w
            self.mounted = true

            // Left cluster: clear of the face's square, vertically centred on
            // it. Placed off the FACE rather than off the screen, so it stays
            // right when the face moves.
            let cw = 300, ch = 236
            let left = max(48, Int(faceRect.minX) - cw - 72)
            let top = Int(host.bounds.height - faceRect.midY) - ch / 2
            let t = max(48, top)
            self.cardRect = CGRect(x: CGFloat(left),
                                   y: host.bounds.height - CGFloat(t + ch),
                                   width: CGFloat(cw), height: CGFloat(ch))

            // §3 step 1: sample what is behind THIS card, not the screen's
            // average. A card in the left cluster sits over a different part of
            // the picture than one on the right, and one fill for both is the
            // "unadapted" the rule exists to refuse.
            //
            // §3 step 5: an unsampleable backdrop takes the tier's nominal fill
            // and is reported unadapted rather than looking solved.
            if let backdrop,
               let st = Ambience.backdropStats(url: backdrop, region: self.cardRect,
                                               screen: screen) {
                self.cardBackdropLuma = st.mean
                self.cardFill = Self.solvedFill(backdrop: st.mean)
                self.cardAdapted = true
            } else {
                self.cardBackdropLuma = 0
                self.cardFill = 0
                self.cardAdapted = false
            }

            w.loadHTMLString(Self.page(cardWidth: cw, cardHeight: ch,
                                       left: left, top: t, fill: self.cardFill),
                             baseURL: nil)
            onVerdict(verdict)
        }
    }

    /// §10's dim. Driven from Swift because the fact lives in the window
    /// server -- the page has no way to know a system Dock is over it.
    func setDockUp(_ up: Bool) {
        web?.evaluateJavaScript(
            "document.body.classList.toggle('dock-up', \(up))", completionHandler: nil)
    }

    func unmount() {
        web?.removeFromSuperview()
        web = nil
        mounted = false
    }
}
