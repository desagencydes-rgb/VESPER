// A software projection keeps the portrait available on devices without WebGL.
// The export stores x/y/z as little-endian int16 at scale 28,000 plus one intensity byte.
(() => {
  const chamber = document.querySelector(".chamber");
  const hero = chamber.closest(".hero");
  const canvas = chamber.querySelector("canvas");
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  const context = canvas.getContext("2d");
  if (!context) return;
  let points,
    loading,
    frame = 0,
    visible = true,
    started = 0;
  let yaw = 0,
    pitch = 0,
    aimX = 0,
    aimY = 0,
    spread = 0,
    targetSpread = 0;
  let pixels, light, size, tint;

  function color() {
    const hex = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
    const rgb = parseInt(hex.slice(1), 16);
    tint = [rgb >> 16, (rgb >> 8) & 255, rgb & 255].map((c, i) =>
      Math.round(c * 0.69 + [255, 229, 204][i] * 0.31),
    );
    wake();
  }
  async function load() {
    if (motion.matches || !visible) return;
    if (!loading) {
      loading = fetch("assets/portrait.bin")
        .then((response) => {
          if (!response.ok) throw new Error("Portrait unavailable");
          return response.arrayBuffer();
        })
        .then((buffer) => {
          const bytes = new DataView(buffer);
          const count = bytes.byteLength / 7;
          if (count !== 39805) throw new Error("Incomplete portrait");
          points = new Float32Array(count * 8);
          let seed = 11;
          const random = () => (seed = (Math.imul(1664525, seed) + 1013904223) >>> 0) / 4294967296;
          for (let n = 0; n < count; n++) {
            const offset = n * 7,
              i = n * 8;
            const x = bytes.getInt16(offset, true) / 28000;
            const y = bytes.getInt16(offset + 2, true) / 28000;
            points.set(
              [
                x,
                y,
                bytes.getInt16(offset + 4, true) / 28000,
                bytes.getUint8(offset + 6) / 255,
                (random() - 0.5) * 2.3,
                (random() - 0.5) * 2,
                random() - 0.5,
                Math.abs(x) < 0.32 && y > -0.12 && y < 0.17 ? 1 : 0,
              ],
              i,
            );
          }
        })
        .catch(() => {
          loading = null;
        });
    }
    await loading;
    if (points && !motion.matches) {
      started = performance.now();
      wake();
    }
  }
  function wake() {
    if (points && !frame && visible && !motion.matches) frame = requestAnimationFrame(draw);
  }
  function draw(now) {
    frame = 0;
    if (motion.matches || !visible) return;
    const side = Math.max(1, Math.round(chamber.clientWidth * Math.min(devicePixelRatio, 1.65)));
    if (side !== size) {
      size = canvas.width = canvas.height = side;
      pixels = context.createImageData(size, size);
      light = new Float32Array(size * size);
    }
    light.fill(0);
    yaw += (aimX - yaw) * 0.14;
    pitch += (aimY - pitch) * 0.14;
    spread += (targetSpread - spread) * 0.18;
    // One breath at arrival; pointer and scroll changes wake a settled frame.
    const breathPhase = Math.min(1, (now - started) / 2400);
    const breath = Math.sin(breathPhase * Math.PI) ** 2;
    const scale = size * (0.443 + 0.006 * breath);
    const cy = Math.cos(yaw),
      sy = Math.sin(yaw),
      cp = Math.cos(pitch),
      sp = Math.sin(pitch);
    for (let i = 0; i < points.length; i += 8) {
      const x = points[i] + spread * points[i + 4];
      const y = points[i + 1] + spread * points[i + 5];
      const z = points[i + 2] - 0.43 + spread * points[i + 6];
      const depth = z * cy - x * sy;
      const perspective = 1 / (1 - (depth * cp + y * sp) * 0.09);
      const px = size / 2 + (x * cy + z * sy + points[i + 7] * (aimX - yaw) * 0.12) * scale * perspective;
      const py = size / 2 - (y * cp - depth * sp) * scale * perspective;
      const ix = Math.floor(px),
        iy = Math.floor(py);
      if (ix < 0 || iy < 0 || ix >= size - 1 || iy >= size - 1) continue;
      const k = ix + iy * size,
        dx = px - ix,
        dy = py - iy;
      const flux = (points[i + 3] * (1.1 + 0.12 * breath) * (1 - spread * 0.25) * size) / 320;
      light[k] += flux * (1 - dx) * (1 - dy);
      light[k + 1] += flux * dx * (1 - dy);
      light[k + size] += flux * (1 - dx) * dy;
      light[k + size + 1] += flux * dx * dy;
    }
    for (let k = 0; k < light.length; k++) {
      const v = light[k],
        p = k * 4;
      pixels.data[p] = tint[0];
      pixels.data[p + 1] = tint[1] + Math.min(36, v * 12);
      pixels.data[p + 2] = tint[2] + Math.min(42, v * 12);
      pixels.data[p + 3] = Math.min(255, v * 205);
    }
    context.putImageData(pixels, 0, 0);
    canvas.hidden = false;
    chamber.classList.add("live");
    if (
      breathPhase < 1 ||
      Math.abs(aimX - yaw) + Math.abs(aimY - pitch) + Math.abs(targetSpread - spread) > 0.0008
    )
      wake();
  }
  hero.addEventListener("pointermove", (e) => {
    if (e.pointerType === "touch") return;
    const rect = chamber.getBoundingClientRect();
    const clamp = (n) => Math.max(-1, Math.min(1, n));
    aimX = clamp(((e.clientX - rect.left) / rect.width) * 2 - 1) * 0.31;
    aimY = clamp(((e.clientY - rect.top) / rect.height) * 2 - 1) * 0.21;
    wake();
  });
  hero.addEventListener("pointerleave", () => {
    aimX = aimY = 0;
    wake();
  });
  function scroll() {
    const distance = Math.max(0, -hero.getBoundingClientRect().top);
    targetSpread = Math.sin(Math.PI * Math.min(1, distance / (hero.clientHeight * 0.66)));
    wake();
  }
  window.addEventListener("scroll", scroll, { passive: true });
  window.addEventListener("resize", scroll);
  window.addEventListener("ambience", color);
  motion.addEventListener("change", () => {
    if (motion.matches) {
      cancelAnimationFrame(frame);
      frame = 0;
      canvas.hidden = true;
      chamber.classList.remove("live");
    } else load();
  });
  new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    if (visible) {
      scroll();
      load();
    }
  }).observe(chamber);
  color();
})();
