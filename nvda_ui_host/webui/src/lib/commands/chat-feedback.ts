import { appState, announceResponse, setStatus, t } from '../state.svelte';
import { readPresentationValue } from './_shared';

/** One completion path for streamed, non-streamed, stopped and failed turns. */
export function completeChatTurn(messageId: string, payload: Record<string, unknown>): void {
	if (appState.chat.latestCompletedMessageId === messageId) return;
	appState.chat.processing = false;
	appState.chat.requestId = null;
	appState.chat.stopping = false;
	appState.chat.latestCompletedMessageId = messageId;
	const cancelled = readPresentationValue(payload, 'cancelled') === true;
	const failed = readPresentationValue(payload, 'failed') === true;
	const status = cancelled ? t('response_stopped_status', 'Response stopped.')
		: failed ? t('response_failed_status', 'Response failed. Review the error and retry.')
		: t('response_ready_status', 'Response ready.');
	setStatus(status, false);
	const speech = readPresentationValue<string>(payload, 'announcement_text');
	if (!cancelled && !failed && typeof speech === 'string' && speech.trim()) {
		// App delivers this only after DOM and native keyboard focus settle.
		appState.view.pendingAnnouncement = { text: speech, messageId };
	} else if (appState.chat.statusAnnouncements !== false) {
		announceResponse(status);
	}
}
