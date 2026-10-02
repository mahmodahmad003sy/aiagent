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

	var FONT_STACKS = {
		system: 'Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',
		arial: 'Arial,Helvetica,sans-serif',
		verdana: 'Verdana,Geneva,sans-serif',
		tahoma: 'Tahoma,Geneva,sans-serif',
		trebuchet: '"Trebuchet MS",Helvetica,sans-serif',
		georgia: 'Georgia,serif',
		times: '"Times New Roman",Times,serif',
		courier: '"Courier New",Courier,monospace'
	};
	var LAUNCHER_RADIUS = { circle: '999px', rounded: '16px', square: '6px' };

	var storageKey = 'owui_chat_widget_' + widgetId;
	var state = loadState();
	var config = null;
	var configPromise = null;
	var isOpen = false;
	var isSending = false;
	var isReady = false;
	var unreadCount = 0;

	var root = document.createElement('div');
	root.id = mountId;
	root.className = 'owui-widget';
	root.classList.add('owui-loading');
	root.innerHTML =
		'<button class="owui-launcher" type="button" aria-label="Open chat" aria-expanded="false">' +
		'<svg class="owui-launcher-chat" viewBox="0 0 24 24" aria-hidden="true"><path d="M5.5 4A3.5 3.5 0 0 0 2 7.5v5A3.5 3.5 0 0 0 5.5 16H7v3.2a.8.8 0 0 0 1.3.62L13.08 16h5.42A3.5 3.5 0 0 0 22 12.5v-5A3.5 3.5 0 0 0 18.5 4h-13Zm0 2h13A1.5 1.5 0 0 1 20 7.5v5a1.5 1.5 0 0 1-1.5 1.5h-6.12L9 16.7V14H5.5A1.5 1.5 0 0 1 4 12.5v-5A1.5 1.5 0 0 1 5.5 6Z"/></svg>' +
		'<svg class="owui-launcher-close" viewBox="0 0 24 24" aria-hidden="true"><path d="m6.4 5 5.6 5.6L17.6 5 19 6.4 13.4 12l5.6 5.6-1.4 1.4-5.6-5.6L6.4 19 5 17.6l5.6-5.6L5 6.4 6.4 5Z"/></svg>' +
		'<span class="owui-badge" aria-hidden="true"></span>' +
		'</button>' +
		'<section class="owui-panel" aria-label="Chat widget" aria-live="polite" role="dialog">' +
		'<header class="owui-header"><div class="owui-brand"><div class="owui-avatar"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5.5 4A3.5 3.5 0 0 0 2 7.5v5A3.5 3.5 0 0 0 5.5 16H7v3.2a.8.8 0 0 0 1.3.62L13.08 16h5.42A3.5 3.5 0 0 0 22 12.5v-5A3.5 3.5 0 0 0 18.5 4h-13Z"/></svg></div><div class="owui-heading"><div class="owui-title">Chat</div><div class="owui-status"><span class="owui-status-dot"></span><span class="owui-subtitle">Connecting</span></div></div></div><button class="owui-close" type="button" aria-label="Close chat"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6.4 5 5.6 5.6L17.6 5 19 6.4 13.4 12l5.6 5.6-1.4 1.4-5.6-5.6L6.4 19 5 17.6l5.6-5.6L5 6.4 6.4 5Z"/></svg></button></header>' +
		'<div class="owui-messages"></div>' +
		'<form class="owui-form"><textarea class="owui-input" rows="1" placeholder="Type a message" aria-label="Message"></textarea><button class="owui-send" type="submit" aria-label="Send message"><svg class="owui-send-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M3.4 20.4 21.2 12 3.4 3.6 3 10.2l10.4 1.8L3 13.8l.4 6.6Z"/></svg><span class="owui-send-spinner" aria-hidden="true"></span></button></form>' +
		'</section>';

	document.documentElement.appendChild(root);
	injectStyles();

	var launcher = root.querySelector('.owui-launcher');
	var closeButton = root.querySelector('.owui-close');
	var messages = root.querySelector('.owui-messages');
	var form = root.querySelector('.owui-form');
	var input = root.querySelector('.owui-input');
	var sendButton = root.querySelector('.owui-send');
	var title = root.querySelector('.owui-title');
	var subtitle = root.querySelector('.owui-subtitle');
	var badge = root.querySelector('.owui-badge');

	launcher.addEventListener('click', function () {
		setOpen(!isOpen);
	});
	closeButton.addEventListener('click', function () {
		setOpen(false);
	});
	document.addEventListener('keydown', function (event) {
		if (event.key === 'Escape' && isOpen) setOpen(false);
	});
	input.addEventListener('keydown', function (event) {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			if (form.requestSubmit) {
				form.requestSubmit();
			} else {
				form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
			}
		}
	});
	input.addEventListener('input', resizeInput);
	form.addEventListener('submit', function (event) {
		event.preventDefault();
		sendMessage();
	});

	setInputEnabled(false);
	updateLauncher();
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
			unreadCount = 0;
			loadConfig();
			setTimeout(function () {
				input.focus();
			}, 80);
		}
		updateLauncher();
	}

	function updateLauncher() {
		launcher.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
		launcher.setAttribute('aria-label', isOpen ? 'Close chat' : 'Open chat');
		if (!badge) return;
		if (isOpen || unreadCount < 1) {
			badge.textContent = '';
			badge.classList.remove('owui-badge-visible');
			return;
		}
		badge.textContent = unreadCount > 9 ? '9+' : String(unreadCount);
		badge.classList.add('owui-badge-visible');
	}

	function loadConfig() {
		if (config) return Promise.resolve(config);
		if (configPromise) return configPromise;

		isReady = false;
		setInputEnabled(false);
		setStatus('Connecting');
		root.classList.remove('owui-unavailable');

		configPromise = fetch(apiBase + '/api/v1/widgets/public/config?widget_id=' + encodeURIComponent(widgetId), {
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
				applyTheme(data.theme);
				isReady = true;
				setStatus('Online');
				setInputEnabled(true);
				if (data.welcome_message && messages.children.length === 0) {
					addMessage('assistant', data.welcome_message, { quiet: true });
				}
				return data;
			})
			.catch(function () {
				isReady = false;
				root.classList.add('owui-unavailable');
				setStatus('Unavailable');
				setInputEnabled(false);
				if (messages.children.length === 0) {
					addMessage('error', 'This chat is unavailable right now.', { quiet: true });
				}
			})
			.finally(function () {
				configPromise = null;
				root.classList.remove('owui-loading');
			});

		return configPromise;
	}

	function sendMessage() {
		var text = input.value.trim();
		if (!text || isSending) return;

		if (!isReady) {
			loadConfig();
			return;
		}

		input.value = '';
		resizeInput();
		addMessage('user', text, { quiet: true });

		var assistant = addMessage('assistant', '', { streaming: true, quiet: true });
		isSending = true;
		root.classList.add('owui-sending');
		setInputEnabled(false);
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
					if (data.content && !isOpen) bumpUnread();
				});
			})
			.catch(function () {
				assistant.classList.add('owui-error');
				setMessageText(assistant, 'Something went wrong. Please try again.');
				if (!isOpen) bumpUnread();
			})
			.finally(function () {
				assistant.classList.remove('owui-streaming');
				isSending = false;
				root.classList.remove('owui-sending');
				setInputEnabled(isReady);
				setStatus(isReady ? 'Online' : 'Unavailable');
				if (isOpen) input.focus();
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
					if (data.widget_status) {
						setStatus('Using tools');
						return;
					}
					if (data.widget_final) {
						fullText = data.widget_final.content || fullText;
						setMessageText(assistant, fullText);
						return;
					}
					if (data.widget_error) {
						assistant.classList.add('owui-error');
						fullText = data.widget_error.message || 'Something went wrong. Please try again.';
						setMessageText(assistant, fullText);
						return;
					}
					var delta = extractDelta(data);
					if (delta) {
						setStatus('Typing');
						fullText += delta;
						setMessageText(assistant, fullText);
					}
				} catch (error) {
					// Ignore non-JSON SSE comments or provider-specific keepalives.
				}
			});
		}

		return pump().then(function () {
			if (fullText && !isOpen) bumpUnread();
		});
	}

	function extractDelta(data) {
		var choice = data && data.choices && data.choices[0];
		if (!choice) return '';
		if (choice.delta && typeof choice.delta.content === 'string') return choice.delta.content;
		if (choice.message && typeof choice.message.content === 'string') return choice.message.content;
		if (typeof choice.text === 'string') return choice.text;
		return '';
	}

	function addMessage(role, text, options) {
		var opts = options || {};
		var node = document.createElement('div');
		node.className = 'owui-message owui-' + role;
		if (opts.streaming) node.classList.add('owui-streaming');

		var bubble = document.createElement('div');
		bubble.className = 'owui-bubble';
		bubble.textContent = text || '';
		node.appendChild(bubble);
		messages.appendChild(node);

		if (!opts.quiet && role !== 'user' && !isOpen) bumpUnread();
		scrollMessages();
		return node;
	}

	function setMessageText(node, text) {
		var bubble = node.querySelector('.owui-bubble');
		bubble.textContent = text || '';
		scrollMessages();
	}

	function bumpUnread() {
		unreadCount += 1;
		updateLauncher();
	}

	function setInputEnabled(enabled) {
		input.disabled = !enabled;
		sendButton.disabled = !enabled || isSending;
		root.classList.toggle('owui-ready', enabled);
	}

	function setStatus(text) {
		subtitle.textContent =
			config && config.theme && config.theme.header_subtitle && text === 'Online'
				? config.theme.header_subtitle
				: text;
		root.setAttribute('data-status', text.toLowerCase());
	}

	function applyTheme(theme) {
		theme = theme || {};
		var vars = {
			'--owui-primary': theme.primary_color || '#111827',
			'--owui-on-primary': theme.primary_text_color || '#ffffff',
			'--owui-header-bg': theme.header_background_color || '#ffffff',
			'--owui-header-fg': theme.header_text_color || '#111827',
			'--owui-bg': theme.background_color || '#fafafa',
			'--owui-assistant-bg': theme.assistant_bubble_color || '#ffffff',
			'--owui-assistant-fg': theme.assistant_text_color || '#111827',
			'--owui-user-bg': theme.user_bubble_color || '#111827',
			'--owui-user-fg': theme.user_text_color || '#ffffff',
			'--owui-font': FONT_STACKS[theme.font_family] || FONT_STACKS.system,
			'--owui-font-size': (theme.font_size || 14) + 'px',
			'--owui-panel-radius': (theme.panel_radius != null ? theme.panel_radius : 12) + 'px',
			'--owui-bubble-radius': (theme.bubble_radius != null ? theme.bubble_radius : 12) + 'px',
			'--owui-launcher-radius': LAUNCHER_RADIUS[theme.launcher_shape] || LAUNCHER_RADIUS.circle,
			'--owui-launcher-size': (theme.launcher_size || 58) + 'px',
			'--owui-offset-x': (theme.offset_x != null ? theme.offset_x : 20) + 'px',
			'--owui-offset-y': (theme.offset_y != null ? theme.offset_y : 20) + 'px',
			'--owui-panel-width': (theme.panel_width || 390) + 'px',
			'--owui-panel-height': (theme.panel_height || 640) + 'px'
		};
		Object.keys(vars).forEach(function (key) {
			root.style.setProperty(key, vars[key]);
		});

		root.classList.toggle('owui-left', theme.position === 'left');
		root.classList.toggle('owui-hide-status', theme.show_status === false);
		input.placeholder = theme.input_placeholder || 'Type a message';
		if (theme.header_title) title.textContent = theme.header_title;

		if (theme.avatar_url) {
			setAvatarImage(root.querySelector('.owui-avatar'), theme.avatar_url, 'owui-avatar-img');
			if (theme.launcher_icon === 'avatar') {
				launcher.classList.add('owui-launcher-has-img');
				setAvatarImage(launcher, theme.avatar_url, 'owui-launcher-img');
			}
		}
	}

	function setAvatarImage(container, src, className) {
		var img = container.querySelector('img.' + className);
		if (!img) {
			img = document.createElement('img');
			img.className = className;
			img.alt = '';
			container.insertBefore(img, container.firstChild);
		}
		img.src = src;
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
			'.owui-widget{position:fixed;right:var(--owui-offset-x,20px);bottom:var(--owui-offset-y,20px);z-index:2147483000;font-family:var(--owui-font);color:#111827;letter-spacing:0}' +
			'.owui-widget *{box-sizing:border-box}.owui-widget button,.owui-widget textarea{font:inherit;letter-spacing:0}' +
			'.owui-loading{visibility:hidden}' +
			'.owui-launcher{position:relative;width:var(--owui-launcher-size,58px);height:var(--owui-launcher-size,58px);border:0;border-radius:var(--owui-launcher-radius,999px);background:var(--owui-primary,#111827);color:var(--owui-on-primary,#fff);overflow:hidden;box-shadow:0 16px 38px rgba(0,0,0,.22);display:flex;align-items:center;justify-content:center;cursor:pointer;transition:transform .16s ease,box-shadow .16s ease,background .16s ease}' +
			'.owui-launcher:hover{transform:translateY(-1px);box-shadow:0 18px 44px rgba(0,0,0,.28)}.owui-launcher:focus-visible{outline:3px solid rgba(37,99,235,.35);outline-offset:3px}.owui-launcher svg{width:27px;height:27px;fill:currentColor;transition:opacity .16s ease,transform .16s ease}' +
			'.owui-launcher-close{position:absolute;opacity:0;transform:scale(.82) rotate(-12deg)}.owui-open .owui-launcher-chat{opacity:0;transform:scale(.82) rotate(12deg)}.owui-open .owui-launcher-close{opacity:1;transform:scale(1) rotate(0)}' +
			'.owui-badge{position:absolute;right:-3px;top:-3px;min-width:19px;height:19px;padding:0 5px;border-radius:999px;background:#dc2626;color:#fff;border:2px solid #fff;font-size:11px;font-weight:700;line-height:15px;display:none;align-items:center;justify-content:center}.owui-badge-visible{display:flex}' +
			'.owui-panel{position:absolute;right:0;bottom:calc(var(--owui-launcher-size,58px) + 18px);width:min(var(--owui-panel-width,390px),calc(100vw - 32px));height:min(var(--owui-panel-height,640px),calc(100vh - 112px));background:#fff;border:1px solid rgba(17,24,39,.1);border-radius:var(--owui-panel-radius,12px);box-shadow:0 24px 70px rgba(0,0,0,.22);display:flex;flex-direction:column;overflow:hidden;opacity:0;pointer-events:none;transform:translateY(10px) scale(.98);transform-origin:bottom right;transition:opacity .16s ease,transform .16s ease}' +
			'.owui-open .owui-panel{opacity:1;pointer-events:auto;transform:translateY(0) scale(1)}' +
			'.owui-left{left:var(--owui-offset-x,20px);right:auto}.owui-left .owui-panel{left:0;right:auto;transform-origin:bottom left}.owui-hide-status .owui-status{display:none}' +
			'.owui-header{height:62px;flex:0 0 62px;display:flex;align-items:center;justify-content:space-between;padding:0 14px;border-bottom:1px solid #eef0f3;background:var(--owui-header-bg,#fff)}.owui-brand{min-width:0;display:flex;align-items:center;gap:10px}.owui-avatar{width:36px;height:36px;border-radius:10px;background:var(--owui-primary,#111827);color:var(--owui-on-primary,#fff);overflow:hidden;display:flex;align-items:center;justify-content:center;flex:0 0 auto}.owui-avatar svg{width:19px;height:19px;fill:currentColor}.owui-avatar-img{width:100%;height:100%;object-fit:cover;display:block}.owui-avatar-img~svg{display:none}.owui-heading{min-width:0}.owui-title{max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:calc(var(--owui-font-size,14px) + 1px);font-weight:650;line-height:1.2;color:var(--owui-header-fg,#111827)}.owui-status{display:flex;align-items:center;gap:6px;margin-top:3px}.owui-status-dot{width:7px;height:7px;border-radius:999px;background:#9ca3af}.owui-ready .owui-status-dot{background:#16a34a}.owui-unavailable .owui-status-dot{background:#dc2626}.owui-sending .owui-status-dot{background:#2563eb;animation:owuiPulse 1s infinite}.owui-subtitle{font-size:12px;color:var(--owui-header-fg,#6b7280);opacity:.7;line-height:1.2}' +
			'.owui-close{width:34px;height:34px;flex:0 0 34px;border:0;border-radius:8px;background:transparent;color:var(--owui-header-fg,#4b5563);display:flex;align-items:center;justify-content:center;cursor:pointer}.owui-close:hover{background:#f3f4f6}.owui-close:focus-visible{outline:3px solid rgba(37,99,235,.25);outline-offset:1px}.owui-close svg{width:19px;height:19px;fill:currentColor}' +
			'.owui-messages{flex:1;overflow:auto;padding:14px;display:flex;flex-direction:column;gap:10px;background:var(--owui-bg,#fafafa);scrollbar-width:thin}.owui-message{display:flex;min-width:0}.owui-user{justify-content:flex-end}.owui-assistant,.owui-error{justify-content:flex-start}.owui-bubble{max-width:82%;white-space:pre-wrap;overflow-wrap:anywhere;border-radius:var(--owui-bubble-radius,12px);padding:9px 11px;font-size:var(--owui-font-size,14px);line-height:1.45;background:var(--owui-assistant-bg,#fff);border:1px solid #eceff3;color:var(--owui-assistant-fg,#111827);box-shadow:0 1px 2px rgba(17,24,39,.04)}.owui-user .owui-bubble{background:var(--owui-user-bg,#111827);color:var(--owui-user-fg,#fff);border-color:var(--owui-user-bg,#111827)}.owui-error .owui-bubble{background:#fff1f2;border-color:#fecdd3;color:#9f1239}' +
			'.owui-streaming .owui-bubble:empty:after{content:"";display:inline-block;width:7px;height:7px;border-radius:999px;background:#9ca3af;animation:owuiPulse 1s infinite}.owui-form{display:flex;align-items:flex-end;gap:8px;padding:10px;border-top:1px solid #eef0f3;background:#fff}.owui-input{flex:1;min-width:0;min-height:42px;max-height:112px;resize:none;border:1px solid #d9dee7;border-radius:10px;padding:10px 11px;font-size:var(--owui-font-size,14px);line-height:1.35;outline:none;background:#fff;color:#111827}.owui-input:focus{border-color:var(--owui-primary,#111827);box-shadow:0 0 0 3px rgba(17,24,39,.08)}.owui-input:disabled{background:#f9fafb;color:#9ca3af;cursor:not-allowed}.owui-input::placeholder{color:#9ca3af}' +
			'.owui-send{position:relative;width:42px;height:42px;flex:0 0 42px;border:0;border-radius:10px;background:var(--owui-primary,#111827);color:var(--owui-on-primary,#fff);display:flex;align-items:center;justify-content:center;cursor:pointer}.owui-send:hover:not(:disabled){background:var(--owui-primary,#111827);filter:brightness(1.15)}.owui-send:focus-visible{outline:3px solid rgba(37,99,235,.25);outline-offset:1px}.owui-send:disabled{opacity:.55;cursor:not-allowed}.owui-send svg{width:19px;height:19px;fill:currentColor}.owui-send-spinner{position:absolute;width:18px;height:18px;border:2px solid rgba(255,255,255,.35);border-top-color:#fff;border-radius:999px;display:none;animation:owuiSpin .75s linear infinite}.owui-sending .owui-send-icon{opacity:0}.owui-sending .owui-send-spinner{display:block}.owui-launcher-img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;transition:opacity .16s ease}.owui-launcher-has-img .owui-launcher-chat{display:none}.owui-open .owui-launcher-img{opacity:0}' +
			'@keyframes owuiPulse{0%,100%{opacity:.35;transform:scale(.82)}50%{opacity:1;transform:scale(1)}}@keyframes owuiSpin{to{transform:rotate(360deg)}}' +
			'@media (max-width:480px){.owui-widget{right:12px;bottom:12px}.owui-left{left:12px;right:auto}.owui-panel{right:-4px;bottom:68px;width:calc(100vw - 24px);height:min(640px,calc(100vh - 92px));border-radius:10px}.owui-left .owui-panel{left:-4px;right:auto}.owui-launcher{width:54px;height:54px}.owui-title{max-width:calc(100vw - 150px)}}';
		document.head.appendChild(style);
	}
})();
