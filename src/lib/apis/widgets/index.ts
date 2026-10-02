import { WEBUI_API_BASE_URL } from '$lib/constants';

export type ChatWidgetTheme = {
	primary_color: string;
	primary_text_color: string;
	header_background_color: string;
	header_text_color: string;
	background_color: string;
	assistant_bubble_color: string;
	assistant_text_color: string;
	user_bubble_color: string;
	user_text_color: string;
	font_family:
		| 'system'
		| 'arial'
		| 'verdana'
		| 'tahoma'
		| 'trebuchet'
		| 'georgia'
		| 'times'
		| 'courier';
	font_size: number;
	panel_radius: number;
	bubble_radius: number;
	panel_width: number;
	panel_height: number;
	launcher_shape: 'circle' | 'rounded' | 'square';
	launcher_size: number;
	launcher_icon: 'chat' | 'avatar';
	position: 'right' | 'left';
	offset_x: number;
	offset_y: number;
	avatar_url: string | null;
	header_title: string | null;
	header_subtitle: string | null;
	input_placeholder: string;
	show_status: boolean;
};

// Must match backend ChatWidgetTheme defaults exactly.
export const DEFAULT_WIDGET_THEME: ChatWidgetTheme = {
	primary_color: '#111827',
	primary_text_color: '#ffffff',
	header_background_color: '#ffffff',
	header_text_color: '#111827',
	background_color: '#fafafa',
	assistant_bubble_color: '#ffffff',
	assistant_text_color: '#111827',
	user_bubble_color: '#111827',
	user_text_color: '#ffffff',
	font_family: 'system',
	font_size: 14,
	panel_radius: 12,
	bubble_radius: 12,
	panel_width: 390,
	panel_height: 640,
	launcher_shape: 'circle',
	launcher_size: 58,
	launcher_icon: 'chat',
	position: 'right',
	offset_x: 20,
	offset_y: 20,
	avatar_url: null,
	header_title: null,
	header_subtitle: null,
	input_placeholder: 'Type a message',
	show_status: true
};

// Must match FONT_STACKS in backend/open_webui/static/widget/chat-widget.js exactly.
export const WIDGET_FONT_STACKS: Record<ChatWidgetTheme['font_family'], string> = {
	system: 'Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',
	arial: 'Arial,Helvetica,sans-serif',
	verdana: 'Verdana,Geneva,sans-serif',
	tahoma: 'Tahoma,Geneva,sans-serif',
	trebuchet: '"Trebuchet MS",Helvetica,sans-serif',
	georgia: 'Georgia,serif',
	times: '"Times New Roman",Times,serif',
	courier: '"Courier New",Courier,monospace'
};

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
	theme: ChatWidgetTheme;
	mcp_enabled: boolean;
	mcp_tool_ids: string[];
	folder_id?: string | null;
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
	theme: ChatWidgetTheme;
	mcp_enabled: boolean;
	mcp_tool_ids: string[];
};

export type ChatWidgetSession = {
	id: string;
	widget_id: string;
	visitor_id: string;
	title?: string | null;
	model_id?: string | null;
	message_count: number;
	chat_id?: string | null;
	chat_last_message_id?: string | null;
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
