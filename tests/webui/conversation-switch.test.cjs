const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const ts = require(path.join(root, 'nvda_ui_host/node_modules/typescript'));

function loadFlow() {
	const state = {
		chat: {
			active: true, conversationId: 'B', commandId: 'open-B', processing: true,
			conversations: [{ id: 'A' }, { id: 'B' }],
			transcript: {
				count: 1, clear() { this.count = 0; },
				applyDelta() { return false; }, abortStream() {},
			},
		}, view: {}, display: {},
	};
	const stateModule = {
		appState: state, ConversationSelectionState: {}, setViewMode(mode, focus) { state.view.mode = mode; if (focus) state.view.pendingFocus = focus; },
		setPendingFocus(focus) { state.view.pendingFocus = focus; },
		announceResponse(text) { state.announcement = text; }, setStatus(text) { state.status = text; }, t(key, fallback) { return fallback; },
		setCopyBuffers() {}, setControlsVisible() {}, setInteractionMode() {},
	};
	function load(file, modules) {
		const exports = {};
		const source = fs.readFileSync(path.join(root, 'nvda_ui_host/webui/src/lib', file), 'utf8');
		vm.runInNewContext(ts.transpileModule(source, {
			compilerOptions: { module: ts.ModuleKind.CommonJS },
		}).outputText, { exports, require: name => modules[name], console, $state: value => value });
		return exports;
	}
	const views = load('operations/view-ops.ts', { '../state.svelte': stateModule });
	const { Transcript } = load('transcript.svelte.ts', {});
	state.chat.transcript = new Transcript();
	state.chat.transcript.beginStream('assistant-B', 'stream-B', 'assistant', []);
	const shared = load('commands/_shared.ts', {
		'../operations/view-ops': views, '../state.svelte': stateModule,
		'./_events': { emitUiEvent() {} }, 'svelte': { tick: () => Promise.resolve() },
		'../operations/control-ops': { getMetadata: payload => payload.metadata || {}, readPresentationValue: (payload, key, fallback) => payload[key] ?? payload.metadata?.[key] ?? fallback },
	});
	const streams = load('commands/chat-streaming.ts', {
		'../state.svelte': stateModule, '../content': { summarizeForAnnouncement: () => 'partial' }, './_shared': shared,
	});
	const history = load('commands/chat-history.ts', {
		'../state.svelte': stateModule, '../operations/view-ops': views, './_shared': shared,
	});
	const opening = load('commands/open-chat.ts', {
		'../state.svelte': stateModule, '../operations/view-ops': views, './_shared': shared,
		'../attachments': { addInitialImageAttachment() {} },
	});
	return { state, views, streams, history, opening };
}

test('reopening hidden chat preserves its unsent draft and active request', () => {
	const { state, opening } = loadFlow();
	state.chat.composerText = 'unsent draft'; state.chat.requestId = 'request-B';
	opening.openChat('reopen-B', { conversation_id: 'B', metadata: { preserve_conversation: true }, initial_text: '' });
	assert.equal(state.chat.composerText, 'unsent draft');
	assert.equal(state.chat.requestId, 'request-B');
	assert.equal(state.chat.processing, true);
});

test('preservation cannot retain a different conversation transcript', () => {
	const { state, opening } = loadFlow();
	opening.openChat('open-A', { conversation_id: 'A', metadata: { preserve_conversation: true } });
	assert.equal(state.chat.transcript.count, 0);
	assert.equal(state.chat.processing, false);
});

test('completed answer requests content keyboard focus', () => {
	const { state, streams } = loadFlow();
	streams.endChatStream('end-B', { conversation_id: 'B', message_id: 'assistant-B', stream_id: 'stream-B', metadata: { focus_target: 'content' } });
	assert.equal(state.view.pendingFocus, 'content');
	assert.equal(state.chat.processing, false);
});

test('stopped answer keeps its partial content without requesting focus', () => {
	const { state, streams } = loadFlow();
	streams.endChatStream('end-B', { conversation_id: 'B', message_id: 'assistant-B', stream_id: 'stream-B', content: [{ type: 'text', text: 'partial\n\n[Stopped]' }], metadata: { cancelled: true, attention_policy: 'none' } });
	assert.equal(state.view.pendingFocus, undefined);
	assert.equal(state.chat.transcript.findById('assistant-B').content[0].text, 'partial\n\n[Stopped]');
	assert.equal(state.status, 'Response stopped.');
});

test('resetting a conversation releases the old turn processing state', () => {
	const { state, views } = loadFlow();
	views.resetChatState();
	assert.equal(state.chat.processing, false);
});

test('a rejected late delta cannot select the previous conversation', () => {
	const { state, streams } = loadFlow();
	streams.applyChatStreamDelta('delta-A', {
		conversation_id: 'A', message_id: 'assistant-A', stream_id: 'stream-A', delta: 'late',
	});
	assert.equal(state.chat.conversationId, 'B');
});

test('old turn cancellation cannot select A or release an active B turn', () => {
	const { state, streams } = loadFlow();
	streams.abortChatStream('abort-A', {
		conversation_id: 'A', message_id: 'assistant-A', stream_id: 'stream-A',
	});
	assert.equal(state.chat.conversationId, 'B');
	assert.equal(state.chat.processing, true);
});

test('an older request in the same conversation cannot finish a newer request', () => {
	const { state, streams } = loadFlow();
	state.chat.requestId = 'new-request-B';
	streams.endChatStream('end-old-B', {
		conversation_id: 'B', message_id: 'assistant-B', stream_id: 'stream-B',
		metadata: { request_id: 'old-request-B', focus_target: 'content' },
	});
	assert.equal(state.chat.processing, true);
	assert.equal(state.chat.requestId, 'new-request-B');
	assert.equal(state.view.pendingFocus, undefined);
});

test('a completed newer request still fences older responses', () => {
	const { state, streams } = loadFlow();
	state.chat.requestId = null;
	state.chat.latestRequestId = 'new-request-B';
	streams.endChatStream('end-old-B', {
		conversation_id: 'B', message_id: 'assistant-B', stream_id: 'stream-B',
		metadata: { request_id: 'old-request-B', focus_target: 'content' },
	});
	assert.equal(state.chat.transcript.findById('assistant-B').streaming, true);
	assert.equal(state.view.pendingFocus, undefined);
});

test('matching stream still applies deltas to the current conversation', () => {
	const { state, streams } = loadFlow();
	streams.applyChatStreamDelta('delta-B', {
		conversation_id: 'B', message_id: 'assistant-B', stream_id: 'stream-B', delta: 'current', sequence: 1,
	});
	assert.equal(state.chat.transcript.findById('assistant-B').content[0].text, 'current');
});

test('an unmatched stream abort within B cannot release the active B turn', () => {
	const { state, streams } = loadFlow();
	streams.abortChatStream('abort-old-B', {
		conversation_id: 'B', message_id: 'old-B', stream_id: 'old-stream-B',
	});
	assert.equal(state.chat.processing, true);
});

test('late appended assistant message cannot change the selected chat', () => {
	const { state, history } = loadFlow();
	history.appendChatMessage('append-A', {
		conversation_id: 'A', message: { id: 'assistant-A', role: 'assistant', content: [] },
	});
	assert.equal(state.chat.conversationId, 'B');
	assert.equal(state.chat.transcript.count, 1);
	assert.equal(state.chat.processing, true);
});

for (const summaries of [[], [{ id: 'A' }]]) {
	test(`authoritative open accepts first appended turn with ${summaries.length} summaries`, () => {
		const { state, opening, history } = loadFlow();
		opening.openChat('open-A', { conversation_id: 'A', conversation_summaries: summaries });
		assert.equal(state.chat.conversationId, 'A');
		history.appendChatMessage('append-A', {
			conversation_id: 'A', message: { id: 'user-A', role: 'user', content: [{ type: 'text', text: 'hello' }] },
		});
		assert.equal(state.chat.transcript.findById('user-A').content[0].text, 'hello');
		assert.equal(state.chat.conversationId, 'A');
	});
}
