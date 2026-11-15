// MCP App host with opaque iframe origins and server-authorized RPC.
// Native sign-in stays offline; bridges may declare HTTPS resource/network origins.
export function mountApp(container, payload, callTool) {
	const frame = document.createElement('iframe');
	frame.title = payload.bridge ? 'MCP App' : 'Private Odoo sign-in';
	frame.setAttribute('sandbox', 'allow-scripts allow-forms');
	frame.referrerPolicy = 'no-referrer';
	frame.style.cssText =
		'display:block;width:100%;height:440px;border:0;border-radius:14px;background:transparent';
	function domains(key) {
		const values = payload.bridge && payload.csp && payload.csp[key];
		if (!Array.isArray(values)) return '';
		return values
			.slice(0, 32)
			.flatMap((value) => {
				try {
					const url = new URL(value);
					return url.protocol === 'https:' &&
						!url.username &&
						!url.password &&
						url.pathname === '/' &&
						!url.search &&
						!url.hash
						? [url.origin]
						: [];
				} catch {
					return [];
				}
			})
			.join(' ');
	}
	const resources = domains('resourceDomains');
	const connections = domains('connectDomains');
	const policy =
		"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'";
	const bridgePolicy = `default-src 'none'; script-src 'unsafe-inline' ${resources}; style-src 'unsafe-inline' ${resources}; img-src data: blob: ${resources}; font-src data: ${resources}; connect-src ${connections || "'none'"}; frame-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'`;
	// Policy must precede any app-controlled content, including scripts in <head>.
	frame.srcdoc =
		'<!doctype html><meta http-equiv="Content-Security-Policy" content="' +
		(payload.bridge ? bridgePolicy : policy) +
		'">' +
		payload.html;
	let disposed = false;
	let initialized = false;
	function send(message) {
		if (!disposed) frame.contentWindow.postMessage({ jsonrpc: '2.0', ...message }, '*');
	}
	async function receive(event) {
		if (disposed || event.source !== frame.contentWindow || event.origin !== 'null') return;
		const message = event.data;
		if (!message || message.jsonrpc !== '2.0' || typeof message.method !== 'string') return;
		const reply = (result) => send({ id: message.id, result });
		if (message.method === 'ui/initialize') {
			initialized = true;
			reply({
				protocolVersion: '2026-01-26',
				hostInfo: { name: 'OpenWebUI widget', version: '1.0.0' },
				hostCapabilities: { serverTools: {}, ...(payload.bridge ? { serverResources: {} } : {}) },
				hostContext: {
					theme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light',
					displayMode: 'inline'
				}
			});
		} else if (initialized && message.method === 'ui/notifications/initialized') {
			send({
				method: 'ui/notifications/tool-input',
				params: payload.toolInput || { arguments: {} }
			});
			if (payload.bridge)
				send({ method: 'ui/notifications/tool-result', params: payload.toolResult || {} });
		} else if (initialized && message.method === 'ui/notifications/size-changed') {
			const height = message.params && message.params.height;
			if (Number.isFinite(height)) frame.style.height = Math.min(650, Math.max(200, height)) + 'px';
		} else if (
			initialized &&
			(message.method === 'tools/call' ||
				(payload.bridge && ['resources/read', 'resources/list'].includes(message.method)))
		) {
			try {
				const result = await callTool(
					payload.bridge
						? { name: message.method, arguments: message.params || {} }
						: message.params
				);
				if (payload.bridge && result.error) send({ id: message.id, error: result.error });
				else reply(payload.bridge ? result.result : result);
			} catch {
				reply({
					isError: true,
					content: [{ type: 'text', text: 'The form could not connect. Please try again.' }]
				});
			}
		} else if (message.method === 'ping') reply({});
		else if (message.id !== undefined)
			send({ id: message.id, error: { code: -32601, message: 'This action is not available.' } });
	}
	window.addEventListener('message', receive);
	container.appendChild(frame);
	if (payload.bridge)
		return () => {
			disposed = true;
			window.removeEventListener('message', receive);
			frame.remove();
		};
	const cancel = document.createElement('button');
	cancel.type = 'button';
	cancel.textContent = 'Cancel sign-in';
	cancel.style.cssText =
		'display:block;margin:8px auto;padding:8px 14px;border:1px solid #cdd3dd;border-radius:8px;background:transparent;color:inherit;cursor:pointer';
	cancel.onclick = async () => {
		cancel.disabled = true;
		try {
			await callTool({ name: '__cancel__', arguments: {} });
		} catch {
			cancel.disabled = false;
			cancel.textContent = 'Try cancelling again';
		}
	};
	container.appendChild(cancel);
	return () => {
		disposed = true;
		window.removeEventListener('message', receive);
		frame.remove();
		cancel.remove();
	};
}
