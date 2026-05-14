import {
	clearDisplayedContent,
	copyCurrentMarkdown,
	copyCurrentText,
	focusChatComposer,
	focusContentRegion,
	focusModelSelect,
	focusProviderSelect,
	requestCloseHost,
	submitChatMessage,
} from './actions';
import { appState } from './state.svelte';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ShortcutActions {
	onClose: () => void;
	onCopyText: () => void;
	onCopyMarkdown: () => void;
	onClear: () => void;
	onFocusContent: () => void;
	onFocusComposer: () => void;
	onFocusProvider: () => void;
	onFocusModel: () => void;
	onAttachFile: () => void;
	onSubmit: (fileInputElement: HTMLInputElement | null) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function hasToolbarAction(actionId: string): boolean {
	return (
		Array.isArray(appState.display.toolbarActions) &&
		appState.display.toolbarActions.includes(actionId)
	);
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

export function registerGlobalShortcuts(
	actions: ShortcutActions,
	fileInputElement: HTMLInputElement | null,
): () => void {
	function handler(event: KeyboardEvent): void {
		if (event.repeat) return;

		// Escape: close / dismiss
		if (event.key === 'Escape') {
			event.preventDefault();
			actions.onClose();
			return;
		}

		// All shortcuts use Alt+Key only — no Shift, Ctrl, or Meta modifiers.
		if (!event.altKey || event.shiftKey || event.ctrlKey || event.metaKey) return;

		const shortcut = event.key.toLowerCase();

		switch (shortcut) {
			case 't':
				if (!hasToolbarAction('copy_text')) return;
				event.preventDefault();
				actions.onCopyText();
				break;
			case 'k':
				if (!hasToolbarAction('copy_markdown')) return;
				event.preventDefault();
				actions.onCopyMarkdown();
				break;
			case 'r':
				if (!hasToolbarAction('clear')) return;
				event.preventDefault();
				actions.onClear();
				break;
			case 'l':
				event.preventDefault();
				actions.onFocusContent();
				break;
			case 'i':
				if (appState.view.mode !== 'chat') return;
				event.preventDefault();
				actions.onFocusComposer();
				break;
			case 'p':
				event.preventDefault();
				actions.onFocusProvider();
				break;
			case 'm':
				event.preventDefault();
				actions.onFocusModel();
				break;
			case 'a':
				if (appState.view.mode !== 'chat') return;
				event.preventDefault();
				actions.onAttachFile();
				break;
			case 's':
				if (appState.view.mode !== 'chat') return;
				event.preventDefault();
				actions.onSubmit(fileInputElement);
				break;
			default:
				break;
		}
	}

	window.addEventListener('keydown', handler);
	return () => window.removeEventListener('keydown', handler);
}
