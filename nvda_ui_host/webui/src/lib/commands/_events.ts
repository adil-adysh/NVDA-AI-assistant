/**
 * Emit a UI event back to the Rust host (and then to Python).
 * Thin transport wrapper — no business logic.
 */

export function emitUiEvent(
	name: string,
	correlationId: string | null,
	payload: Record<string, unknown> = {},
): boolean {
	if (typeof (window as any).__sendHostEvent !== 'function') {
		console.warn('Unable to send host event; WebView bridge unavailable.');
		return false;
	}

	return (window as any).__sendHostEvent({
		schema: 'nvda.ui_host',
		version: 2,
		id: crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
		correlation_id: correlationId,
		source: 'web_ui',
		type: 'event',
		event: { name, payload },
	});
}
