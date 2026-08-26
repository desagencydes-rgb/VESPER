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

// MARK: - The two directions between the page and the runtime

/// What the owner typed, on its way to the runtime.
///
/// THE WEBVIEW CANNOT REACH PYTHON AND MUST NOT TRY. It has no socket, no
/// interpreter and no business holding one: the page is a SURFACE, and a
/// surface that can start a process is a surface that can be talked into
/// starting one. So the field posts to Swift, Swift appends a line to a file,
/// and the runtime -- which already owns the bus, the ladder and the cost
/// policy -- picks it up. That is the same direction home.json already runs in,
/// reversed, rather than a second kind of channel.
///
/// APPEND, NEVER REWRITE. Two utterances typed a moment apart must both
/// survive; a whole-file write would drop whichever lost the race and report
/// nothing. One JSON object per line, which is also what makes a partial write
/// recoverable -- a torn last line is one lost utterance, not a lost file.
final class SayBridge: NSObject, WKScriptMessageHandler {

    static let name = "vesperSay"
    /// The page asking to be typed into.
    ///
    /// VESPER IS AN ACCESSORY APP (`LSUIElement`), so it has no Dock tile and
    /// does not become active by being clicked the way an ordinary app does.
    /// The ground can become key -- but only while the application is active,
    /// and nothing was making it active. So the field could be clicked, showed
    /// a caret, and still received no keystrokes.
    ///
    /// Requested by the PAGE rather than taken on every click: activating on
    /// any mouse-down anywhere would steal focus from whatever the owner is
    /// doing every time the cursor crossed the desktop, which is the behaviour
    /// SS10 refuses for the Dock and refuses here for the same reason.
    static let focusName = "vesperFocus"
    /// The page reporting how far through VESPER's own sentence it is.
    ///
    /// A CHANNEL, NOT A TRIGGER. The chrome does not tell the face to "look
    /// like it is talking" -- it reports which word of the reply is on screen,
    /// and Behaviour.swift decides what that looks like. Keeping the decision
    /// on the Swift side is what lets the audio path replace the SOURCE later
    /// without touching a line of the animation.
    static let speakingName = "vesperSpeaking"
    /// Set when a speaking report arrives. Read by the host's render tick.
    ///
    /// Held here rather than pushed straight at the driver because the message
    /// handler runs on the main queue between frames and the driver is stepped
    /// inside one -- writing a level the frame is halfway through reading is a
    /// tear nobody would ever see and nobody could ever explain.
    private(set) var speechLevel: Float = 0
    private(set) var speechIsFromText = false
    static var outbox: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/say.jsonl")
    }

    func userContentController(_ c: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        if message.name == Self.focusName {
            NSApp.activate(ignoringOtherApps: true)
            if let w = message.webView?.window {
                w.makeKeyAndOrderFront(nil)
                w.makeFirstResponder(message.webView)
            }
            return
        }
        if message.name == Self.speakingName {
            guard let raw = message.body as? String,
                  let d = raw.data(using: .utf8),
                  let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any]
            else { return }
            let lvl = (o["level"] as? NSNumber)?.floatValue ?? 0
            // `none` IS AN EXPLICIT STATE, not the absence of a report. A page
            // that stops posting because it was torn down mid-sentence would
            // otherwise leave the face mouthing forever; the host's staleness
            // fallback would eventually correct it, and eventually is not the
            // same as correctly.
            speechIsFromText = (o["source"] as? String) == "textReveal"
            speechLevel = speechIsFromText ? min(max(lvl, 0), 1) : 0
            return
        }
        guard message.name == Self.name,
              let text = message.body as? String else { return }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        // TYPED, SO CERTAIN AND FINAL, and said explicitly rather than left to
        // a default. core/intake.py distinguishes `confidence: null` -- meaning
        // certainty is not a question on this channel -- from a recogniser's
        // 1.0, and the record cannot be audited later if the two collapse.
        let obj: [String: Any] = ["text": trimmed, "source": "typed",
                                  "final": true,
                                  "at_ms": Int(Date().timeIntervalSince1970 * 1000)]
        guard let data = try? JSONSerialization.data(withJSONObject: obj),
              var line = String(data: data, encoding: .utf8) else { return }
        line += "\n"

        let url = Self.outbox
        try? FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        if let h = try? FileHandle(forWritingTo: url) {
            defer { try? h.close() }
            _ = try? h.seekToEnd()
            try? h.write(contentsOf: Data(line.utf8))
        } else {
            try? Data(line.utf8).write(to: url)
        }
    }
}


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

    /// What VESPER is doing, read from the state the runtime writes.
    ///
    /// THE FACE WAS BUILT AND NEVER CONNECTED. `Behaviour.swift` carries
    /// fourteen behaviours with distinct gaze, blink, breath and dispersal, and
    /// the only thing that has ever selected one is `--demo`, cycling them on a
    /// timer so they could be seen. So a face able to express thinking,
    /// listening and talking has been resting through every call VESPER has
    /// made -- the same built-and-unreached shape as `Provider.profile_id`
    /// sitting unread, and the egress class applied at registration and never
    /// at the choke point.
    ///
    /// READ, NOT PUSHED, and polled rather than notified. The runtime is a
    /// separate process; a push would need a second channel between the same
    /// two processes, and `tools/ops/alarm_wake_linux.py` records what two
    /// mechanisms writing one piece of state costs. The snapshot is already
    /// the channel.
    ///
    /// AN ABSENT FILE MEANS `resting`, WHICH IS THE TRUE READING. Nothing is
    /// running, so nothing is happening -- unlike a stale `thinking`, which
    /// would report work that is not occurring.
    static func faceBehaviour() -> String {
        let url = FileManager.default
            .homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/home.json")
        guard let data = try? Data(contentsOf: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let face = obj["face"] as? [String: Any],
              let b = face["behaviour"] as? String, !b.isEmpty
        else { return "resting" }
        return b
    }

    /// The whole conversation, as JSON, for the history bar.
    ///
    /// PUSHED AS DATA, NOT AS MARKUP. The page builds the rows and sets each
    /// line with `textContent`, so a model's output cannot become an element.
    /// Handing over pre-built HTML would put that decision in the one place
    /// least able to make it -- the layer whose whole job is to render.
    static func historyJSON() -> String {
        let url = FileManager.default
            .homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/home.json")
        guard let data = try? Data(contentsOf: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let entries = obj["transcript"] as? [[String: Any]]
        else { return "[]" }
        let rows: [[String: String]] = entries.compactMap { e in
            guard let text = e["text"] as? String, !text.isEmpty else { return nil }
            return ["who": (e["who"] as? String) ?? "owner", "text": text]
        }
        guard let out = try? JSONSerialization.data(withJSONObject: rows),
              let s = String(data: out, encoding: .utf8) else { return "[]" }
        return s
    }

    /// The latest line and who said it, for the stage.
    ///
    /// ONE LINE, NOT A LIST. The bottom of the home is a stage: what the owner
    /// said appears, comes apart, and the answer lands in the same place. A
    /// scrolling transcript would make this a chat window, and the thing it
    /// becomes once speech lands has nothing to scroll.
    ///
    /// Returned as (text, who) rather than as markup, because the page builds
    /// one element per character to dissolve it and cannot be handed a string
    /// that is already HTML.
    static func stageLine() -> (String, String) {
        let url = FileManager.default
            .homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/home.json")
        guard let data = try? Data(contentsOf: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let entries = obj["transcript"] as? [[String: Any]],
              let last = entries.last,
              let text = last["text"] as? String, !text.isEmpty
        else { return ("", "vesper") }
        return (text, (last["who"] as? String) ?? "owner")
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
                     convoLeft: Int,
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
            .replacingOccurrences(of: "{{convoLeft}}",  with: String(convoLeft))
            .replacingOccurrences(of: "{{cardWidth}}",  with: String(cardWidth))
            .replacingOccurrences(of: "{{cardHeight}}", with: String(cardHeight))
            .replacingOccurrences(of: "{{left}}",       with: String(left))
            .replacingOccurrences(of: "{{top}}",        with: String(top))
            .replacingOccurrences(of: "{{fill}}",       with: String(fill))
            .replacingOccurrences(of: "{{slots}}",      with: slots)
            .replacingOccurrences(of: "{{METRIC_ROWS}}", with: metricRows())
            .replacingOccurrences(of: "{{FACE}}", with: faceBehaviour())
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
        <body data-face="{{FACE}}">
        <style>
          /* SS5's stack, in the order the specification sets it.
             Aeonik and Canela are named FIRST even though neither is licensed yet: the
             day they are bought and installed they take over with no code change, and
             until then the cascade falls through. `Outfit` is the substitute
             DESIGN-FOUNDATION itself names; Futura is what this machine actually has
             that shares Aeonik's geometric construction. -apple-system last, so there
             is always a face.

             THE EMOJI FACE IS DECLARED EXPLICITLY. Without it the cascade hands a
             colour emoji to whichever text face matched first, and a geometric
             grotesque has no glyph for one -- which is half of why they rendered as
             boxes. The other half was the dissolve splitting them; see the script. */
          :root{--ink:#f4e6dc;
                --face-body:"Aeonik","Outfit","Futura",-apple-system,system-ui,
                            "Helvetica Neue",sans-serif;
                --face-emoji:"Apple Color Emoji"}
          html,body{margin:0;height:100%;background:transparent;overflow:hidden;
                    font-family:var(--face-body),var(--face-emoji);
                    -webkit-font-smoothing:antialiased;
                    color:var(--ink)}

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

          /* ---- the field, top right (SS14.2) --------------------------------
             Moved off the bottom because the bottom is now the STAGE. Two surfaces
             competing for the same edge is how a composition stops reading, and the
             one that has to be looked at while typing is not the one that should sit
             under the face. */
          .field{position:absolute;top:38px;right:28px;width:360px;
                 box-sizing:border-box;display:flex;align-items:center;gap:12px;
                 padding:13px 18px;border-radius:18px;z-index:6;
                 background-color:rgba(255,255,255,.055);
                 background-image:linear-gradient(rgba(0,0,0,0.42),rgba(0,0,0,0.42));
                 -webkit-backdrop-filter:blur(24px) saturate(180%);
                 backdrop-filter:blur(24px) saturate(180%);
                 border:1px solid rgba(255,255,255,.18);
                 box-shadow:0 8px 32px rgba(0,0,0,.22),
                            inset 0 1px 0 rgba(255,255,255,.22);
                 transition:border-color .3s ease, box-shadow .3s ease}
          .field:focus-within{border-color:rgba(255,255,255,.34);
                 box-shadow:0 10px 38px rgba(0,0,0,.28),
                            inset 0 1px 0 rgba(255,255,255,.30)}
          .field input{flex:1;background:transparent;border:0;outline:0;
                       font-family:inherit;font-size:13.5px;color:#f4e6dc;
                       letter-spacing:.01em}
          .field input::placeholder{color:rgba(244,230,220,.32)}

          /* The state dot: VESPER's activity, read from the same key the face is
             driven from, so it cannot disagree with the expression above it. */
          .dot{width:8px;height:8px;border-radius:50%;flex:0 0 auto;
               background:rgba(244,230,220,.34);
               transition:background .4s ease, box-shadow .4s ease}
          body[data-face="thinking"] .dot,
          body[data-face="working"]  .dot{background:rgba(244,230,220,.88);
               box-shadow:0 0 10px rgba(244,230,220,.45);
               animation:pulse 1.6s ease-in-out infinite}
          body[data-face="talking"]  .dot{background:rgba(180,220,255,.92);
               box-shadow:0 0 12px rgba(180,220,255,.50);
               animation:pulse 1.1s ease-in-out infinite}
          body[data-face="listening"] .dot{background:rgba(180,255,210,.90);
               box-shadow:0 0 12px rgba(180,255,210,.45);
               animation:pulse 2.2s ease-in-out infinite}
          body[data-face="wondering"] .dot{background:rgba(244,190,150,.90);
               box-shadow:0 0 12px rgba(244,190,150,.45)}
          @keyframes pulse{0%,100%{opacity:1}50%{opacity:.45}}

          /* ---- the conversation, bottom right ---------------------------------
             A CARD, not a bare line on the ground. The line read as a caption over the
             wallpaper; at this length it needs a ground of its own to stay legible,
             and SS4 names Sheet for cards.

             BOTTOM RIGHT AND ABOVE THE DOCK ROW rather than beside it. The main menu
             is centred and grows with its contents, so anything sharing its band gets
             pushed into it the moment a slot is added. Sitting above it is stable
             under a menu of any width.

             AND ANCHORED TO THE FACE, NOT TO THE VIEWPORT. `right: 26px` with a
             `min(38vw, 520px)` width put this cluster over the face card on the
             owner's display: a viewport-derived width cannot avoid an element it
             cannot see, so the two were only ever coincidentally clear of each other.
             `{{convoLeft}}` is `faceRect.maxX + 40` computed in Swift, which is how
             the HOST card on the left has always been placed. `max-width` with
             `margin-left:auto` then keeps it from sprawling on a wide screen while
             still starting no further left than the face allows. */
          .convo{position:absolute;left:{{convoLeft}}px;right:26px;bottom:104px;
                 max-width:420px;margin-left:auto;
                 display:flex;flex-direction:column;gap:10px;z-index:7}

          /* The history bar: the OLDEST line, one row, until it is asked to open. */
          .history{box-sizing:border-box;border-radius:16px;overflow:hidden;
                   background-color:rgba(255,255,255,.045);
                   background-image:linear-gradient(rgba(0,0,0,0.40),rgba(0,0,0,0.40));
                   -webkit-backdrop-filter:blur(22px) saturate(175%);
                   backdrop-filter:blur(22px) saturate(175%);
                   border:1px solid rgba(255,255,255,.11);cursor:default;
                   max-height:44px;
                   transition:max-height .46s cubic-bezier(.32,.72,0,1),
                              border-color .3s ease, background-color .3s ease}
          .history:hover{border-color:rgba(255,255,255,.20);
                         background-color:rgba(255,255,255,.065)}
          .history.open{max-height:min(46vh,420px);overflow-y:auto}
          .hrow{display:flex;gap:10px;align-items:baseline;padding:11px 16px;
                font-size:12.5px;line-height:1.45;
                border-top:1px solid rgba(255,255,255,.055)}
          .hrow:first-child{border-top:0}
          .history:not(.open) .hrow:not(:first-child){display:none}
          .hwho{flex:0 0 auto;min-width:46px;font-size:9px;letter-spacing:.15em;
                text-transform:uppercase;color:rgba(244,230,220,.30)}
          .htext{flex:1;color:rgba(244,230,220,.66);
                 overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
          .history.open .htext{white-space:normal;overflow:visible}
          .hcue{flex:0 0 auto;font-size:9px;letter-spacing:.13em;text-transform:uppercase;
                color:rgba(244,230,220,.26);transition:opacity .3s ease}

          /* The card: the current exchange, and the only thing that animates. */
          .stage{box-sizing:border-box;padding:18px 20px;border-radius:20px;
                 min-height:66px;display:flex;align-items:flex-end;
                 background-color:rgba(255,255,255,.055);
                 background-image:linear-gradient(rgba(0,0,0,0.44),rgba(0,0,0,0.44));
                 -webkit-backdrop-filter:blur(24px) saturate(180%);
                 backdrop-filter:blur(24px) saturate(180%);
                 border:1px solid rgba(255,255,255,.15);
                 box-shadow:0 10px 36px rgba(0,0,0,.26),
                            inset 0 1px 0 rgba(255,255,255,.22)}
          .say{font-size:14px;line-height:1.55;letter-spacing:.004em;
               color:rgba(244,230,220,.94);max-height:132px;overflow:hidden}
          .say.vesper{color:rgba(230,240,255,.92)}
          .say b{display:inline-block;font-weight:inherit;white-space:pre-wrap;
                 will-change:transform,opacity,filter}
          .say.in b{animation:arrive .40s cubic-bezier(.22,.9,.24,1) both}
          .say.out b{animation:scatter .74s cubic-bezier(.4,0,.7,.2) both}
          @keyframes arrive{
            from{opacity:0;filter:blur(6px);transform:translateY(8px) scale(.98)}
            to  {opacity:1;filter:blur(0);transform:none}}
          /* THE DISSOLVE. Every glyph takes its own direction from a per-character
             custom property, so the line comes apart rather than sliding away as a
             block -- the same idea as the face's dispersal tier, where each point
             drifts to its own resting place instead of translating together. */
          @keyframes scatter{
            0%  {opacity:1;filter:blur(0);transform:none}
            100%{opacity:0;filter:blur(8px);
                 transform:translate(var(--dx),var(--dy)) rotate(var(--rot)) scale(.74)}}

        </style>

        <div class="card">
          <div class="t">host</div>
          {{METRIC_ROWS}}
        </div>


        <div class="field">
          <span class="dot" title="what VESPER is doing"></span>
          <input id="say" type="text" autocomplete="off" spellcheck="false"
                 placeholder="say something to VESPER">
        </div>


        <div class="convo">
          <div class="history" id="history">
            <div class="rows" id="hrows"></div>
          </div>
          <div class="stage"><div class="say" id="stage"></div></div>
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

        <script>
          // The field's only job: hand the text to Swift and clear itself. It does not
          // render the result -- the transcript is pushed back in by the runtime, so
          // what the owner sees is what VESPER actually recorded rather than an
          // optimistic echo that might never have arrived.
          (function () {
            var f = document.getElementById('say');
            if (!f) return;
            // ASK FOR FOCUS ON POINTER-DOWN, before the click resolves. VESPER is an
            // accessory app and does not activate by being clicked; without this the
            // field shows a caret and receives nothing.
            ['pointerdown', 'focus'].forEach(function (ev) {
              f.addEventListener(ev, function () {
                try { window.webkit.messageHandlers.vesperFocus.postMessage('1'); }
                catch (err) { /* no bridge: the keydown handler reports it */ }
              });
            });
            f.addEventListener('keydown', function (e) {
              if (e.key !== 'Enter') return;
              var v = f.value.trim();
              if (!v) return;
              try {
                window.webkit.messageHandlers.vesperSay.postMessage(v);
                f.value = '';
              } catch (err) {
                // NO SILENT SWALLOW. If the bridge is absent the owner has just typed
                // into a void, and the field saying so is the only way they would know.
                f.value = '';
                f.placeholder = 'not connected to the runtime';
              }
            });
          })();
        </script>

        <script>
          // THE CONVERSATION SURFACE. The card animates the current exchange; the bar
          // above it holds the history. Both are driven entirely from data pushed by
          // Swift -- the page keeps no record of its own, so a refresh cannot disagree
          // with the runtime about what was said.
          (function () {
            var stage = document.getElementById('stage');
            var hist  = document.getElementById('history');
            var hrows = document.getElementById('hrows');
            if (!stage) return;
            var showing = '';

            // SPLIT BY GRAPHEME, NOT BY INDEX. `text[i]` walks UTF-16 CODE UNITS, so
            // an emoji -- a surrogate pair, often several joined by ZWJ -- was torn
            // into halves that are not characters at all. That is why they rendered as
            // boxes: the dissolve had already destroyed them before the font was ever
            // asked for a glyph. Intl.Segmenter is the correct instrument; Array.from
            // is the fallback and at least keeps surrogate pairs whole.
            var seg = (typeof Intl !== 'undefined' && Intl.Segmenter)
              ? new Intl.Segmenter(undefined, { granularity: 'grapheme' }) : null;
            function graphemes(s) {
              if (seg) return Array.from(seg.segment(s), function (g) { return g.segment; });
              return Array.from(s);
            }

            // The card shows 288 characters (48 per line over six lines, measured).
            // Every glyph past that was split, animated, and then clipped.
            var ANIMATED_MAX = 320;

            function paint(text, who, mode) {
              stage.className = 'say' + (who === 'vesper' ? ' vesper' : '') + ' ' + mode;
              stage.innerHTML = '';
              var all = graphemes(text);
              var gs = all.slice(0, ANIMATED_MAX);
              var n = gs.length;
              for (var i = 0; i < n; i++) {
                var b = document.createElement('b');
                b.textContent = gs[i];
                var a = Math.random() * Math.PI * 2;
                var d = 22 + Math.random() * 62;
                b.style.setProperty('--dx', (Math.cos(a) * d).toFixed(1) + 'px');
                b.style.setProperty('--dy', (Math.sin(a) * d - 20).toFixed(1) + 'px');
                b.style.setProperty('--rot', ((Math.random() - 0.5) * 42).toFixed(1) + 'deg');
                // Staggered from the middle outwards so the line frays rather than
                // wiping left to right, which reads as a transition effect.
                var mid = Math.abs(i - n / 2) / (n / 2 || 1);
                b.style.animationDelay = ((mode === 'out' ? (1 - mid) : mid) * 240).toFixed(0) + 'ms';
                stage.appendChild(b);
              }
              if (all.length > n) {
                var rest = document.createElement('b');
                rest.textContent = all.slice(n).join('');
                rest.style.animationDelay = '240ms';
                stage.appendChild(rest);
              }
            }

            function restagger(el, mode) {
              var kids = el.children, n = kids.length;
              for (var i = 0; i < n; i++) {
                var mid = Math.abs(i - n / 2) / (n / 2 || 1);
                kids[i].style.animationDelay =
                  ((mode === 'out' ? (1 - mid) : mid) * 240).toFixed(0) + 'ms';
              }
            }

            // ONE PENDING TRANSITION. This scheduled a timer per arrival, and a
            // typed turn publishes the owner's line and then the reply -- both
            // inside the same 860 ms dissolve. Two timers, two different lines,
            // the first painted and wiped a few milliseconds later.
            var pending = null, pendingTimer = null;

            window.__vesperStage = function (text, who) {
              if (!text || text === showing) return;
              if (pendingTimer) { pending = { text: text, who: who }; return; }
              if (!showing) { showing = text; paint(text, who, 'in'); return; }
              // DISSOLVE FIRST, THEN ARRIVE. The wait matches the scatter animation
              // plus its stagger; cutting it short would overlap two lines in the
              // one place they share, which is the whole reason this is a card and
              // not a list. Re-staggered on the way out -- `paint(.., 'out')` was
              // never called, so the dissolve replayed the ARRIVAL's stagger.
              restagger(stage, 'out');
              stage.classList.remove('in');
              stage.classList.add('out');
              pending = { text: text, who: who };
              pendingTimer = setTimeout(function () {
                pendingTimer = null;
                var q = pending; pending = null;
                if (q) { showing = q.text; paint(q.text, q.who, 'in'); }
              }, 860);
            };

            // The history bar. Collapsed it shows the OLDEST line, which is what makes
            // it a way back into the conversation rather than a duplicate of the card.
            var lastJSON = '';
            window.__vesperHistory = function (json) {
              if (json === lastJSON) return;
              lastJSON = json;
              var rows;
              try { rows = JSON.parse(json); } catch (e) { return; }
              if (!rows.length) {
                hrows.innerHTML = '<div class="hrow"><span class="hwho">—</span>'
                                + '<span class="htext" style="opacity:.4">'
                                + 'nothing said yet</span></div>';
                return;
              }
              var html = '';
              for (var i = 0; i < rows.length; i++) {
                var r = rows[i];
                var cue = (i === 0 && rows.length > 1)
                  ? '<span class="hcue">' + (rows.length - 1) + ' more</span>' : '';
                html += '<div class="hrow"><span class="hwho">'
                     + (r.who === 'vesper' ? 'vesper' : 'you') + '</span>'
                     + '<span class="htext"></span>' + cue + '</div>';
              }
              hrows.innerHTML = html;
              // TEXT SET AS textContent, NEVER AS MARKUP. These lines carry a model's
              // output, and the day one contains a tag is the day that stops being
              // theoretical.
              var cells = hrows.querySelectorAll('.htext');
              for (var j = 0; j < rows.length; j++) cells[j].textContent = rows[j].text;
            };

            if (hist) {
              hist.addEventListener('click', function () {
                // Focus first: VESPER is an accessory app and a click does not make it
                // active on its own, so without this the expand works and the field
                // beside it still cannot be typed into.
                try { window.webkit.messageHandlers.vesperFocus.postMessage('1'); } catch (e) {}
                hist.classList.toggle('open');
              });
            }
          })();
        </script>
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

    static var pushFailures = 0
    static var pushCount = 0
    private let bridge = SayBridge()

    /// What the page last reported about VESPER's own delivery, for the host's
    /// render tick. `(level, isDriven)` -- and `isDriven` is not redundant with
    /// a zero level: a real sentence passes through zero at every word boundary,
    /// and a face that dropped its source on each of those would stutter.
    var speech: (level: Float, isDriven: Bool) {
        (bridge.speechLevel, bridge.speechIsFromText)
    }
    private var refresh: Timer?

    /// Push the runtime's state into the live page.
    ///
    /// PUSHED FROM SWIFT RATHER THAN FETCHED BY THE PAGE. The page is loaded
    /// from a string with no base URL, so it has no origin and cannot read a
    /// file -- and giving it one so it could would hand a surface the ability
    /// to read the disk, which is a much larger thing than a transcript needs.
    ///
    /// RE-RENDERS ONLY WHAT CHANGED. Reloading the page each tick would clear
    /// the field the owner is typing into, which is the one thing the loop must
    /// not do. So it writes the transcript's innerHTML and the body's face
    /// attribute and touches nothing else.
    ///
    /// 700 ms, not faster. This is a status surface, not an animation -- the
    /// FACE animates continuously in Metal below, driven by its own driver at
    /// frame rate, and this only tells it which behaviour to hold. SPIKE-013's
    /// cost table is why: the composite already costs +0.053% of one core, and
    /// a JS evaluation four times a second buys nothing a person can perceive.
    /// Ask the page what it painted. Not what it was told to paint.
    static func reportStage(_ w: WKWebView) {
        let js = """
        (function(){
          function d(sel){
            var e = document.querySelector(sel);
            if (!e) return sel + ': ABSENT';
            var r = e.getBoundingClientRect();
            var s = getComputedStyle(e);
            return sel + ': "' + (e.textContent||'').trim().slice(0,42) + '"'
                 + ' box=' + Math.round(r.x) + ',' + Math.round(r.y)
                 + ' ' + Math.round(r.width) + 'x' + Math.round(r.height)
                 + ' opacity=' + s.opacity + ' display=' + s.display
                 + ' vis=' + s.visibility;
          }
          return [d('#stage'), d('.field'), d('#say'),
                  'viewport=' + window.innerWidth + 'x' + window.innerHeight,
                  'face=' + document.body.getAttribute('data-face')].join(' | ');
        })();
        """
        w.evaluateJavaScript(js) { val, err in
            if let err { print("chrome: stage READBACK failed: \(err)") }
            else { print("chrome: READBACK \(val ?? "nil")") }
        }
    }

    func startRefresh() {
        refresh?.invalidate()
        // 0.25 s, DOWN FROM 0.7 s. Together with the runtime's own poll this
        // was up to 1.2 s of transport around a model call that now returns in
        // well under a second -- the plumbing was the slower half of the
        // conversation, and it was the half nobody had measured because the
        // provider was always blamed first. Each tick reads one small JSON file
        // and evaluates a string; the composite cost recorded in §0.5 is
        // +0.053% of one core, and this multiplies that term by 2.8, not the
        // window's whole cost.
        let timer = Timer(timeInterval: 0.25, repeats: true) { [weak self] _ in
            guard let self, let w = self.web else { return }
            let face = Self.faceBehaviour()
            let (line, who) = Self.stageLine()
            let histSafe = Self.historyJSON()
                .replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "`", with: "\\`")
                .replacingOccurrences(of: "$", with: "\\$")
            let safe = line
                .replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "`", with: "\\`")
                .replacingOccurrences(of: "$", with: "\\$")
            let js = """
            (function(){
              document.body.setAttribute('data-face', '\(face)');
              if (window.__vesperStage) window.__vesperStage(`\(safe)`, '\(who)');
              if (window.__vesperHistory) window.__vesperHistory(`\(histSafe)`);
            })();
            """
            // REPORT WHAT THE PUSH DID. `completionHandler: nil` swallowed
            // every JavaScript error: a throw inside the injected snippet --
            // an undefined function, a bad template literal -- left the page
            // unchanged and said nothing, which is indistinguishable from a
            // timer that never fired. The whole pipeline can be working and
            // the surface still show nothing, which is exactly what happened.
            w.evaluateJavaScript(js) { _, err in
                if let err {
                    Self.pushFailures += 1
                    if Self.pushFailures <= 3 {
                        print("chrome: stage push FAILED: \(err)")
                    }
                } else {
                    // PERIODIC, NOT ONCE. A single readback at mount goes stale
                    // the moment anything changes, and it then describes a
                    // layout that no longer exists -- which is worse than no
                    // readback, because it reads like current evidence. Every
                    // 40th push is roughly every 28 s.
                    Self.pushCount += 1
                    if Self.pushCount == 1 || Self.pushCount % 40 == 0 {
                        print("chrome: stage push OK (#\(Self.pushCount))")
                    // READ THE WORLD AFTER ACTING. "push OK" only means the
                    // snippet did not throw; it says nothing about whether a
                    // glyph is on screen. A stage that is empty, transparent,
                    // zero-height or positioned off the display would report
                    // exactly the same success. So the PAGE is asked what it
                    // actually rendered -- text, box and opacity -- which is
                    // the closest thing to looking at it available without a
                    // screen-recording grant.
                        Self.reportStage(w)
                    }
                }
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        refresh = timer
    }

    func stopRefresh() { refresh?.invalidate(); refresh = nil }

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

            // The page's only way to reach anything. Registered on the
            // configuration BEFORE the view exists, because a handler added
            // afterwards is not visible to a page that has already loaded.
            let cfg = WKWebViewConfiguration()
            cfg.userContentController.add(self.bridge, name: SayBridge.name)
            cfg.userContentController.add(self.bridge, name: SayBridge.focusName)
            cfg.userContentController.add(self.bridge, name: SayBridge.speakingName)
            let w = WKWebView(frame: host.bounds, configuration: cfg)
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
            // THE RIGHT-HAND CLUSTER IS ANCHORED THE SAME WAY THE LEFT ONE IS,
            // and it was not. The HOST card has always been placed from
            // `faceRect.minX`, so it clears the face at any window size; the
            // conversation card was positioned in pure CSS as `right: 26px`
            // with a `min(38vw, 520px)` width, which knows nothing about where
            // the face is and overlapped it on this display. A viewport-derived
            // width cannot avoid an element it cannot see -- the two are only
            // ever coincidentally clear of each other.
            //
            // 40 px of gap, then the card takes whatever is left, capped in CSS
            // so it does not sprawl on a wide screen.
            let convoLeft = Int(faceRect.maxX) + 40
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
                                       left: left, top: t, convoLeft: convoLeft,
                                       fill: self.cardFill),
                             baseURL: nil)
            self.startRefresh()
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
