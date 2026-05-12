import type { SyncSessionPayload } from '../protocol-types';
import {
	setActiveConversationId,
	setConversationSummaries,
} from '../operations/view-ops';
import {
	applyPresentationState,
	readPresentationValue,
	reportUiApplied,
} from './_shared';

export function syncSession(_commandId: string, payload: SyncSessionPayload): void {
	applyPresentationState(payload as Record<string, unknown>, {
		controlsVisible: true,
		interactionMode: 'chat',
	});

	if (payload.conversation_id || payload.conversation_id === null) {
		setActiveConversationId(payload.conversation_id ?? null);
	}

	const summaries = readPresentationValue(payload, 'conversation_summaries');
	if (Array.isArray(summaries)) setConversationSummaries(summaries);

	reportUiApplied(_commandId);
}
