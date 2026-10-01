(function () {
	'use strict';

	var script = document.currentScript;
	if (!script) {
		var scripts = document.querySelectorAll('script[data-widget-id][data-token]');
		script = scripts[scripts.length - 1];
	}
	if (!script) return;

	var widgetId = script.getAttribute('data-widget-id') || '';
	var token = script.getAttribute('data-token') || '';
	var apiBase = (script.getAttribute('data-api-base') || window.location.origin).replace(/\/$/, '');
	var mountId = 'owui-chat-widget-' + widgetId;

	if (!widgetId || !token || document.getElementById(mountId)) return;

	var storageKey = 'owui_chat_widget_' + widgetId;
	var state = loadState();
	var config = null;
	var isOpen = false;
	var isSending = false;

	var root = document.createElement('div');
	root.id = mountId;
	root.className = 'owui-widget';
	root.innerHTML =
		'<button class="owui-launcher" type="button" aria-label="Open chat">' +
		'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.75A3.75 3.75 0 0 1 7.75 2h8.5A3.75 3.75 0 0 1 20 5.75v6.5A3.75 3.75 0 0 1 16.25 16H11l-5.2 4.1A1.05 1.05 0 0 1 4 19.28V16.1A3.75 3.75 0 0 1 .25 12.35v-6.6A3.75 3.75 0 0 1 4 2h.4A5.73 5.73 0 0 0 2 6.75v5.6a5.74 5.74 0 0 0 4 5.47v-.34l4.1-3.23h6.15A1.75 1.75 0 0 0 18 12.5V5.75A1.75 1.75 0 0 0 16.25 4h-8.5A1.75 1.75 0 0 0 6 5.75v5.5a1 1 0 1 1-2 0v-5.5Z"/></svg>' +
		'</button>' +
		'<section class="owui-panel" aria-live="polite" aria-label="Chat widget">' +
		'<header class="owui-header"><div><div class="owui-title">Chat</div><div class="owui-subtitle">Online</div></div><button class="owui-close" type="button" aria-label="Close chat">x</button></header>' +
		'<div class="owui-messages"></div>' +
		'<form class="owui-form"><textarea class="owui-input" rows="1" placeholder="Type a message"></textarea><button class="owui-send" type="submit" aria-label="Send message"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.4 20.4 21.2 12 3.4 3.6 3 10.2l10.4 1.8L3 13.8l.4 6.6Z"/></svg></button></form>' +
		'</section>';

	document.documentElement.appendChild(root);
	injectStyles();

	var launcher = root.querySelector('.owui-launcher');
	var panel = root.querySelector('.owui-panel');
	var closeButton = root.querySelector('.owui-close');
	var messages = root.querySelector('.owui-messages');
	var form = root.querySelector('.owui-form');
	var input = root.querySelector('.owui-input');
	var sendButton = root.querySelector('.owui-send');
	var title = root.querySelector('.owui-title');
	var subtitle = root.querySelector('.owui-subtitle');

	launcher.addEventListener('click', function () {
		setOpen(!isOpen);
	});
	closeButton.addEventListener('click', function () {
		setOpen(false);
	});
	input.addEventListener('keydown', function (event) {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			form.requestSubmit();
		}
	});
	input.addEventListener('input', resizeInput);
	form.addEventListener('submit', function (event) {
		event.preventDefault();
		sendMessage();
	});

	loadConfig();

	function loadState() {
		try {
			var parsed = JSON.parse(window.localStorage.getItem(storageKey) || '{}');
			if (!parsed.visitor_id) parsed.visitor_id = cryptoRandomId();
			return parsed;
		} catch (error) {
			return { visitor_id: cryptoRandomId() };
		}
	}

	function saveState() {
		try {
			window.localStorage.setItem(storageKey, JSON.stringify(state));
		} catch (error) {
			// Storage can be blocked by the host page. The widget still works for the active tab.
		}
	}

	function cryptoRandomId() {
		if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
		return 'visitor_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
	}

	function setOpen(next) {
		isOpen = next;
		root.classList.toggle('owui-open', isOpen);
		if (isOpen) {
			loadConfig();
			setTimeout(function () {
				input.focus();
			}, 60);
		}
	}

	function loadConfig() {
		if (config) return Promise.resolve(config);
		setStatus('Connecting');
		return fetch(apiBase + '/api/v1/widgets/public/config?widget_id=' + encodeURIComponent(widgetId), {
			headers: {
				Accept: 'application/json',
				'X-Widget-Token': token
			}
		})
			.then(function (response) {
				if (!response.ok) throw new Error('Unable to load widget');
				return response.json();
			})
			.then(function (data) {
				config = data;
				title.textContent = data.name || 'Chat';
				setStatus('Online');
				if (data.welcome_message && messages.children.length === 0) {
					addMessage('assistant', data.welcome_message);
				}
				return data;
			})
			.catch(function () {
				setStatus('Unavailable');
				if (messages.children.length === 0) {
					addMessage('error', 'This chat is unavailable right now.');
				}
			});
	}

	function sendMessage() {
		var text = input.value.trim();
		if (!text || isSending) return;

		input.value = '';
		resizeInput();
		addMessage('user', text);
		var assistant = addMessage('assistant', '');
		assistant.classList.add('owui-streaming');
		isSending = true;
		sendButton.disabled = true;
		setStatus('Typing');

		fetch(apiBase + '/api/v1/widgets/public/chat', {
			method: 'POST',
			headers: {
				Accept: 'text/event-stream, application/json',
				'Content-Type': 'application/json',
				'X-Widget-Token': token
			},
			body: JSON.stringify({
				widget_id: widgetId,
				visitor_id: state.visitor_id,
				session_id: state.session_id || null,
				message: text,
				stream: true
			})
		})
			.then(function (response) {
				if (!response.ok) throw new Error('Message failed');
				var contentType = response.headers.get('content-type') || '';
				if (contentType.indexOf('text/event-stream') !== -1 && response.body) {
					return readStream(response, assistant);
				}
				return response.json().then(function (data) {
					if (data.session_id) {
						state.session_id = data.session_id;
						saveState();
					}
					setMessageText(assistant, data.content || '');
				});
			})
			.catch(function () {
				assistant.classList.add('owui-error');
				setMessageText(assistant, 'Something went wrong. Please try again.');
			})
			.finally(function () {
				assistant.classList.remove('owui-streaming');
				isSending = false;
				sendButton.disabled = false;
				setStatus('Online');
				input.focus();
			});
	}

	function readStream(response, assistant) {
		var reader = response.body.getReader();
		var decoder = new TextDecoder();
		var buffer = '';
		var fullText = '';

		function pump() {
			return reader.read().then(function (result) {
				if (result.done) {
					if (buffer.trim()) processEvent(buffer);
					return;
				}
				buffer += decoder.decode(result.value, { stream: true });
				var index;
				while ((index = buffer.indexOf('\n\n')) !== -1) {
					processEvent(buffer.slice(0, index));
					buffer = buffer.slice(index + 2);
				}
				return pump();
			});
		}

		function processEvent(eventText) {
			eventText.split('\n').forEach(function (line) {
				line = line.trim();
				if (line.indexOf('data:') !== 0) return;
				var payload = line.slice(5).trim();
				if (!payload || payload === '[DONE]') return;
				try {
					var data = JSON.parse(payload);
					if (data.widget && data.widget.session_id) {
						state.session_id = data.widget.session_id;
						saveState();
						return;
					}
					var delta = extractDelta(data);
					if (delta) {
						fullText += delta;
						setMessageText(assistant, fullText);
					}
				} catch (error) {
					// Ignore non-JSON SSE comments or provider-specific keepalives.
				}
			});
		}

		return pump();
	}

	function extractDelta(data) {
		var choice = data && data.choices && data.choices[0];
		if (!choice) return '';
		if (choice.delta && typeof choice.delta.content === 'string') return choice.delta.content;
		if (choice.message && typeof choice.message.content === 'string') return choice.message.content;
		if (typeof choice.text === 'string') return choice.text;
		return '';
	}

	function addMessage(role, text) {
		var node = document.createElement('div');
		node.className = 'owui-message owui-' + role;
		var bubble = document.createElement('div');
		bubble.className = 'owui-bubble';
		bubble.textContent = text;
		node.appendChild(bubble);
		messages.appendChild(node);
		scrollMessages();
		return node;
	}

	function setMessageText(node, text) {
		var bubble = node.querySelector('.owui-bubble');
		bubble.textContent = text || ' ';
		scrollMessages();
	}

	function setStatus(text) {
		subtitle.textContent = text;
	}

	function scrollMessages() {
		messages.scrollTop = messages.scrollHeight;
	}

	function resizeInput() {
		input.style.height = 'auto';
		input.style.height = Math.min(input.scrollHeight, 112) + 'px';
	}

	function injectStyles() {
		if (document.getElementById('owui-chat-widget-styles')) return;
		var style = document.createElement('style');
		style.id = 'owui-chat-widget-styles';
		style.textContent =
			'.owui-widget{position:fixed;right:20px;bottom:20px;z-index:2147483000;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#111827}' +
			'.owui-launcher{width:56px;height:56px;border:0;border-radius:999px;background:#111827;color:#fff;box-shadow:0 16px 38px rgba(0,0,0,.22);display:flex;align-items:center;justify-content:center;cursor:pointer;transition:transform .16s ease,box-shadow .16s ease}' +
			'.owui-launcher:hover{transform:translateY(-1px);box-shadow:0 18px 44px rgba(0,0,0,.28)}.owui-launcher svg{width:27px;height:27px;fill:currentColor}' +
			'.owui-panel{position:absolute;right:0;bottom:72px;width:min(380px,calc(100vw - 32px));height:min(620px,calc(100vh - 110px));background:#fff;border:1px solid rgba(17,24,39,.1);border-radius:12px;box-shadow:0 24px 70px rgba(0,0,0,.22);display:none;overflow:hidden}' +
			'.owui-open .owui-panel{display:flex;flex-direction:column}.owui-header{height:58px;display:flex;align-items:center;justify-content:space-between;padding:0 14px;border-bottom:1px solid #eef0f3;background:#fff}' +
			'.owui-title{font-size:15px;font-weight:650;line-height:1.2}.owui-subtitle{font-size:12px;color:#6b7280;margin-top:2px}.owui-close{width:32px;height:32px;border:0;border-radius:8px;background:transparent;color:#4b5563;cursor:pointer;font-size:18px;line-height:1}.owui-close:hover{background:#f3f4f6}' +
			'.owui-messages{flex:1;overflow:auto;padding:14px;display:flex;flex-direction:column;gap:10px;background:#fafafa}.owui-message{display:flex}.owui-user{justify-content:flex-end}.owui-assistant,.owui-error{justify-content:flex-start}' +
			'.owui-bubble{max-width:82%;white-space:pre-wrap;overflow-wrap:anywhere;border-radius:12px;padding:9px 11px;font-size:14px;line-height:1.45;background:#fff;border:1px solid #eceff3;color:#111827}.owui-user .owui-bubble{background:#111827;color:#fff;border-color:#111827}.owui-error .owui-bubble{background:#fff1f2;border-color:#fecdd3;color:#9f1239}' +
			'.owui-streaming .owui-bubble:empty:after{content:"";display:inline-block;width:6px;height:6px;border-radius:999px;background:#9ca3af;animation:owuiPulse 1s infinite}' +
			'.owui-form{display:flex;align-items:flex-end;gap:8px;padding:10px;border-top:1px solid #eef0f3;background:#fff}.owui-input{flex:1;min-height:40px;max-height:112px;resize:none;border:1px solid #d9dee7;border-radius:10px;padding:10px 11px;font:inherit;font-size:14px;line-height:1.35;outline:none;background:#fff;color:#111827}.owui-input:focus{border-color:#111827}' +
			'.owui-send{width:40px;height:40px;flex:0 0 40px;border:0;border-radius:10px;background:#111827;color:#fff;display:flex;align-items:center;justify-content:center;cursor:pointer}.owui-send:disabled{opacity:.55;cursor:not-allowed}.owui-send svg{width:19px;height:19px;fill:currentColor}' +
			'@keyframes owuiPulse{0%,100%{opacity:.35;transform:scale(.8)}50%{opacity:1;transform:scale(1)}}' +
			'@media (max-width:480px){.owui-widget{right:12px;bottom:12px}.owui-panel{right:-4px;bottom:68px;width:calc(100vw - 24px);height:min(620px,calc(100vh - 92px));border-radius:10px}.owui-launcher{width:52px;height:52px}}';
		document.head.appendChild(style);
	}
})();
