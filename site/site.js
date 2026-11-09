// A tile remains a link to its wallpaper if scripts are unavailable.
(() => {
  const tiles = Array.from(document.querySelectorAll("[data-mode]"));
  const root = document.documentElement;
  const modeKey = "vesper-ambience";
  function apply(mode, remember) {
    root.style.setProperty("--accent", mode.accent);
    root.style.setProperty("--ground", mode.ground);
    root.style.setProperty("--wall", "url(assets/modes/" + mode.mode + ".webp)");
    for (const tile of tiles) {
      if (tile.dataset.mode === mode.mode) tile.setAttribute("aria-current", "true");
      else tile.removeAttribute("aria-current");
    }
    if (tiles.length) {
      document.querySelector("#mode-label").textContent = mode.mode;
      document.querySelector("#mode-note").textContent = mode.note;
    }
    if (remember) {
      try {
        sessionStorage.setItem(modeKey, JSON.stringify(mode));
      } catch {
        /* Storage is optional. */
      }
    }
    window.dispatchEvent(new CustomEvent("ambience", { detail: mode.accent }));
  }
  for (const tile of tiles) {
    tile.addEventListener("click", (event) => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      apply(tile.dataset, true);
    });
  }
  try {
    const saved = JSON.parse(sessionStorage.getItem(modeKey));
    if (
      saved &&
      /^[a-z]+$/.test(saved.mode) &&
      /^#[a-f0-9]{6}$/i.test(saved.accent) &&
      /^#[a-f0-9]{6}$/i.test(saved.ground)
    )
      apply(saved, false);
  } catch {
    /* The default mode is fully present in HTML. */
  }
})();
