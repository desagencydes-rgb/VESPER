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
}

private let SHADER = """
#include <metal_stdlib>
using namespace metal;

struct Uniforms {
    float yaw, pitch, eyeYaw, eyePitch, scale, pointSize, blink, alpha;
    float tintR, tintG, tintB, aspect;
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
    warm = mix(warm, float3(1.0, 0.94, 0.86), iris * 0.85);
    i = clamp(i + iris * 0.55, 0.0, 1.6);

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

    func draw(in layer: CAMetalLayer) {
        guard let drawable = layer.nextDrawable(),
              let cmd = queue.makeCommandBuffer() else { return }
        let rp = MTLRenderPassDescriptor()
        rp.colorAttachments[0].texture = drawable.texture
        rp.colorAttachments[0].loadAction = .clear
        // Clears to the ground the island already paints, so the face sits ON our
        // black rather than in a black rectangle of its own.
        // Black, not #03141f. The presence reference puts its content straight on
        // the shell -- the inner ground panel belongs to Hanging. Measured: the
        // instruments reference carries 16,129 px of #03141f, the presence one
        // carries none.
        rp.colorAttachments[0].clearColor = MTLClearColor(red: 0, green: 0, blue: 0, alpha: 1)
        rp.colorAttachments[0].storeAction = .store
        guard let enc = cmd.makeRenderCommandEncoder(descriptor: rp) else { return }
        var u = uniforms
        u.aspect = Float(layer.drawableSize.width / max(1, layer.drawableSize.height))
        enc.setRenderPipelineState(pipeline)
        enc.setVertexBuffer(points, offset: 0, index: 0)
        enc.setVertexBytes(&u, length: MemoryLayout<FaceUniforms>.stride, index: 1)
        enc.drawPrimitives(type: .point, vertexStart: 0, vertexCount: count)
        enc.endEncoding()
        cmd.present(drawable)
        cmd.commit()
    }
}
