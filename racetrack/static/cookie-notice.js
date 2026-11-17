(() => {
  const notice = document.querySelector('[data-cookie-notice]');
  if (!notice) return;

  // This is a notice, not consent to optional tracking. No optional cookies,
  // analytics or advertising scripts are enabled by any action here.
  const preferenceKey = 'trackops.cookie-notice.v1';
  let returnFocus = null;
  let dismissed = false;
  try {
    dismissed = sessionStorage.getItem(preferenceKey) === 'dismissed';
  } catch (_) {
    // The notice still works when the browser blocks storage.
  }

  function updateSpace() {
    document.documentElement.style.setProperty(
      '--cookie-notice-space', notice.hidden ? '0px' : `${notice.offsetHeight + 32}px`
    );
  }

  function showNotice() {
    notice.hidden = false;
    document.body.classList.add('cookie-notice-visible');
    updateSpace();
  }

  function dismissNotice() {
    try {
      sessionStorage.setItem(preferenceKey, 'dismissed');
    } catch (_) {
      // Dismiss for this page even if browser storage is unavailable.
    }
    notice.hidden = true;
    document.body.classList.remove('cookie-notice-visible');
    updateSpace();
    if (returnFocus) {
      returnFocus.focus();
      returnFocus = null;
    }
  }

  notice.querySelector('[data-cookie-dismiss]').addEventListener('click', dismissNotice);
  document.querySelectorAll('[data-cookie-settings]').forEach(link => {
    link.addEventListener('click', event => {
      event.preventDefault();
      returnFocus = link;
      showNotice();
      notice.focus({ preventScroll: true });
    });
  });
  notice.addEventListener('keydown', event => {
    if (event.key === 'Escape') dismissNotice();
  });
  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(updateSpace).observe(notice);
  } else {
    window.addEventListener('resize', updateSpace);
  }
  if (!dismissed) showNotice();
})();
