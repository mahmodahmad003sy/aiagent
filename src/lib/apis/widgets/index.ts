import { WEBUI_API_BASE_URL } from '$lib/constants';

export type ChatWidget = {
	id: string;
	user_id: string;
	name: string;
	model_id: string;
	system_prompt?: string | null;
	welcome_message?: string | null;
	token: string;
	enabled: boolean;
	allowed_domains?: string[] | null;
	created_at: number;
	updated_at: number;
};

export type ChatWidgetForm = {
	name: string;
	model_id: string;
	system_prompt?: string | null;
	welcome_message?: string | null;
	enabled: boolean;
	allowed_domains: string[];
};

export type ChatWidgetSession = {
	id: string;
	widget_id: string;
	visitor_id: string;
	title?: string | null;
	model_id?: string | null;
	message_count: number;
	created_at: number;
	updated_at: number;
	last_activity_at: number;
};

export type ChatWidgetMessage = {
	id: string;
	session_id: string;
	widget_id: string;
	role: string;
	content?: unknown;
	model_id?: string | null;
	done: boolean;
	error?: Record<string, unknown> | string | null;
	usage?: Record<string, unknown> | null;
	created_at: number;
	updated_at: number;
};

const parseError = async (res: Response) => {
	try {
		const json = await res.json();
		return json?.detail ?? json;
	} catch {
		return res.statusText;
	}
};

export const getChatWidgets = async (token: string = ''): Promise<ChatWidget[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/widgets`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await parseError(res);
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const createChatWidget = async (
	token: string = '',
	widget: ChatWidgetForm
): Promise<ChatWidget> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/widgets`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(widget)
	})
		.then(async (res) => {
			if (!res.ok) throw await parseError(res);
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const updateChatWidget = async (
	token: string = '',
	id: string,
	widget: Partial<ChatWidgetForm>
): Promise<ChatWidget> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/widgets/${encodeURIComponent(id)}`, {
		method: 'PUT',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(widget)
	})
		.then(async (res) => {
			if (!res.ok) throw await parseError(res);
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const deleteChatWidget = async (token: string = '', id: string): Promise<boolean> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/widgets/${encodeURIComponent(id)}`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await parseError(res);
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const rotateChatWidgetToken = async (
	token: string = '',
	id: string
): Promise<ChatWidget> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/widgets/${encodeURIComponent(id)}/rotate-token`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await parseError(res);
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const getChatWidgetSessions = async (
	token: string = '',
	id: string,
	skip = 0,
	limit = 50
): Promise<ChatWidgetSession[]> => {
	let error = null;

	const params = new URLSearchParams({
		skip: `${skip}`,
		limit: `${limit}`
	});

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/widgets/${encodeURIComponent(id)}/sessions?${params.toString()}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await parseError(res);
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const getChatWidgetSessionMessages = async (
	token: string = '',
	widgetId: string,
	sessionId: string
): Promise<ChatWidgetMessage[]> => {
	let error = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/widgets/${encodeURIComponent(widgetId)}/sessions/${encodeURIComponent(
			sessionId
		)}/messages`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await parseError(res);
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const deleteChatWidgetSession = async (
	token: string = '',
	widgetId: string,
	sessionId: string
): Promise<boolean> => {
	let error = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/widgets/${encodeURIComponent(widgetId)}/sessions/${encodeURIComponent(
			sessionId
		)}`,
		{
			method: 'DELETE',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await parseError(res);
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) throw error;
	return res;
};
