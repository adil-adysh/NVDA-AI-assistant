const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../../nvda_ui_host/node_modules/typescript');

function loadFocusHelpers() {
	const exports = {};
	const ticks = [];
	const events = [];
	const state = { view: { pendingFocus: 'composer' } };
	const source = fs.readFileSync(path.join(__dirname, '../../nvda_ui_host/webui/src/lib/commands/_shared.ts'), 'utf8');
	vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
		exports, require: name => name === 'svelte' ? { tick: () => new Promise(resolve => ticks.push(resolve)) }
			: name === '../state.svelte' ? { appState: state }
			: name === './_events' ? { emitUiEvent: (...args) => events.push(args) } : {},
	});
	return { ...exports, ticks, events, state };
}

test('applied acknowledgement waits for DOM and focus flushes', async () => {
	const helpers = loadFocusHelpers();
	const pending = helpers.reportUiApplied('command-1');
	assert.equal(helpers.events.length, 0);
	helpers.ticks.shift()();
	await new Promise(resolve => setImmediate(resolve));
	assert.equal(helpers.events.length, 0);
	helpers.ticks.shift()();
	await pending;
	assert.equal(helpers.events[0][0], 'ui_applied');
	assert.equal(helpers.events[0][1], 'command-1');
});

test('dismissal cancels queued DOM focus', async () => {
	const helpers = loadFocusHelpers();
	let focused = false;
	const pending = helpers.focusPresentationElement({ isConnected: true, focus: () => { focused = true; } });
	helpers.invalidatePresentationFocus();
	helpers.ticks.shift()();
	await pending;
	assert.equal(focused, false);
	assert.equal(helpers.state.view.pendingFocus, null);
});

test('detached targets never receive delayed focus', async () => {
	const helpers = loadFocusHelpers();
	let focused = false;
	const pending = helpers.focusPresentationElement({ isConnected: false, focus: () => { focused = true; } });
	helpers.ticks.shift()();
	await pending;
	assert.equal(focused, false);
});

test('the latest connected presentation target receives focus', async () => {
	const helpers = loadFocusHelpers();
	const focused = [];
	const old = helpers.focusPresentationElement({ isConnected: true, focus: () => focused.push('old') });
	const latest = helpers.focusPresentationElement({ isConnected: true, focus: () => focused.push('latest') });
	helpers.ticks.shift()(); helpers.ticks.shift()();
	await Promise.all([old, latest]);
	assert.deepEqual(focused, ['latest']);
});

test('progress updates preserve the chat and do not request focus', () => {
	const exports = {};
	const state = { view: { mode: 'chat', pendingFocus: null } };
	let status;
	const stateModule = {
		appState: state, setStatus: text => { status = text; },
		showDisplayText: () => { state.view.mode = 'display'; state.view.pendingFocus = 'status'; },
	};
	const source = fs.readFileSync(path.join(__dirname, '../../nvda_ui_host/webui/src/lib/commands/error-progress-close.ts'), 'utf8');
	vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
		exports, require: name => name === '../state.svelte' ? stateModule : {
			getHostStatusMessage: () => '', applyPresentationState() {}, reportUiApplied() {},
		},
	});
	exports.updateProgress('progress', { message: 'Working' });
	assert.equal(status, 'Working');
	assert.equal(state.view.mode, 'chat');
	assert.equal(state.view.pendingFocus, null);
});
