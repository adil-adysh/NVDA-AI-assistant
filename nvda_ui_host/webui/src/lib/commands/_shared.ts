/**
 * Shared helpers for command modules.
 *
 * - Presentation metadata resolution
 * - Chat envelope updates (shared across chat-history and chat-streaming)
 * - Event emission
 */

import { setActiveConversationId, setConversationSummaries } from '../operations/view-ops';
import {
	appState,
	setControlsVisible,
	setInteractionMode,
} from '../state.svelte';
import { emitUiEvent } from './_events';
import { readPresentationValue, getMetadata } from '../operations/control-ops';

// Re-export for convenience
export { getMetadata, readPresentationValue };

// ---------------------------------------------------------------------------
// Presentation state
// ---------------------------------------------------------------------------

export function applyPresentationState(
	payload: Record<string, unknown>,
	defaults: { controlsVisible?: boolean; interactionMode?: string } = {},
): void {
	const controlsVisible = readPresentationValue<boolean>(payload, 'controls_visible', defaults.controlsVisible);
	if (typeof controlsVisible === 'boolean') setControlsVisible(controlsVisible);

	const interactionMode = readPresentationValue<string>(payload, 'interaction_mode', defaults.interactionMode);
	if (typeof interactionMode === 'string' && interactionMode.trim()) {
		setInteractionMode(interactionMode.trim());
	}
}

export function resolvePresentationFocusTarget(
	payload: Record<string, unknown>,
	fallback: string | null = null,
): string | null {
	const target = readPresentationValue<string>(payload, 'focus_target', fallback ?? undefined);
	if (typeof target !== 'string' || !target.trim()) return null;
	return target.trim();
}

export function getHostStatusMessage(payload: Record<string, unknown>): string {
	const msg = readPresentationValue<string>(payload, 'status_message');
	return typeof msg === 'string' && msg.trim() ? msg.trim() : '';
}

// ---------------------------------------------------------------------------
// Chat envelope (shared by chat-history and chat-streaming)
// ---------------------------------------------------------------------------

export function updateChatEnvelope(payload: Record<string, unknown>): void {
	appState.chat.active = true;
	if (payload.conversation_id) {
		setActiveConversationId(payload.conversation_id as string);
	}
	if (payload.command_id) {
		appState.chat.commandId = payload.command_id as string;
	}
	const summaries = readPresentationValue(payload, 'conversation_summaries');
	if (Array.isArray(summaries)) setConversationSummaries(summaries);
}

// ---------------------------------------------------------------------------
// Event reporting
// ---------------------------------------------------------------------------

export function reportUiApplied(commandId: string): void {
	emitUiEvent('ui_applied', commandId);
}

export function reportUiFailure(commandId: string, reason: string): void {
	emitUiEvent('ui_failed', commandId, { reason });
}
