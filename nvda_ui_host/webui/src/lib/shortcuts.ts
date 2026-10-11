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
	fileInputElement: HTMLInputElement | null | (() => HTMLInputElement | null),
): () => void {
	let composing = false;
	let expandedSelect: EventTarget | null = null;
	let escapePressed = false;
	let lastEscapeAt = 0;
	let lastEscapeResult: boolean | null = null;
	const hostWindow = window as Window & { __dismissHostOnEscape?: () => boolean };
	const isSelect = (target: EventTarget | null | undefined): boolean => {
		const select = target as HTMLSelectElement | null;
		return select?.tagName === 'SELECT' && !select.multiple && Number(select.size || 0) <= 1;
	};

	function dismissOnEscape(fromDom = false, event?: KeyboardEvent): boolean {
		const recent = Date.now() - lastEscapeAt < 250;
		if (lastEscapeResult !== null && recent && (!fromDom || escapePressed)) {
			return lastEscapeResult;
		}
		escapePressed = true;
		lastEscapeAt = Date.now();
		lastEscapeResult = !(composing || event?.isComposing || event?.defaultPrevented || expandedSelect);
		if (expandedSelect) expandedSelect = null;
		if (lastEscapeResult) actions.onClose();
		return lastEscapeResult;
	}
	const nativeEscape = () => dismissOnEscape();
	hostWindow.__dismissHostOnEscape = nativeEscape;
	const compositionStart = () => { composing = true; };
	const compositionEnd = () => { composing = false; };
	const pointerDown = (event: Event) => { expandedSelect = isSelect(event.target) ? event.target : null; };
	const resetSelect = () => { expandedSelect = null; };
	const keyUp = (event: KeyboardEvent) => { if (event.key === 'Escape') escapePressed = false; };

	function handler(event: KeyboardEvent): void {
		if (event.repeat) return;

		// Escape: close / dismiss
		if (event.key === 'Escape') {
			if (dismissOnEscape(true, event)) event.preventDefault();
			return;
		}
		if (event.defaultPrevented || event.isComposing || composing) return;
		if (isSelect(event.target) && (event.key === 'F4' || event.key === ' ' || event.key === 'Enter'
			|| (event.altKey && event.key === 'ArrowDown'))) expandedSelect = event.target;

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
				actions.onSubmit(typeof fileInputElement === 'function' ? fileInputElement() : fileInputElement);
				break;
			default:
				break;
		}
	}

	window.addEventListener('keydown', handler);
	window.addEventListener('keyup', keyUp);
	window.addEventListener('compositionstart', compositionStart);
	window.addEventListener('compositionend', compositionEnd);
	window.addEventListener('pointerdown', pointerDown);
	window.addEventListener('change', resetSelect);
	window.addEventListener('focusout', resetSelect);
	return () => {
		window.removeEventListener('keydown', handler);
		window.removeEventListener('keyup', keyUp);
		window.removeEventListener('compositionstart', compositionStart);
		window.removeEventListener('compositionend', compositionEnd);
		window.removeEventListener('pointerdown', pointerDown);
		window.removeEventListener('change', resetSelect);
		window.removeEventListener('focusout', resetSelect);
		if (hostWindow.__dismissHostOnEscape === nativeEscape) delete hostWindow.__dismissHostOnEscape;
	};
}
