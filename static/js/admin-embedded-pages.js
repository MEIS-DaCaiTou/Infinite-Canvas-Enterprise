/* Reuse the existing profile and audit pages without navigating the admin shell. */
window.AdminEmbeddedPages = {
    initialize() {
        const dialog = document.getElementById('adminPersonalDialog');
        document.getElementById('openPersonalCenter').onclick = () => {
            document.querySelector('.admin-account').open = false;
            const frame = document.getElementById('adminPersonalFrame');
            frame.src = frame.dataset.src;
            dialog.showModal();
        };
        document.getElementById('closePersonalCenter').onclick = () => dialog.close();
        dialog.addEventListener('close', () => {
            document.getElementById('adminPersonalFrame').removeAttribute('src');
            document.querySelector('.admin-account>summary').focus();
        });
    },
    openLogs() {
        const frame = document.getElementById('adminLogsFrame');
        if (!frame.hasAttribute('src')) frame.src = frame.dataset.src;
    }
};
