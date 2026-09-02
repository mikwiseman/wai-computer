(() => {
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const hero = document.querySelector('.hero');
  if (!hero) return;
  let frame = 0;
  const paint = () => {
    frame = 0;
    const progress = motion.matches ? 0 : Math.min(window.scrollY, hero.offsetHeight);
    hero.style.setProperty('--scene-y', `${progress * 0.12}px`);
    hero.style.setProperty('--cloud-y', `${progress * 0.22}px`);
  };
  const update = () => { if (!frame) frame = window.requestAnimationFrame(paint); };
  window.addEventListener('scroll', update, { passive: true });
  motion.addEventListener('change', update);
  update();
})();
