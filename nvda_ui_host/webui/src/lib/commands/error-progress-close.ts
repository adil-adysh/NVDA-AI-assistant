import type {
	ShowErrorPayload,
	UpdateProgressPayload,
	CloseWindowPayload,
} from '../protocol-types';
import {
	appState,
	setStatus,
	setDisplayBlocks,
    setViewMode,
    setWindowTitle,
    showDisplayText,
    t,
} from '../state.svelte';
import {
	applyPresentationState,
	getHostStatusMessage,
	readPresentationValue,
	reportUiApplied,
} from './_shared';

// ---------------------------------------------------------------------------
// show_error
// ---------------------------------------------------------------------------

export function showError(commandId: string, payload: ShowErrorPayload): void {
	const msg =
		payload.error_message ||
		payload.message ||
		(payload.details as string | undefined) ||
		getHostStatusMessage(payload as Record<string, unknown>);
	setDisplayBlocks(
		[
			{
				type: 'error',
				text: msg,
				summary: payload.title || t('error_prefix', 'Error'),
			},
		],
		[],
	);
	setViewMode('display', 'content');
	if (payload.title) setWindowTitle(payload.title);
	setStatus(msg, true);
	applyPresentationState(payload as Record<string, unknown>, {
		controlsVisible: false,
		interactionMode: 'display',
	});
	reportUiApplied(commandId);
}

// ---------------------------------------------------------------------------
// update_progress
// ---------------------------------------------------------------------------

export function updateProgress(commandId: string, payload: UpdateProgressPayload): void {
	const msg = payload.message || getHostStatusMessage(payload as Record<string, unknown>);
	showDisplayText(msg, 'status');
	if (payload.title) setWindowTitle(payload.title);
	setStatus(msg, false);
	applyPresentationState(payload as Record<string, unknown>);
	reportUiApplied(commandId);
}

// ---------------------------------------------------------------------------
// close_window
// ---------------------------------------------------------------------------

export function closeWindow(commandId: string, _payload: CloseWindowPayload): void {
	appState.controlsVisible = false;
	setViewMode('display', 'status');
	reportUiApplied(commandId);
}
