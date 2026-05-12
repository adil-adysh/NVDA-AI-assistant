import {
	clearDisplayedContent,
	copyCurrentMarkdown,
	copyCurrentText,
	focusChatComposer,
	focusContentRegion,
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
	onAttachFile: () => void;
	onSubmit: (fileInputElement: HTMLInputElement | null) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isTextEntryTarget(target: EventTarget | null): boolean {
	return (
		target instanceof HTMLInputElement ||
		target instanceof HTMLTextAreaElement ||
		target instanceof HTMLSelectElement ||
		(target as HTMLElement | null)?.isContentEditable === true
	);
}

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
		if (event.key === 'Escape') {
			if (event.repeat) return;
			event.preventDefault();
			actions.onClose();
			return;
		}

		if (!(event.altKey && event.shiftKey) || event.repeat) return;

		const shortcut = event.key.toLowerCase();
		const activeTarget = document.activeElement;
		if (isTextEntryTarget(activeTarget) && shortcut !== 'i' && shortcut !== 's') {
			return;
		}

		switch (shortcut) {
			case 't':
				if (!hasToolbarAction('copy_text')) return;
				event.preventDefault();
				actions.onCopyText();
				break;
			case 'm':
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
