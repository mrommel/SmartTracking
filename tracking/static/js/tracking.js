/* Restore the saved theme before the page renders to avoid a flash of the wrong theme. */
(function() {
    const stored = localStorage.getItem('theme');
    const theme = stored === 'dark' || stored === 'light'
        ? stored
        : (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    document.documentElement.setAttribute('data-bs-theme', theme);

	function initializeToggle() {
        const toggle = document.getElementById('themeToggle');
        const icon = document.getElementById('themeIcon');
		if (!toggle || !icon) return;

		function updateIcon() {
            const theme = document.documentElement.getAttribute('data-bs-theme');
  			icon.textContent = theme === 'dark' ? '🌙' : '☀️';
		}

		toggle.addEventListener('click', function() {
			const html = document.documentElement;
            const current = html.getAttribute('data-bs-theme');
            const next = current === 'dark' ? 'light' : 'dark';
  			html.setAttribute('data-bs-theme', next);
  			localStorage.setItem('theme', next);
  			updateIcon();
		});

		updateIcon();
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', initializeToggle);
	} else {
		initializeToggle();
	}
})();

