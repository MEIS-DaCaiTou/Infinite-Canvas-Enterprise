/* Presentation opt-in only. Original page authentication and actions are reused. */
if (new URLSearchParams(location.search).get('embedded') === 'admin') {
    document.documentElement.classList.add('admin-embedded');
}
