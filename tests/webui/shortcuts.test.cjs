const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../../nvda_ui_host/node_modules/typescript');

function loadShortcuts() {
	const exports = {};
	const handlers = new Map();
	const window = {
		addEventListener: (name, value) => { handlers.set(name, value); },
		removeEventListener: name => handlers.delete(name),
	};
	const context = {
		exports,
		require: name => name === './state.svelte' ? { appState: { view: { mode: 'chat' }, display: { toolbarActions: [] } } } : {},
		window,
	};
	const source = fs.readFileSync(path.join(__dirname, '../../nvda_ui_host/webui/src/lib/shortcuts.ts'), 'utf8');
	vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, context);
	return { register: exports.registerGlobalShortcuts, window,
		fire: (event, name = 'keydown') => handlers.get(name)?.({ preventDefault() {}, ...event }) };
}

test('keyboard submission resolves the current file input after chat mounts', () => {
	const { register, fire } = loadShortcuts();
	let current = null;
	let received;
	register({ onSubmit: input => { received = input; } }, () => current);
	current = { value: 'selected image' };
	fire({ key: 's', altKey: true });
	assert.equal(received, current);
});

test('handled or composing keyboard events do not trigger global actions', () => {
	const { register, fire } = loadShortcuts();
	let closes = 0;
	register({ onClose: () => { closes++; } }, null);
	fire({ key: 'Escape', defaultPrevented: true });
	fire({ key: 'Escape', isComposing: true });
	assert.equal(closes, 0);
});

test('native Escape fallback respects active IME composition', () => {
	const { register, fire, window } = loadShortcuts();
	let closes = 0;
	register({ onClose: () => { closes++; } }, null);
	fire({}, 'compositionstart');
	assert.equal(window.__dismissHostOnEscape(), false);
	assert.equal(closes, 0);
});

test('expanded select consumes Escape across duplicate native and DOM paths', () => {
	const { register, fire, window } = loadShortcuts();
	let closes = 0;
	register({ onClose: () => { closes++; } }, null);
	const select = { tagName: 'SELECT' };
	fire({ target: select }, 'pointerdown');
	fire({ key: 'Escape', target: select });
	assert.equal(window.__dismissHostOnEscape(), false);
	assert.equal(closes, 0);
	fire({ key: 'Escape' }, 'keyup');
	fire({ key: 'Escape', target: select });
	assert.equal(closes, 1);
});

test('ordinary Escape dismisses once across native and DOM paths', () => {
	const { register, fire, window } = loadShortcuts();
	let closes = 0;
	register({ onClose: () => { closes++; } }, null);
	assert.equal(window.__dismissHostOnEscape(), true);
	fire({ key: 'Escape' });
	assert.equal(closes, 1);
});

test('shortcut cleanup removes native Escape callback', () => {
	const { register, window } = loadShortcuts();
	const cleanup = register({ onClose() {} }, null);
	cleanup();
	assert.equal(window.__dismissHostOnEscape, undefined);
});
