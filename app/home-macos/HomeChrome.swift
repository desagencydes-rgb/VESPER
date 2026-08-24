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
    static func page(cardWidth: Int, cardHeight: Int, left: Int, top: Int) -> String {
        """
        <!doctype html><meta charset="utf-8">
        <style>
          html,body{margin:0;height:100%;background:transparent;overflow:hidden;
                    font-family:-apple-system,system-ui,sans-serif;
                    -webkit-font-smoothing:antialiased}
          .card{position:absolute;left:\(left)px;top:\(top)px;
                width:\(cardWidth)px;height:\(cardHeight)px;box-sizing:border-box;
                padding:22px 24px;border-radius:22px;
                background:rgba(255,255,255,.055);
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
        </style>
        <div class="card">
          <div class="t">host</div>
          <div class="row"><span class="k">thinking</span><span class="v">UNAVAILABLE</span></div>
          <div class="row"><span class="k">context</span><span class="v">UNAVAILABLE</span></div>
          <div class="row"><span class="k">cache</span><span class="v">UNAVAILABLE</span></div>
          <div class="row"><span class="k">tokens</span><span class="v">UNAVAILABLE</span></div>
          <div class="row"><span class="k">power</span><span class="v">UNAVAILABLE</span></div>
        </div>
        """
    }

    /// Mount the chrome over `host`, but only if the glass is actually clear.
    ///
    /// `onVerdict` is called with the guard's answer either way, so a refusal is
    /// reported rather than being a chrome that quietly never appeared.
    func mount(over host: NSView, faceRect: CGRect,
               onVerdict: @escaping (GlassGuard.Verdict) -> Void) {
        GlassGuard.verify { [weak self] verdict in
            onVerdict(verdict)
            guard let self, verdict.mayMountChrome else { return }

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
            w.loadHTMLString(Self.page(cardWidth: cw, cardHeight: ch,
                                       left: left, top: t), baseURL: nil)
        }
    }

    func unmount() {
        web?.removeFromSuperview()
        web = nil
        mounted = false
    }
}
