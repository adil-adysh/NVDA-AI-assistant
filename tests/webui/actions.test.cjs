const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const ts = require(path.join(root, 'nvda_ui_host/node_modules/typescript'));

// Execute production action code, replacing only browser/host and reactive-state boundaries.
function loadActions(sent = false) {
	const state = {
		currentCommandId: 'command',
		view: { pendingFocus: 'composer' },
		control: { selectedProvider: 'old', providerDraft: 'new', selectedModel: 'model', modelDraft: 'draft', thinkEnabled: false, thinkDraft: true, pendingChange: null },
		chat: { conversationId: 'old-chat', composerText: 'hello', attachments: [], processing: false },
	};
	const events = [];
	const status = [];
	const modules = {
		'./attachments': { clearPendingAttachments: () => { state.chat.attachments = []; } },
		'./commands/_events': { emitUiEvent: (...args) => { events.push(args); return sent; } },
		'./commands/_shared': { invalidatePresentationFocus: () => { state.view.pendingFocus = null; } },
		'./content': { getCurrentCopyText: () => 'copy me' },
		'./operations/view-ops': { setActiveConversationId: id => { state.chat.conversationId = id; } },
		'./state.svelte': { appState: state, setControlPending: value => { state.control.pendingChange = value; }, setStatus: value => status.push(value), t: (_key, value) => value },
	};
	const exports = {};
	const context = { exports, require: name => modules[name], console, navigator: {}, document: {}, crypto: { randomUUID: () => 'request-1' } };
	const source = fs.readFileSync(path.join(root, 'nvda_ui_host/webui/src/lib/actions.ts'), 'utf8');
	vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, context);
	return { actions: exports, state, events, status, context };
}

for (const [action, value] of [['submitProviderSelection', 'new'], ['submitModelSelection', 'other'], ['submitThinkModeToggle', true]]) {
	test(`${action}: failed send keeps controls usable`, () => {
		const { actions, state, status } = loadActions();
		actions[action](value);
		assert.equal(state.control.pendingChange, null);
		assert.match(status.at(-1), /failed|unavailable/i);
	});
	test(`${action}: successful send waits for host acknowledgement`, () => {
		const { actions, state, events } = loadActions(true);
		actions[action](value);
		assert.ok(state.control.pendingChange);
		assert.equal(events.length, 1);
	});
}

test('failed conversation send preserves the displayed selection', () => {
	const { actions, state } = loadActions();
	actions.openConversation('new-chat');
	assert.equal(state.chat.conversationId, 'old-chat');
});

test('fallback clipboard restores keyboard focus', async () => {
	const { actions, context } = loadActions();
	let focused = false;
	const previous = { isConnected: true, focus: () => { focused = true; } };
	context.document = {
		activeElement: previous,
		createElement: () => ({ style: {}, setAttribute() {}, focus() {}, select() {} }),
		body: { appendChild() {}, removeChild() {} },
		execCommand: () => true,
	};
	await actions.copyCurrentText();
	assert.equal(focused, true);
});

test('chat submit assigns a cancellation identity only after a successful send', () => {
	const { actions, state, events } = loadActions(true);
	state.control.chatEnabled = true;
	actions.submitChatMessage();
	assert.equal(state.chat.requestId, 'request-1');
	assert.equal(events[0][2].request_id, 'request-1');
});

test('Stop requests cancellation once and preserves the in-flight chat', () => {
	const { actions, state, events } = loadActions(true);
	state.chat.processing = true;
	state.chat.requestId = 'active';
	actions.stopChatResponse();
	actions.stopChatResponse();
	assert.equal(events.length, 1);
	assert.equal(events[0][2].action_id, 'chat_stop');
	assert.equal(events[0][2].payload.request_id, 'active');
	assert.equal(state.chat.processing, true);
	assert.equal(state.chat.stopping, true);
	assert.equal(state.chat.conversationId, 'old-chat');
});

test('failed Stop send permits retry', () => {
	const { actions, state } = loadActions();
	state.chat.processing = true;
	state.chat.requestId = 'active';
	actions.stopChatResponse();
	assert.equal(Boolean(state.chat.stopping), false);
});

test('Escape hide sends no cancellation event', () => {
	const { actions, events } = loadActions(true);
	actions.requestCloseHost();
	assert.equal(events.length, 1);
	assert.equal(events[0][0], 'close_host');
});
