(() => {
  const video = document.getElementById('home-video');
  if (!video) return;

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  if (!reducedMotion.matches) {
    video.muted = true;
    // Native controls remain available if the browser declines autoplay.
    video.play().catch(() => {});
  }

  reducedMotion.addEventListener('change', (event) => {
    if (event.matches) video.pause();
  });
})();
