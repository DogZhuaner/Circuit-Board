// Restoring a protected page from browser history must recheck the login cookie.
window.addEventListener('pageshow', event => {
    if (event.persisted) window.location.reload();
});
