// Run with: node --test tests/test_cookie_notice.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../racetrack/static/cookie-notice.js'), 'utf8');

function page({ stored = new Map(), storageBlocked = false, hasNotice = true } = {}) {
  const writes = [];
  const handlers = {};
  const dismiss = { addEventListener: (event, callback) => { handlers.dismiss = callback; } };
  let focus = null;
  const link = {
    addEventListener: (event, callback) => { handlers.settings = callback; },
    focus: () => { focus = link; },
  };
  const notice = {
    hidden: true, offsetHeight: 180,
    querySelector: () => dismiss,
    addEventListener: (event, callback) => { handlers[event] = callback; },
    focus: () => { focus = notice; },
  };
  const document = {
    querySelector: () => hasNotice ? notice : null,
    querySelectorAll: () => [link],
    body: { classList: { add() {}, remove() {} } },
    documentElement: { style: { setProperty() {} } },
  };
  Object.defineProperty(document, 'cookie', {
    set() { assert.fail('The notice must not write cookies'); },
  });
  const context = {
    document,
    window: { addEventListener() {} },
    sessionStorage: {
      getItem(key) {
        if (storageBlocked) throw new Error('Storage blocked');
        return stored.get(key) || null;
      },
      setItem(key, value) {
        if (storageBlocked) throw new Error('Storage blocked');
        writes.push([key, value]);
        stored.set(key, value);
      },
    },
  };
  Object.defineProperty(context, 'localStorage', {
    get() { assert.fail('The notice must not use persistent local storage'); },
  });
  vm.runInNewContext(source, context);
  return { notice, link, handlers, writes, stored, focused: () => focus };
}

test('first visit shows information without storing anything', () => {
  const current = page();
  assert.equal(current.notice.hidden, false);
  assert.deepEqual(current.writes, []);
});

test('only dismissal writes a tab preference, with no identifier', () => {
  const current = page();
  current.handlers.dismiss();
  assert.equal(current.notice.hidden, true);
  assert.deepEqual(current.writes, [['trackops.cookie-notice.v1', 'dismissed']]);
  assert.equal(page({ stored: current.stored }).notice.hidden, true);
  assert.equal(page().notice.hidden, false);
});

test('blocked storage still allows the notice to be dismissed', () => {
  const current = page({ storageBlocked: true });
  assert.equal(current.notice.hidden, false);
  current.handlers.dismiss();
  assert.equal(current.notice.hidden, true);
  assert.deepEqual(current.writes, []);
});

test('footer control reopens the notice and Escape restores focus', () => {
  const current = page({ stored: new Map([['trackops.cookie-notice.v1', 'dismissed']]) });
  let prevented = false;
  current.handlers.settings({ preventDefault: () => { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(current.notice.hidden, false);
  assert.equal(current.focused(), current.notice);
  current.handlers.keydown({ key: 'Escape' });
  assert.equal(current.notice.hidden, true);
  assert.equal(current.focused(), current.link);
});

test('pages without a notice do not access storage', () => {
  const current = page({ hasNotice: false, storageBlocked: true });
  assert.deepEqual(current.writes, []);
});
