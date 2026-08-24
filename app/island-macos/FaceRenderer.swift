// The face — a real 3D point cloud, on the GPU.
//
// WHY METAL AND NOT CoreGraphics. This runs continuously while VESPER works, on a
// laptop whose stated goal is to stretch its own host's lifetime. 33,670 points
// stroked per frame through CoreGraphics is tens of milliseconds of CPU every
// frame, burning a core to draw a face. On the GPU it is one draw call over a
// buffer that never changes, and the CPU writes 128 bytes of uniforms.
//
// THE CLOUD IS THE REFERENCE. Points come from `docs/design/source/face_cloud.py`,
// which samples the owner's own reference for (x, y) and intensity, so head-on
// this IS the reference. z comes from a head-shaped depth field so it can turn.
//
// COLOUR IS NOT BAKED. §8: "the colour is whatever the adaptive rule picked for
// the space, and the hologram panels take the same colour." The cloud carries
// intensity only; the tint is a uniform.

import Foundation
import Metal
import QuartzCore
import simd

struct FaceUniforms {
    var yaw: Float = 0, pitch: Float = 0
    var eyeYaw: Float = 0, eyePitch: Float = 0
    var scale: Float = 1, pointSize: Float = 1.6
    var blink: Float = 0            // 0 open, 1 shut
    var alpha: Float = 1
    // THREE PLAIN FLOATS, NOT SIMD3. SIMD3<Float> is 16-byte aligned in Swift but
    // packed_float3 is 12 in MSL, so Metal read `aspect` out of Swift's padding,
    // got 0, and every point went to infinity on the x divide. The face rendered
    // nothing and the layer looked exactly like an empty panel -- a layout bug
    // that presents as "the feature is not wired up".
    // MEASURED off the owner's reference, not chosen. Sampling the head region by
    // brightness band gives normalised (1.00, 0.46, 0.29) dim, (1.00, 0.55, 0.39)
    // mid, (1.00, 0.70, 0.56) hot -- it is a TEMPERATURE RAMP, not a colour. This
    // is the ember end; the shader washes it toward white as a point gets hot,
    // which is what makes it read as light instead of as paint.
    var tintR: Float = 1.00, tintG: Float = 0.46, tintB: Float = 0.29
    var aspect: Float = 1
    /// §8's fourth tier. 0 is the head; 1 is the attractor fully released and
    /// the cloud settled into the ambience field the widgets sit in. APPENDED
    /// at the end of the struct, and appended in the same order in the MSL one:
    /// this layout has already cost a bug where `aspect` was read out of Swift's
    /// padding, got 0, and sent every point to infinity.
    var disperse: Float = 0
    /// Seconds. Only the dispersed field uses it -- §8 says the points "drift to
    /// a low-energy field and stay there, ALIVE", and a field that is merely
    /// stopped is not that.
    var time: Float = 0
}

extension FaceUniforms {
    /// The width the 1.6 px default was tuned at: the island's own face layer,
    /// `min(230, width * 0.38)`.
    static let tunedAtPoints: CGFloat = 230

    /// A cloud is a FIXED number of points. Spread over a layer three times
    /// wider without growing the points, a bust becomes dust -- measured on the
    /// home's 693 pt face on 2026-08-23: 3.46% of the rect painted at mean
    /// alpha 0.003. It rendered 367 frames and the owner saw an empty ground,
    /// which is exactly why `framesDrawn` counts attempts and cannot be the
    /// instrument.
    ///
    /// So point size is DERIVED from the layer rather than carried as a
    /// constant that happens to suit one host. Two hosts, one density.
    static func pointSize(forLayerWidth w: CGFloat) -> Float {
        Float(1.6 * max(1, w / tunedAtPoints))
    }
}

private let SHADER = """
#include <metal_stdlib>
using namespace metal;

struct Uniforms {
    float yaw, pitch, eyeYaw, eyePitch, scale, pointSize, blink, alpha;
    float tintR, tintG, tintB, aspect;
    float disperse, time;
};

struct VOut { float4 pos [[position]]; float psize [[point_size]]; half4 colour; };

// The irises, MEASURED off the reference rather than placed by eye.
//
// The first measurement was wrong and looked convincing: thresholding near-white
// pixels across the whole eye BAND caught the bright mesh on the ears and temples,
// putting the irises at +/-0.44 -- nearly double. The glow rendered on the temples
// and the face looked possessed. Constraining to the central 62% and taking the
// radius that contains 85% of the cluster rather than its maximum gives
// (-0.252, +0.062) and (+0.224, +0.062), stable across three thresholds.
//
// The cloud carries no eye grouping and does not need one -- the shader already
// has every point's model position, so it can tell an eye point from a head point
// without a second attribute or a wider vertex format.
constant float2 EYE_L = float2(-0.252, 0.062);
constant float2 EYE_R = float2( 0.224, 0.062);
constant float  IRIS  = 0.030;      // hot core; measured r85 = 0.028
constant float  LID   = 0.072;      // what the lid closes over

vertex VOut vmain(uint vid [[vertex_id]],
                  const device float4 *pts [[buffer(0)]],
                  constant Uniforms &u [[buffer(1)]]) {
    float4 p = pts[vid];
    float3 v = float3(p.xyz);

    float2 eye = (v.x < 0.0) ? EYE_L : EYE_R;
    float dEye = distance(v.xy, eye);
    float iris = 1.0 - smoothstep(IRIS, LID, dEye);          // 1 at the pupil, 0 past the lid

    // The eyes move BEYOND the head, and they carry the head's own rotation with
    // them -- so this is a small displacement in model space applied before the
    // head turns, not a second rotation fought against the first.
    v.xy += float2(u.eyeYaw, u.eyePitch) * 0.22 * iris;

    // Blink: the lid closes over the eye, so eye points collapse toward the eye's
    // own centre line rather than the head's. 120 ms, driven from the CPU.
    v.y = mix(v.y, eye.y, u.blink * iris);

    // Yaw about Y, then pitch about X. Order matters: pitch-then-yaw tilts the
    // head off its own axis and reads as a lolling head rather than a look.
    float cy = cos(u.yaw), sy = sin(u.yaw);
    v = float3(v.x * cy + v.z * sy, v.y, -v.x * sy + v.z * cy);
    float cp = cos(u.pitch), sp = sin(u.pitch);
    v = float3(v.x, v.y * cp - v.z * sp, v.y * sp + v.z * cp);

    // §8 DISPERSAL. "The point cloud with the head's attractor released. The
    // points become the ambience field the widgets sit in."
    //
    // A RELEASE, NOT A FADE, and not a second asset: the same 39,805 points,
    // each drifting to its own resting place in a wider, flatter volume. The
    // target is derived from the vertex id, so it is stable frame to frame --
    // a target re-randomised per frame would be static, not a field.
    //
    // Applied AFTER the rotation. Dispersed, there is no head to turn, and a
    // field that yaws with a head nobody can see reads as a bug.
    if (u.disperse > 0.0) {
        float f = float(vid);
        float h1 = fract(sin(f * 12.9898) * 43758.5453);
        float h2 = fract(sin(f * 78.2330) * 43758.5453);
        float h3 = fract(sin(f * 39.4250) * 43758.5453);
        float3 rest = float3((h1 - 0.5) * 2.70, (h2 - 0.5) * 1.75, (h3 - 0.5) * 0.55);
        // Alive rather than merely stopped. Slow, per-point phase, small
        // amplitude: at this scale it is drift, not motion.
        rest += 0.045 * float3(sin(u.time * 0.21 + h1 * 6.2832),
                               cos(u.time * 0.17 + h2 * 6.2832),
                               sin(u.time * 0.13 + h3 * 6.2832));
        v = mix(v, rest, u.disperse);
    }

    // Weak perspective. A full projection at this scale buys nothing visible and
    // costs a matrix upload per frame.
    float persp = 1.0 / (1.0 + 0.22 * (1.0 - v.z));

    VOut o;
    o.pos = float4(v.x * persp * u.scale / u.aspect, v.y * persp * u.scale, 0.0, 1.0);

    // Points behind the head are dimmer, which is what gives a point cloud its
    // volume. Without it the far side reads as noise sitting on top of the near.
    float depthFade = clamp(0.18 + 0.82 * (v.z * 0.5 + 0.5), 0.0, 1.0);
    // ADDITIVE BLENDING SATURATES: where the cloud is dense, overlapping points
    // sum past 1.0 and the face drifts toward cream -- an early build read as
    // sandstone rather than ember. Gain 1.15 with a late wash keeps the colour
    // concentrated, so only genuine highlights climb the ramp.
    //
    // CHOSEN, NOT SETTLED FOR. Owner, 2026-08-21, shown both: "that concentrated
    // ember is even better". A brighter 1.95 was legible and read warmer; this is
    // darker and holds the hue. Do not "fix" the darkness -- it is the decision.
    float i = clamp(p.w * 1.15, 0.0, 1.0) * depthFade;

    // The hot end desaturates toward white. The base hue stays a uniform so §8's
    // adaptive rule still owns the colour -- only the RAMP is baked, because the
    // ramp is physics rather than palette.
    float3 base = float3(u.tintR, u.tintG, u.tintB);
    float3 warm = mix(base, mix(base, float3(1.0), 0.38), smoothstep(0.62, 1.0, i));

    // The irises are the focal point of the reference -- hot, near-white, and the
    // one place the ramp is allowed to run all the way out. Everything else stays
    // ember; if the whole face could reach white it would read as sandstone again.
    // Dispersed, the irises go with the head -- there are no eyes in an
    // ambience field, and a pair of hot points floating in one reads as the
    // face failing to dissolve rather than as a field.
    float lit = iris * (1.0 - u.disperse);
    warm = mix(warm, float3(1.0, 0.94, 0.86), lit * 0.85);
    i = clamp(i + lit * 0.55, 0.0, 1.6);
    // A field is quieter than a face. This is what makes DISPERSED plausibly
    // cheaper than CENTRE on the axes that are not point count -- and §8
    // pre-registered that it must be, so it is measured, not assumed.
    i *= mix(1.0, 0.62, u.disperse);

    o.psize = max(1.0, u.pointSize * persp);
    o.colour = half4(half3(warm * i), half(i * u.alpha));
    return o;
}

fragment half4 fmain(VOut in [[stage_in]], float2 pc [[point_coord]]) {
    // Round, soft-edged points. Square points read as pixels, not as light.
    float d = length(pc - float2(0.5));
    if (d > 0.5) discard_fragment();
    half fall = half(smoothstep(0.5, 0.12, d));
    return half4(in.colour.rgb * fall, in.colour.a * fall);
}
"""

final class FaceRenderer {
    let device: MTLDevice
    private let queue: MTLCommandQueue
    private let pipeline: MTLRenderPipelineState
    private let points: MTLBuffer
    let count: Int
    var uniforms = FaceUniforms()

    init?(cloudPath: String) {
        guard let dev = MTLCreateSystemDefaultDevice(),
              let q = dev.makeCommandQueue(),
              let data = FileManager.default.contents(atPath: cloudPath),
              data.count > 4 else { return nil }

        let n = data.withUnsafeBytes { $0.load(as: UInt32.self) }
        let bytes = Int(n) * 16
        guard data.count >= 4 + bytes else { return nil }
        guard let buf = data.withUnsafeBytes({ raw -> MTLBuffer? in
            dev.makeBuffer(bytes: raw.baseAddress!.advanced(by: 4), length: bytes,
                           options: .storageModeShared)
        }) else { return nil }

        do {
            let lib = try dev.makeLibrary(source: SHADER, options: nil)
            let d = MTLRenderPipelineDescriptor()
            d.vertexFunction = lib.makeFunction(name: "vmain")
            d.fragmentFunction = lib.makeFunction(name: "fmain")
            d.colorAttachments[0].pixelFormat = .bgra8Unorm
            // Additive: overlapping points accumulate into brightness the way a
            // real point cloud does. Alpha blending would make the dense areas
            // flat instead of hot.
            d.colorAttachments[0].isBlendingEnabled = true
            d.colorAttachments[0].rgbBlendOperation = .add
            d.colorAttachments[0].sourceRGBBlendFactor = .sourceAlpha
            d.colorAttachments[0].destinationRGBBlendFactor = .one
            d.colorAttachments[0].sourceAlphaBlendFactor = .sourceAlpha
            d.colorAttachments[0].destinationAlphaBlendFactor = .one
            pipeline = try dev.makeRenderPipelineState(descriptor: d)
        } catch { return nil }

        device = dev; queue = q; points = buf; count = Int(n)
        FileHandle.standardError.write("face: \(n) points loaded\n".data(using: .utf8)!)
    }

    /// Alpha the pass clears to. **1 for the island, 0 for the home**, and the
    /// difference is not a preference — it is what is underneath.
    ///
    /// The island paints its own opaque black shell, so clearing to opaque black
    /// makes the face sit ON that ground rather than inside a black rectangle of
    /// its own. The home has no such ground: since 2026-08-23 the mode picture is
    /// the real desktop picture, and there is nothing of VESPER's between the
    /// face and it. Clearing to alpha 1 there paints exactly the black square the
    /// owner reported — a correct decision for one surface applied to another
    /// where its premise does not hold.
    ///
    /// Default stays 1 so the island is untouched.
    public var clearAlpha: Double = 1

    func draw(in layer: CAMetalLayer) {
        guard let drawable = layer.nextDrawable() else { return }
        encode(to: drawable.texture, present: drawable)
    }

    /// Same pass, into a texture nobody presents — so the result can be read
    /// back and checked. Without this, "the background is transparent now" is a
    /// claim about a line of code rather than a reading of a pixel.
    func render(to texture: MTLTexture) { encode(to: texture, present: nil) }

    private func encode(to texture: MTLTexture, present drawable: CAMetalDrawable?) {
        guard let cmd = queue.makeCommandBuffer() else { return }
        let rp = MTLRenderPassDescriptor()
        rp.colorAttachments[0].texture = texture
        rp.colorAttachments[0].loadAction = .clear
        // Black, not #03141f. The presence reference puts its content straight on
        // the shell -- the inner ground panel belongs to Hanging. Measured: the
        // instruments reference carries 16,129 px of #03141f, the presence one
        // carries none.
        rp.colorAttachments[0].clearColor =
            MTLClearColor(red: 0, green: 0, blue: 0, alpha: clearAlpha)
        rp.colorAttachments[0].storeAction = .store
        guard let enc = cmd.makeRenderCommandEncoder(descriptor: rp) else { return }
        var u = uniforms
        u.aspect = Float(texture.width) / Float(max(1, texture.height))
        enc.setRenderPipelineState(pipeline)
        enc.setVertexBuffer(points, offset: 0, index: 0)
        enc.setVertexBytes(&u, length: MemoryLayout<FaceUniforms>.stride, index: 1)
        enc.drawPrimitives(type: .point, vertexStart: 0, vertexCount: count)
        enc.endEncoding()
        if let drawable { cmd.present(drawable) }
        cmd.commit()
        if drawable == nil { cmd.waitUntilCompleted() }
    }
}
