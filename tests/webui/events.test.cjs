const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('../../nvda_ui_host/node_modules/typescript');

function emitter(bridge) {
	const exports = {};
	const source = fs.readFileSync(require('node:path').join(__dirname, '../../nvda_ui_host/webui/src/lib/commands/_events.ts'), 'utf8');
	vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
		exports, window: { __sendHostEvent: bridge }, crypto: { randomUUID: () => 'id' },
		console: { warn() {}, error() {} },
	});
	return exports.emitUiEvent;
}

test('bridge exceptions are reported as failed sends', () => {
	assert.equal(emitter(() => { throw new Error('disconnected'); })('model_selected', 'command'), false);
});

test('unavailable bridge is a failed send', () => {
	assert.equal(emitter(undefined)('model_selected', 'command'), false);
});

test('successful event preserves the protocol envelope', () => {
	let received;
	assert.equal(emitter(value => { received = value; return true; })('model_selected', 'command', { model: 'model' }), true);
	assert.equal(received.schema, 'nvda.ui_host');
	assert.equal(received.version, 2);
	assert.equal(received.correlation_id, 'command');
	assert.equal(received.event.payload.model, 'model');
});
