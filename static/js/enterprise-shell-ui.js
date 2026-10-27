/* Only enterprise-injected controls. Language/theme storage remains owned by Studio. */
(function(){
    function translate(){
        const en = localStorage.getItem('studio_lang') === 'en';
        document.querySelectorAll('#__ent_bar__ [data-ent-label]').forEach(el => {
            el.textContent = el.dataset.entLabel === 'admin' ? (en ? 'Administration' : '管理后台') : (en ? 'Sign out' : '退出');
        });
    }
    window.addEventListener('studio-lang-change', translate);
    window.addEventListener('storage', event => { if(event.key === 'studio_lang') translate(); });
    translate();
})();
