// VESPER's home — the surface system. Cards, widgets, fields and popups.
//
// WHY THIS EXISTS RATHER THAN MORE `page()` STRING. The chrome's first card was
// positioned with literal `left` and `top`, which was right for one card and is
// wrong for ninety. HANDOFF_HOME_STEP1 names the cost directly:
//
//     "The composition question should be settled first: moving 90 cards later
//      costs more than moving one now."
//
// The unsettled question is §14.1's: the face is a floating head today and the
// specification says a BUST -- head, neck and shoulders, middle fifth of the
// width, from under the menu bar to two-thirds down. That change moves where
// every card goes.
//
// SO THE ANSWER IS NOT TO SETTLE IT FIRST. It is to stop cards carrying
// coordinates at all. A surface declares a REGION -- `leftCluster`,
// `aboveFace`, `overlay` -- and the layout solves pixels from the face's actual
// rect at mount time. When the face becomes a bust, every surface moves with it
// and nothing is repositioned by hand. The owner's decision then costs one
// measurement instead of ninety edits.
//
// EVERY REGION IS DEFINED AGAINST `faceRect`, NEVER AGAINST THE SCREEN, with
// one deliberate exception: `dock` and `notification` are screen-anchored,
// because §10 puts the main menu at the Dock's own position and a notification
// is addressed to the owner rather than composed around the face.
//
// NOTHING HERE INVENTS A READING. `INV-HW-2` and the projection's rule: a
// surface renders its reading or it renders nothing. A field with no producer
// says UNAVAILABLE in the place the value will go, and it says it once -- an
// empty card reads as broken and a card of five UNAVAILABLEs reads as five
// failures, and neither is true.

import AppKit
import CoreGraphics

// MARK: - Regions

/// Where a surface sits, expressed against the composition rather than the screen.
///
/// ORDERED BY THE RING §14.1 DESCRIBES, so a reader can see the composition in
/// the case list. `overlay` and `notification` are not part of the ring: one is
/// modal over everything, the other is addressed to the owner and may appear
/// when the home is not even visible.
enum HomeRegion: String, CaseIterable {
    case leftCluster        // the ring's left arc — the metrics card lives here
    case rightCluster       // the ring's right arc
    case aboveFace          // between the menu bar and the face's crown
    case belowFace          // between the face's base and the dock row
    case dock               // screen-anchored: §10 takes the Dock's position
    case overlay            // modal, centred on the face's column
    case notification       // screen-anchored, top-right

    /// Anchored to the face, or to the display?
    ///
    /// The distinction is not cosmetic. A face-anchored surface MOVES when the
    /// composition changes and a screen-anchored one does not, so getting this
    /// wrong is exactly the defect this file exists to prevent -- it would
    /// reintroduce hardcoded placement wearing a region's name.
    var followsFace: Bool {
        switch self {
        case .dock, .notification: return false
        default: return true
        }
    }
}

// MARK: - Surfaces

enum SurfaceKind: String {
    case card           // Sheet tier: blur 24, fill solved, radius 22
    case widget         // a small card; same tier, tighter padding
    case field          // an input row
    case popup          // Sheet tier, elevated, dismissible
    case notification   // addressed to the owner, may outlive the home
}

/// One thing on the home. Content is HTML fragments, already escaped.
struct HomeSurface {
    let id: String
    let kind: SurfaceKind
    let region: HomeRegion
    let title: String
    let body: String
    /// Intrinsic size in points. The layout may place it but never resizes it:
    /// a card whose height depends on where it landed cannot be measured
    /// against its own contrast requirement.
    let width: Int
    let height: Int
    /// Lower sorts nearer the face within a region.
    let order: Int

    init(id: String, kind: SurfaceKind, region: HomeRegion, title: String,
         body: String, width: Int = 300, height: Int = 190, order: Int = 0) {
        self.id = id; self.kind = kind; self.region = region
        self.title = title; self.body = body
        self.width = width; self.height = height; self.order = order
    }
}

/// A surface with its solved position.
struct PlacedSurface {
    let surface: HomeSurface
    let rect: CGRect
    /// Why it landed there, in words. A layout nobody can explain is one that
    /// quietly gets worse -- the same argument `core/router.py` makes for
    /// naming its deciding factors.
    let because: String
}

// MARK: - Layout

enum HomeLayout {

    /// Clear of the face by this much, at minimum. §14.1's ring is a ring: a
    /// card that touches the face is not in the ring, it is on it.
    static let ringGap: CGFloat = 34
    /// Between stacked surfaces in the same region.
    static let stackGap: CGFloat = 18
    /// Kept clear at the bottom for the dock row.
    static let dockBand: CGFloat = 96
    /// Kept clear at the top for the menu bar.
    static let menuBand: CGFloat = 28

    /// Solve every surface's rect from the face's ACTUAL rect.
    ///
    /// `faceRect` and `bounds` are both in the chrome's own coordinate space
    /// (origin top-left, points), which is the space the generated CSS uses.
    /// Converting here rather than in the caller keeps one conversion in one
    /// place -- HANDOFF_HOME_STEP1 records an `NSScreen` whose cached geometry
    /// reported the world as it was, and two coordinate conversions is the same
    /// shape of bug.
    static func solve(_ surfaces: [HomeSurface],
                      faceRect: CGRect, bounds: CGRect) -> [PlacedSurface] {
        var out: [PlacedSurface] = []
        for region in HomeRegion.allCases {
            let members = surfaces.filter { $0.region == region }
                                  .sorted { $0.order < $1.order }
            guard !members.isEmpty else { continue }
            out.append(contentsOf: place(members, in: region,
                                         faceRect: faceRect, bounds: bounds))
        }
        return out
    }

    private static func place(_ members: [HomeSurface], in region: HomeRegion,
                              faceRect: CGRect, bounds: CGRect) -> [PlacedSurface] {
        var placed: [PlacedSurface] = []
        // Stack downward from the face's vertical centre, so a region with one
        // surface centres on the face and a region with three stays balanced
        // around it. Centring on the SCREEN instead would drift away from the
        // composition the moment the face is not centred, which is precisely
        // what §14.1's bust does.
        let totalH = members.reduce(0) { $0 + CGFloat($1.height) }
            + stackGap * CGFloat(max(0, members.count - 1))
        var y = faceRect.midY - totalH / 2

        for m in members {
            let w = CGFloat(m.width), h = CGFloat(m.height)
            var x: CGFloat
            var why: String

            switch region {
            case .leftCluster:
                x = faceRect.minX - ringGap - w
                why = "left of the face by the ring gap (\(Int(ringGap)) pt)"
            case .rightCluster:
                x = faceRect.maxX + ringGap
                why = "right of the face by the ring gap (\(Int(ringGap)) pt)"
            case .aboveFace:
                x = faceRect.midX - w / 2
                y = max(menuBand, faceRect.minY - ringGap - h)
                why = "centred on the face's column, above its crown"
            case .belowFace:
                x = faceRect.midX - w / 2
                y = faceRect.maxY + ringGap
                why = "centred on the face's column, below its base"
            case .overlay:
                x = faceRect.midX - w / 2
                y = bounds.midY - h / 2
                why = "modal, centred on the face's column"
            case .dock:
                x = bounds.midX - w / 2
                y = bounds.maxY - dockBand
                why = "screen-anchored at the Dock's own position (SS10)"
            case .notification:
                x = bounds.maxX - w - 24
                y = menuBand + 12 + CGFloat(placed.count) * (h + stackGap)
                why = "screen-anchored top-right; addressed to the owner"
            }

            // CLAMPED INTO THE DISPLAY, AND THE CLAMP IS REPORTED. A surface
            // pushed off-screen by a face near an edge would simply not be
            // seen, and "mounted" would still be true -- the chrome's own
            // header already warns that mounting is not painting.
            var clamped = false
            if x < 12 { x = 12; clamped = true }
            if x + w > bounds.maxX - 12 { x = bounds.maxX - 12 - w; clamped = true }
            if y < menuBand { y = menuBand; clamped = true }
            if y + h > bounds.maxY - 12 { y = bounds.maxY - 12 - h; clamped = true }
            if clamped { why += "; CLAMPED into the display" }

            placed.append(PlacedSurface(surface: m,
                                        rect: CGRect(x: x, y: y, width: w, height: h),
                                        because: why))
            if region.followsFace && region != .aboveFace {
                y += h + stackGap
            }
        }
        return placed
    }

    /// A one-line account of every placement, for `--surface-check`.
    ///
    /// The chrome can already say WHERE a card landed; this says WHY. A layout
    /// that cannot explain itself is one nobody can argue with.
    static func explain(_ placed: [PlacedSurface]) -> String {
        placed.map { p in
            let r = p.rect
            return "\(p.surface.id)  \(p.surface.region.rawValue)  "
                 + "x=\(Int(r.minX)) y=\(Int(r.minY)) "
                 + "\(Int(r.width))x\(Int(r.height))  -- \(p.because)"
        }.joined(separator: "\n")
    }
}
