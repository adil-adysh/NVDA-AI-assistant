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
import { tick } from 'svelte';

let focusGeneration = 0;

export function invalidatePresentationFocus(): void {
	focusGeneration++;
	appState.view.pendingFocus = null;
}

export async function focusPresentationElement(element: HTMLElement): Promise<void> {
	const generation = ++focusGeneration;
	await tick();
	if (generation !== focusGeneration || !element.isConnected) return;
	element.focus({ preventScroll: false });
}

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

/** Incremental events belong to the displayed conversation and never select it. */
export function isCurrentChatEvent(payload: Record<string, unknown>): boolean {
	const conversationId = payload.conversation_id;
	if (!appState.chat.active || (conversationId && conversationId !== appState.chat.conversationId)) return false;
	const metadata = getMetadata(payload);
	const requestId = payload.request_id ?? metadata.request_id;
	const latestRequestId = appState.chat.latestRequestId ?? appState.chat.requestId;
	return !requestId || !latestRequestId || requestId === latestRequestId;
}

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

export async function reportUiApplied(commandId: string): Promise<void> {
	// The first flush creates targets and runs focus effects; the second
	// lets their delayed element.focus() complete before native MoveFocus.
	await tick();
	await tick();
	emitUiEvent('ui_applied', commandId);
}

export function reportUiFailure(commandId: string, reason: string): void {
	emitUiEvent('ui_failed', commandId, { reason });
}
