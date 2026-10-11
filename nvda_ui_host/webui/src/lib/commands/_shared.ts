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
	announceResponse,
} from '../state.svelte';
import { emitUiEvent } from './_events';
import { readPresentationValue, getMetadata } from '../operations/control-ops';
import { tick } from 'svelte';

let focusGeneration = 0;
let cancelAnnouncement: (() => void) | null = null;

export function invalidatePresentationFocus(): void {
	focusGeneration++;
	cancelAnnouncement?.();
	appState.view.pendingAnnouncement = null;
	appState.view.pendingFocus = null;
}

/** Wait for keyboard focus, including native WebView focus, before reading. */
export function announceAfterKeyboardFocus(text: string, element: HTMLElement): void {
	cancelAnnouncement?.();
	const generation = focusGeneration;
	let frame = 0;
	let done = false;
	const cleanup = () => {
		done = true;
		window.removeEventListener('focus', schedule, true);
		cancelAnimationFrame(frame);
	};
	const deliver = () => {
		if (done || generation !== focusGeneration || !element.isConnected) { cleanup(); return; }
		if (!document.hasFocus() || document.activeElement !== element) return;
		cleanup();
		announceResponse(text);
	};
	function schedule() {
		cancelAnimationFrame(frame);
		frame = requestAnimationFrame(() => { frame = requestAnimationFrame(deliver); });
	}
	cancelAnnouncement = cleanup;
	window.addEventListener('focus', schedule, true);
	schedule();
}

export async function focusPresentationElement(element: HTMLElement): Promise<boolean> {
	cancelAnnouncement?.();
	const generation = ++focusGeneration;
	await tick();
	if (generation !== focusGeneration || !element.isConnected) return false;
	element.focus({ preventScroll: false });
	return true;
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
