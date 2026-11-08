(function () {
	'use strict';
	var widgetId = location.pathname.split('/').filter(Boolean).pop();
	var token = new URLSearchParams(location.hash.slice(1)).get('token');
	var status = document.getElementById('status');
	var error = document.getElementById('error');
	if (!token) {
		status.textContent = '';
		error.textContent = 'Open Preview from the chatbot settings, or use the complete preview link.';
		return;
	}
	fetch('/api/v1/widgets/public/config?widget_id=' + encodeURIComponent(widgetId), {
		headers: { 'X-Widget-Token': token }
	})
		.then(function (response) {
			if (!response.ok)
				throw new Error(
					'This preview is unavailable. Check that the chatbot is enabled, its selected model is available, and the preview link is current.'
				);
			return response.json();
		})
		.then(function (config) {
			document.getElementById('name').textContent = config.name;
			document.title = config.name + ' — Chatbot preview';
			var script = document.createElement('script');
			script.src = '/api/v1/widgets/public/embed.js';
			script.dataset.widgetId = widgetId;
			script.dataset.token = token;
			script.dataset.apiBase = location.origin;
			script.onload = function () {
				status.textContent = 'Connected. This is a live chat.';
				var launcher = document.querySelector('.owui-launcher');
				if (launcher) launcher.click();
			};
			script.onerror = function () {
				error.textContent = 'The chat script could not load. Please refresh to retry.';
				status.textContent = '';
			};
			document.body.appendChild(script);
			var copy = document.getElementById('copy');
			copy.hidden = false;
			copy.onclick = function () {
				if (!navigator.clipboard) {
					status.textContent = 'Copy the complete URL from your address bar.';
					return;
				}
				navigator.clipboard
					.writeText(location.href)
					.then(function () {
						status.textContent = 'Preview link copied. Anyone with this link can try the chatbot.';
					})
					.catch(function () {
						status.textContent = 'Copy the complete URL from your address bar.';
					});
			};
		})
		.catch(function (reason) {
			status.textContent = '';
			error.textContent = reason.message || 'Unable to load preview.';
		});
})();
