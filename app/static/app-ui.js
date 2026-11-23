/* Progressive enhancement shared by all server-rendered inventory pages. */
(() => {
  document.querySelectorAll('[data-open-form]').forEach((trigger) => {
    trigger.addEventListener('click', (event) => {
      const panel = document.getElementById(trigger.dataset.openForm);
      if (!panel) return;
      event.preventDefault();
      panel.open = true;
      panel.scrollIntoView({ block: 'nearest' });
      panel.querySelector('input:not([type="hidden"]), textarea, select')?.focus({ preventScroll: true });
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

  const confirmDialog = document.getElementById('confirm-dialog');
  let pending = null;
  const approved = new WeakSet();
  const submitted = new WeakSet();
  document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (submitted.has(form)) { event.preventDefault(); return; }
      if (approved.has(form)) {
        approved.delete(form);
        submitted.add(form);
        return;
      }
      event.preventDefault();
      if (pending) return;
      const submitter = event.submitter;
      pending = { form, submitter, focus: document.activeElement };
      confirmDialog.querySelector('#confirm-description').textContent = form.dataset.confirm;
      confirmDialog.querySelector('#confirm-action').textContent = form.dataset.confirmAction || submitter?.textContent.trim() || 'Potwierdź';
      confirmDialog.returnValue = '';
      confirmDialog.showModal();
      confirmDialog.querySelector('[value="cancel"]').focus();
    });
  });
  confirmDialog?.addEventListener('close', () => {
    const action = pending;
    pending = null;
    if (!action) return;
    action.focus?.focus({ preventScroll: true });
    if (confirmDialog.returnValue === 'confirm' && action.form.isConnected) {
      approved.add(action.form);
      action.form.requestSubmit(action.submitter || undefined);
    }
  });
  // Back/forward cache must not leave an already-submitted form locked.
  window.addEventListener('pageshow', () => document.querySelectorAll('form[data-confirm]').forEach(form => submitted.delete(form)));

  document.querySelectorAll('[data-filter-table]').forEach((input) => {
    const table = document.getElementById(input.dataset.filterTable);
    if (!table) return;
    const rows = Array.from(table.querySelectorAll('tbody tr'));
    const status = document.querySelector(`[data-filter-status="${table.id}"]`);
    input.addEventListener('input', () => {
      const query = input.value.trim().toLocaleLowerCase('pl');
      let visible = 0;
      rows.forEach((row) => {
        row.hidden = !row.textContent.toLocaleLowerCase('pl').includes(query);
        if (!row.hidden) visible++;
      });
      status.textContent = visible ? `Widoczne rekordy: ${visible} z ${rows.length}` : 'Brak pasujących rekordów. Zmień lub wyczyść filtr.';
    });
  });

  const lightbox = document.getElementById('image-lightbox');
  if (!lightbox) return;
  const buttons = Array.from(document.querySelectorAll('.js-gallery-open'));
  const image = lightbox.querySelector('.image-lightbox-image');
  const caption = lightbox.querySelector('.image-lightbox-caption');
  const counter = lightbox.querySelector('.lightbox-counter');
  const feedback = lightbox.querySelector('.lightbox-feedback');
  const message = lightbox.querySelector('.lightbox-message');
  const retry = lightbox.querySelector('.lightbox-retry');
  const closeButton = lightbox.querySelector('.image-lightbox-close');
  const previous = lightbox.querySelector('.image-lightbox-prev');
  const next = lightbox.querySelector('.image-lightbox-next');
  const stage = lightbox.querySelector('.lightbox-stage');
  let index = 0;
  let previousFocus = null;
  let start = null;
  let swiped = false;

  const fitImage = () => {
    if (!lightbox.open || image.hidden || !image.naturalWidth || !image.naturalHeight) return;
    // Use the actual stage dimensions: percentage max-height inside grid can
    // otherwise resolve against an intrinsic track and clip camera-sized files.
    const scale = Math.min(stage.clientWidth / image.naturalWidth,
                           stage.clientHeight / image.naturalHeight, 1);
    image.style.width = `${image.naturalWidth * scale}px`;
    image.style.height = `${image.naturalHeight * scale}px`;
  };
  if ('ResizeObserver' in window) new ResizeObserver(fitImage).observe(stage);
  window.addEventListener('resize', fitImage);

  const showImage = (position) => {
    index = (position + buttons.length) % buttons.length;
    const selected = buttons[index];
    image.hidden = true;
    image.style.width = image.style.height = '';
    feedback.hidden = false;
    retry.hidden = true;
    message.textContent = 'Wczytywanie zdjęcia…';
    stage.setAttribute('aria-busy', 'true');
    caption.textContent = selected.dataset.alt;
    counter.textContent = `${index + 1} / ${buttons.length}`;
    previous.disabled = next.disabled = buttons.length < 2;
    image.alt = selected.dataset.alt;
    image.src = selected.dataset.src;
  };
  image.addEventListener('load', () => {
    if (!lightbox.open) return;
    image.hidden = false;
    feedback.hidden = true;
    stage.setAttribute('aria-busy', 'false');
    fitImage();
  });
  image.addEventListener('error', () => {
    if (!lightbox.open) return;
    image.hidden = true;
    feedback.hidden = false;
    retry.hidden = false;
    message.textContent = 'Nie udało się wczytać zdjęcia. Plik może być niedostępny.';
    stage.setAttribute('aria-busy', 'false');
  });
  buttons.forEach((button, position) => {
    button.addEventListener('click', (event) => {
      event.preventDefault();
      previousFocus = button;
      lightbox.showModal();
      lightbox.classList.add('is-open');
      lightbox.setAttribute('aria-hidden', 'false');
      document.body.classList.add('lightbox-open');
      showImage(position);
      closeButton.focus();
    });
  });
  lightbox.addEventListener('close', () => {
    lightbox.classList.remove('is-open');
    lightbox.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('lightbox-open');
    image.removeAttribute('src');
    previousFocus?.focus({ preventScroll: true });
  });
  closeButton.addEventListener('click', () => lightbox.close());
  previous.addEventListener('click', () => showImage(index - 1));
  next.addEventListener('click', () => showImage(index + 1));
  retry.addEventListener('click', () => { image.removeAttribute('src'); showImage(index); });
  lightbox.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      showImage(index + (event.key === 'ArrowRight' ? 1 : -1));
    }
  });
  stage.addEventListener('pointerdown', event => {
    if (event.pointerType === 'touch' && event.isPrimary) start = { x: event.clientX, y: event.clientY, id: event.pointerId };
  });
  stage.addEventListener('pointercancel', () => { start = null; });
  stage.addEventListener('pointerup', event => {
    if (!start || start.id !== event.pointerId) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    start = null;
    if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) {
      showImage(index + (dx < 0 ? 1 : -1));
      swiped = true;
      window.setTimeout(() => { swiped = false; }, 300);
    }
  });
  lightbox.addEventListener('click', event => {
    if (swiped) { swiped = false; return; }
    if (event.target === lightbox || event.target === stage) lightbox.close();
  });
})();
