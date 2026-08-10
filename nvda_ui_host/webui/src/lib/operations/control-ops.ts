import type { PresentationMetadata } from '../protocol-types';
import { setConversationSummaries } from './view-ops';
import {
	appState,
	clearControlPending,
	setControlsVisible,
	setInteractionMode,
} from '../state.svelte';
import { emitUiEvent } from '../commands/_events';

// ---------------------------------------------------------------------------
// Presentation helpers — shared across _shared.ts
// ---------------------------------------------------------------------------

export function getMetadata(payload: Record<string, unknown>): PresentationMetadata {
	return (payload?.metadata as PresentationMetadata) || {};
}

export function readPresentationValue<T>(
	payload: Record<string, unknown>,
	key: string,
	fallback?: T,
): T | undefined {
	const metadata = getMetadata(payload);
	return (payload?.[key] ?? (metadata as Record<string, unknown>)[key] ?? fallback) as T | undefined;
}

// ---------------------------------------------------------------------------
// Control state (providers, models, think mode, chat enabled)
// ---------------------------------------------------------------------------

export function updateControlState(payload: Record<string, unknown>): void {
	const providerState = readPresentationValue<Record<string, unknown>>(payload, 'provider_state') || {};
	const providerStatus = readPresentationValue<Record<string, unknown>>(payload, 'provider_status') || {};
	const availableProviders = readPresentationValue<(string | { id?: string; value?: string; label?: string })[]>(payload, 'available_providers');
	const availableModels = readPresentationValue<string[]>(payload, 'available_models');
	const thinkEnabled = readPresentationValue<boolean>(payload, 'think_enabled');
	const chatEnabled = readPresentationValue<boolean>(payload, 'chat_enabled');

	console.log(`[control-ops] updateControlState: availProviders=${availableProviders?.length ?? 'undefined'} availModels=${availableModels?.length ?? 'undefined'} provider=${(providerState as any)?.provider ?? 'undefined'} think=${thinkEnabled} chat=${chatEnabled}`);

	if (Array.isArray(availableProviders)) appState.control.availableProviders = availableProviders;
	if (Array.isArray(availableModels)) appState.control.availableModels = availableModels;
	const availableModelLabels = readPresentationValue<Record<string, string>>(payload, 'available_model_labels');
	if (availableModelLabels && typeof availableModelLabels === 'object') {
		appState.control.availableModelLabels = availableModelLabels;
	}
	if (typeof providerState?.provider === 'string') {
		appState.control.selectedProvider = providerState.provider;
		appState.control.providerDraft = providerState.provider;
	}
	if (typeof providerState?.model === 'string') {
		appState.control.selectedModel = providerState.model;
		appState.control.modelDraft = providerState.model;
	}
	if (typeof thinkEnabled === 'boolean') {
		appState.control.thinkEnabled = thinkEnabled;
		appState.control.thinkDraft = thinkEnabled;
	}
	if (providerStatus && typeof providerStatus === 'object') {
		appState.control.providerStatus = {
			state: typeof providerStatus.state === 'string' ? providerStatus.state : 'ready',
			reason: typeof providerStatus.reason === 'string' ? providerStatus.reason : null,
			canInfer: providerStatus.can_infer !== false,
			canListModels: providerStatus.can_list_models !== false,
		};
	}
	if (typeof chatEnabled === 'boolean') {
		appState.control.chatEnabled = chatEnabled;
	} else if (providerStatus && typeof providerStatus === 'object' && typeof providerStatus.can_infer === 'boolean') {
		appState.control.chatEnabled = providerStatus.can_infer as boolean;
	}

	// Conversation summaries often ride along with control state
	const summaries = readPresentationValue(payload, 'conversation_summaries');
	if (Array.isArray(summaries)) {
		setConversationSummaries(summaries);
	}

	// Presentation state also rides along
	const controlsVisible = readPresentationValue<boolean>(payload, 'controls_visible');
	if (typeof controlsVisible === 'boolean') setControlsVisible(controlsVisible);

	const interactionMode = readPresentationValue<string>(payload, 'interaction_mode');
	if (typeof interactionMode === 'string' && interactionMode.trim()) {
		setInteractionMode(interactionMode.trim());
	}

	if (
		(providerStatus && typeof providerStatus === 'object') ||
		Array.isArray(availableProviders) ||
		Array.isArray(availableModels) ||
		typeof providerState?.provider === 'string' ||
		typeof providerState?.model === 'string' ||
		typeof thinkEnabled === 'boolean' ||
		typeof chatEnabled === 'boolean'
	) {
		clearControlPending();
	}
}
