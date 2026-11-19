/* Progressive enhancement shared by all server-rendered inventory pages. */
(() => {
  document.querySelectorAll('[data-open-form]').forEach((trigger) => {
    trigger.addEventListener('click', (event) => {
      const panel = document.getElementById(trigger.dataset.openForm);
      if (!panel) return;
      event.preventDefault();
      panel.open = true;
      panel.scrollIntoView({ block: 'nearest' });
      panel.querySelector('input, textarea, select')?.focus({ preventScroll: true });
    });
  });

  document.querySelectorAll('[data-close-form]').forEach((trigger) => {
    trigger.addEventListener('click', () => {
      const panel = document.getElementById(trigger.dataset.closeForm);
      if (!panel) return;
      panel.open = false;
      panel.querySelector('summary')?.focus();
    });
  });

  document.querySelectorAll('.clickable-row').forEach((row) => {
    row.addEventListener('click', (event) => {
      if (event.target.closest('a, button, form, input, textarea, select, label')) return;
      window.location.href = row.dataset.href;
    });
    row.addEventListener('keydown', (event) => {
      if (event.target !== row) return;
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        window.location.href = row.dataset.href;
      }
    });
  });

  const lightbox = document.getElementById('image-lightbox');
  if (!lightbox) return;
  const image = lightbox.querySelector('.image-lightbox-image');
  const caption = lightbox.querySelector('.image-lightbox-caption');
  const closeButton = lightbox.querySelector('.image-lightbox-close');
  let previousFocus = null;

  const closeLightbox = () => {
    lightbox.classList.remove('is-open');
    lightbox.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('lightbox-open');
    image.removeAttribute('src');
    previousFocus?.focus({ preventScroll: true });
  };

  document.querySelectorAll('.js-gallery-open').forEach((button) => {
    button.addEventListener('click', () => {
      previousFocus = button;
      image.src = button.dataset.src;
      image.alt = button.dataset.alt;
      caption.textContent = button.dataset.alt;
      lightbox.classList.add('is-open');
      lightbox.setAttribute('aria-hidden', 'false');
      document.body.classList.add('lightbox-open');
      closeButton.focus();
    });
  });
  closeButton.addEventListener('click', closeLightbox);
  lightbox.addEventListener('click', (event) => {
    if (event.target === lightbox) closeLightbox();
  });
  document.addEventListener('keydown', (event) => {
    if (!lightbox.classList.contains('is-open')) return;
    if (event.key === 'Escape') closeLightbox();
    if (event.key === 'Tab') {
      event.preventDefault();
      closeButton.focus();
    }
  });
})();
