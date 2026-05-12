import type { ContentBlock, ResultAction, ConversationSummary } from './protocol-types';
import { Transcript } from './transcript.svelte';

// ---------------------------------------------------------------------------
// Reactive application state
// ---------------------------------------------------------------------------

function publishAnnouncement(channel: 'statusAnnouncement' | 'responseAnnouncement', message: string) {
	const nextId = appState.accessibility.nextAnnouncementId + 1;
	appState.accessibility.nextAnnouncementId = nextId;
	appState.accessibility[channel] = { id: nextId, message };
}

export const ConversationSelectionState = {
	None: 'none',
	SummariesAvailable: 'summaries_available',
	SelectedEmpty: 'selected_empty',
	SelectedLoaded: 'selected_loaded',
} as const;

export type ConversationSelectionStateValue =
	(typeof ConversationSelectionState)[keyof typeof ConversationSelectionState];

export const appState = $state({
	currentCommandId: null as string | null,
	title: 'NVDA UI Host',
	statusMessage: '',
	controlsVisible: true,

	accessibility: {
		nextAnnouncementId: 0,
		statusAnnouncement: null as { id: number; message: string } | null,
		responseAnnouncement: null as { id: number; message: string } | null,
	},

	control: {
		availableProviders: [] as (string | { id?: string; value?: string; label?: string })[],
		availableModels: [] as string[],
		selectedProvider: '',
		selectedModel: '',
		thinkEnabled: false,
		providerDraft: '',
		modelDraft: '',
		thinkDraft: false,
		chatEnabled: true,
		providerStatus: {
			state: 'ready' as string,
			reason: null as string | null,
			canInfer: true,
			canListModels: true,
		},
		pendingChange: null as string | null,
	},

	localizedStrings: {} as Record<string, string>,

	chat: {
		active: false,
		commandId: null as string | null,
		conversationId: null as string | null,
		conversationSelectionState: ConversationSelectionState.None as ConversationSelectionStateValue,
		conversations: [] as ConversationSummary[],
		transcript: new Transcript(),
		attachments: [] as { id: string; name?: string; kind?: string; image_base64?: string; mime_type?: string }[],
		composerText: '',
	},

	display: {
		blocks: [] as ContentBlock[],
		actions: [] as ResultAction[],
		variant: 'standard' as 'standard' | 'result_actions',
		toolbarActions: [] as string[],
		toolbarPlacement: 'after_content' as string,
	},

	view: {
		mode: 'display' as 'display' | 'chat',
		pendingFocus: null as string | null,
		interactionMode: 'display' as string,
	},

	copy: {
		text: '',
		markdown: '',
	},
});

// ---------------------------------------------------------------------------
// Localization
// ---------------------------------------------------------------------------

export function t(key: string, fallback = ''): string {
	return appState.localizedStrings[key] || fallback;
}

export function mergeLocalizedStrings(strings: Record<string, string>): void {
	Object.assign(appState.localizedStrings, strings);
}

// ---------------------------------------------------------------------------
// Simple setters (single-field mutations)
// ---------------------------------------------------------------------------

export function setStatus(message: string, announce = false): void {
	appState.statusMessage = message;
	if (announce) {
		publishAnnouncement('statusAnnouncement', message);
	}
}

export function announceResponse(message: string): void {
	if (typeof message !== 'string' || !message.trim()) return;
	publishAnnouncement('responseAnnouncement', message.trim());
}

export function setPendingFocus(target: string | null): void {
	appState.view.pendingFocus = target;
}

export function setViewMode(mode: 'display' | 'chat', pendingFocus: string | null = null): void {
	appState.view.mode = mode;
	if (pendingFocus) {
		appState.view.pendingFocus = pendingFocus;
	}
}

export function setInteractionMode(mode: string): void {
	appState.view.interactionMode = mode || 'display';
}

export function setCopyBuffers(text = '', markdown = ''): void {
	appState.copy.text = text;
	appState.copy.markdown = markdown;
}

export function setDisplayBlocks(
	blocks: ContentBlock[] = [],
	actions: ResultAction[] = [],
	presentation: { variant?: string; toolbarActions?: string[]; toolbarPlacement?: string } = {},
): void {
	appState.display.blocks = blocks;
	appState.display.actions = actions;
	appState.display.variant = (presentation.variant as 'standard' | 'result_actions') || 'standard';
	appState.display.toolbarActions = Array.isArray(presentation.toolbarActions) ? presentation.toolbarActions : [];
	appState.display.toolbarPlacement = presentation.toolbarPlacement || 'after_content';
}

export function setWindowTitle(title: string): void {
	appState.title = title || 'NVDA UI Host';
}

export function setControlPending(change: string | null): void {
	appState.control.pendingChange = change;
}

export function clearControlPending(): void {
	appState.control.pendingChange = null;
}

export function setControlsVisible(visible: boolean): void {
	appState.controlsVisible = visible;
}

export function showDisplayText(text: string, focusTarget: string | null = null): void {
	setDisplayBlocks(text ? [{ type: 'text', text }] : [], []);
	setViewMode('display', focusTarget);
}
