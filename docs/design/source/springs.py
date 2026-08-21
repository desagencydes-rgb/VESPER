import math

# SwiftUI Spring(duration:bounce:) -> unit step response, sampled into a CSS linear() easing.
# duration is the PERCEPTUAL duration: omega_n = 2*pi/duration.
# bounce >= 0  ->  damping ratio zeta = 1 - bounce.
def step(t, duration, bounce):
    wn = 2*math.pi/duration
    z  = 1.0 - bounce
    if abs(z-1.0) < 1e-9:                      # critically damped
        return 1 - math.exp(-wn*t)*(1 + wn*t)
    if z < 1.0:                                # underdamped
        wd = wn*math.sqrt(1-z*z)
        return 1 - math.exp(-z*wn*t)*(math.cos(wd*t) + (z*wn/wd)*math.sin(wd*t))
    a = wn*math.sqrt(z*z-1)                    # overdamped
    return 1 - math.exp(-z*wn*t)*(math.cosh(a*t) + (z*wn/a)*math.sinh(a*t))

def settle(duration, bounce, tol=0.001, tmax=6.0):
    """Wall-clock time until it stays within tol of 1 forever after."""
    t, dt, last = 0.0, 1/1000, 0.0
    while t < tmax:
        if abs(step(t, duration, bounce) - 1) > tol:
            last = t
        t += dt
    return last + dt

def linear_easing(duration, bounce, n=null_n if False else 24):
    T = settle(duration, bounce)
    pts = []
    for i in range(n+1):
        t = T*i/n
        pts.append(step(t, duration, bounce))
    pts[0], pts[-1] = 0.0, 1.0
    body = ", ".join(f"{p:.4f}" for p in pts)
    return T, f"linear({body})"

print(f"{'name':<10} {'dur':>5} {'bounce':>7} {'zeta':>5} {'settle(s)':>10}  overshoot")
rows = [("smooth", 0.5, 0.00), ("snappy", 0.5, 0.15), ("bouncy", 0.5, 0.30),
        ("legacy", 0.55, 0.175)]   # legacy .spring(): response .55, dampingFraction .825 -> bounce .175
out = {}
for name, d, b in rows:
    T, css = linear_easing(d, b)
    peak = max(step(T*i/400, d, b) for i in range(401))
    print(f"{name:<10} {d:>5} {b:>7} {1-b:>5.3f} {T:>10.3f}  {(peak-1)*100:>5.1f}%")
    out[name] = (T, css)
print()
for name,(T,css) in out.items():
    print(f"/* {name}: settles in {T*1000:.0f}ms */")
    print(f"--motion-{name}: {css};")
    print(f"--motion-{name}-dur: {T*1000:.0f}ms;")
    print()
