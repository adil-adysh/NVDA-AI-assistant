import type { RenderDisplayPayload } from '../protocol-types';
import { announceResponse } from '../state.svelte';
import {
	setCopyBuffers,
	setDisplayBlocks,
	setPendingFocus,
	setViewMode,
	setWindowTitle,
	t,
} from '../state.svelte';
import {
	applyPresentationState,
	getMetadata,
	readPresentationValue,
	reportUiApplied,
	resolvePresentationFocusTarget,
} from './_shared';

// ---------------------------------------------------------------------------
// Display presentation resolution
// ---------------------------------------------------------------------------

const DISPLAY_VARIANTS = new Set(['standard', 'result_actions']);
const DISPLAY_TOOLBAR_ACTIONS = new Set(['copy_text', 'copy_markdown', 'clear', 'close']);

function resolveDisplayPresentation(
	payload: Record<string, unknown>,
	{ hasActions = false } = {},
): {
	variant: string;
	initialFocus: string | null;
	toolbarActions: string[];
	toolbarPlacement: string;
} {
	const metadata = getMetadata(payload);
	const rawPresentation =
		(payload?.display_presentation as Record<string, unknown>) ||
		(metadata.display_presentation as Record<string, unknown>) ||
		{};

	const variant =
		typeof rawPresentation?.variant === 'string' && DISPLAY_VARIANTS.has(rawPresentation.variant)
			? rawPresentation.variant
			: hasActions
				? 'result_actions'
				: 'standard';

	const toolbar =
		rawPresentation?.toolbar && typeof rawPresentation.toolbar === 'object'
			? (rawPresentation.toolbar as Record<string, unknown>)
			: {};
	const toolbarActions: string[] = Array.isArray(toolbar.actions)
		? (toolbar.actions as string[]).filter(
				(action) => typeof action === 'string' && DISPLAY_TOOLBAR_ACTIONS.has(action),
			)
		: [];

	const initialFocus = resolvePresentationFocusTarget(
		{
			...payload,
			metadata: {
				...metadata,
				focus_target: rawPresentation?.initial_focus ?? metadata.focus_target,
			},
		},
		hasActions ? 'primary_action' : 'content',
	);

	return {
		variant,
		initialFocus,
		toolbarActions,
		toolbarPlacement: toolbar.placement === 'after_content' ? 'after_content' : 'after_content',
	};
}

function announceDisplayBlocks(blocks: { type: string; text?: string }[]): void {
	const text = blocks
		.filter((b) => typeof b.text === 'string')
		.map((b) => b.text!)
		.join('\n');
	if (text) announceResponse(text);
}

// ---------------------------------------------------------------------------
// Command handler
// ---------------------------------------------------------------------------

export function renderDisplay(commandId: string, payload: RenderDisplayPayload): void {
	const actions = readPresentationValue(payload, 'actions', []);
	const thinkingTrace = readPresentationValue<string>(payload, 'thinking_trace', null);
	const thinkingSummary = readPresentationValue<string>(payload, 'thinking_summary', null);
	const thinkingCollapsed =
		readPresentationValue<boolean>(payload, 'thinking_visible_by_default', true) === false;

	const normalizedActions = Array.isArray(actions) ? actions : [];
	const displayPresentation = resolveDisplayPresentation(
		payload as Record<string, unknown>,
		{ hasActions: normalizedActions.length > 0 },
	);

	const blocks: { type: string; html?: string; text?: string; summary?: string; collapsed?: boolean }[] = [];

	if (payload.output_html) {
		blocks.push({ type: 'html', html: payload.output_html });
	} else {
		blocks.push({
			type: 'text',
			text: payload.output_text || payload.message || t('no_content', 'No content available.'),
		});
	}

	if (thinkingTrace) {
		blocks.push({
			type: 'thinking',
			text: thinkingTrace,
			summary: thinkingSummary || t('thinking_label', 'Thinking'),
			collapsed: thinkingCollapsed,
		});
	}

	setDisplayBlocks(blocks, normalizedActions, displayPresentation);
	announceDisplayBlocks(blocks);
	applyPresentationState(payload as Record<string, unknown>, {
		controlsVisible: true,
		interactionMode: 'display',
	});
	setViewMode('display');
	if (payload.title) setWindowTitle(payload.title);
	setPendingFocus(displayPresentation.initialFocus);
	setCopyBuffers(
		payload.copy_text || payload.output_text || '',
		payload.copy_markdown || '',
	);

	reportUiApplied(commandId);
}
