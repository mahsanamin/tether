// Matrix digital rain on a full-screen canvas behind the UI. Pure decoration:
// it draws nothing the app depends on, captures no input (pointer-events:none in
// CSS), throttles to ~18fps, pauses when the tab is hidden, and stays still for
// users who prefer reduced motion.

const canvas = document.getElementById("matrix");
if (canvas && canvas.getContext) {
  const ctx = canvas.getContext("2d");
  const FONT = 14;
  const GLYPHS =
    "アカサタナハマヤラワabcdef0123456789<>/\\[]{}=+*$#%&ｱｲｳｴｵｶｷｸ｜";
  let cols = 0;
  let drops = [];
  let speeds = [];

  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    cols = Math.ceil(canvas.width / FONT);
    drops = new Array(cols).fill(0).map(() => Math.random() * -50);
    // each column falls at its own pace, so the rain never looks lock-stepped
    speeds = new Array(cols).fill(0).map(() => 0.45 + Math.random() * 0.9);
  }

  function draw() {
    // translucent black wash leaves fading tails behind each falling glyph
    ctx.fillStyle = "rgba(0, 6, 0, 0.09)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.font = `${FONT}px ui-monospace, SFMono-Regular, Menlo, monospace`;
    for (let i = 0; i < cols; i++) {
      const ch = GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
      const x = i * FONT;
      const y = drops[i] * FONT;
      // a bright "head" now and then, dim green for the rest of the stream
      ctx.fillStyle = Math.random() > 0.94 ? "#d6ffe6" : "#00ff66";
      ctx.fillText(ch, x, y);
      if (y > canvas.height && Math.random() > 0.975) drops[i] = 0;
      drops[i] += speeds[i];
    }
  }

  resize();
  window.addEventListener("resize", resize);

  const reduce =
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) {
    draw(); // a single static frame, no animation
  } else {
    let timer = setInterval(draw, 55);
    document.addEventListener("visibilitychange", () => {
      clearInterval(timer);
      if (!document.hidden) timer = setInterval(draw, 55);
    });
  }
}
