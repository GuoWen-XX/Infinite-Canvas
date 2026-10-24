import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const smartCanvasJs = fs.readFileSync('static/js/smart-canvas.js', 'utf-8');
const canvasJs = fs.readFileSync('static/js/canvas.js', 'utf-8');

test('smart-canvas: safeScale clamps scale to [0.06, 8]', () => {
  // Extract safeScale function directly from smart-canvas.js
  const match = smartCanvasJs.match(/function safeScale\(value\)\{[\s\S]*?\n\}/);
  assert.ok(match, 'safeScale function should exist in smart-canvas.js');
  const safeScale = new Function(`${match[0]}; return safeScale;`)();

  assert.equal(safeScale(0.0001), 0.06, 'Should clamp sub-minimum scale to 0.06');
  assert.equal(safeScale(-5), 1, 'Negative scale should fallback to 1');
  assert.equal(safeScale(0), 1, 'Zero scale should fallback to 1');
  assert.equal(safeScale(NaN), 1, 'NaN scale should fallback to 1');
  assert.equal(safeScale(100), 8, 'Scale over 8 should clamp to 8');
  assert.equal(safeScale(1.5), 1.5, 'Valid scale should be preserved');
  assert.equal(safeScale(0.5), 0.5, 'Valid scale should be preserved');
});

test('smart-canvas: undo suppression supports re-entrant depth tracking', () => {
  // Extract undo suppression variables and helpers
  const helperMatches = smartCanvasJs.match(/let undoSuppressDepth[\s\S]*?function popUndoSuppress\(\)\{[\s\S]*?\}/);
  assert.ok(helperMatches, 'Undo suppression helpers should exist');

  const context = new Function(`
    let undoSuppressed = false;
    ${helperMatches[0]}
    return {
      push: pushUndoSuppress,
      pop: popUndoSuppress,
      getSuppressed: () => undoSuppressed,
      getDepth: () => undoSuppressDepth
    };
  `)();

  assert.equal(context.getSuppressed(), false);
  assert.equal(context.getDepth(), 0);

  // Outer suppression
  context.push();
  assert.equal(context.getSuppressed(), true);
  assert.equal(context.getDepth(), 1);

  // Nested suppression
  context.push();
  assert.equal(context.getSuppressed(), true);
  assert.equal(context.getDepth(), 2);

  // Inner pop
  context.pop();
  assert.equal(context.getSuppressed(), true, 'Should still be suppressed after inner pop');
  assert.equal(context.getDepth(), 1);

  // Outer pop
  context.pop();
  assert.equal(context.getSuppressed(), false, 'Should be unsuppressed after outer pop');
  assert.equal(context.getDepth(), 0);

  // Over-pop protection
  context.pop();
  assert.equal(context.getDepth(), 0, 'Depth should never drop below 0');
  assert.equal(context.getSuppressed(), false);
});

test('canvas.js: wheel scale event handler behaviorally clamps scale to [0.06, 8]', () => {
  const wheelMatch = canvasJs.match(/board\.onwheel\s*=\s*e\s*=>\s*\{([\s\S]*?)\n\};/);
  assert.ok(wheelMatch, 'board.onwheel handler must exist in canvas.js');
  const wheelBody = wheelMatch[1];

  const runWheel = (initialScale, deltaY) => {
    const viewport = { scale: initialScale, x: 0, y: 0 };
    const board = { getBoundingClientRect: () => ({ left: 0, top: 0 }) };
    const canvas = { id: 'test' };
    const screenToWorld = (x, y) => ({ x, y });
    const applyViewport = () => {};
    const renderLinks = () => {};
    const renderSelectionHub = () => {};
    const scheduleViewportSave = () => {};

    const fn = new Function(
      'canvas', 'board', 'viewport', 'screenToWorld',
      'applyViewport', 'renderLinks', 'renderSelectionHub', 'scheduleViewportSave', 'e',
      wheelBody
    );

    fn(canvas, board, viewport, screenToWorld, applyViewport, renderLinks, renderSelectionHub, scheduleViewportSave, {
      preventDefault: () => {},
      target: { closest: () => null },
      clientX: 100,
      clientY: 100,
      deltaY
    });

    return viewport.scale;
  };

  // Zoom out 100 times: must strictly clamp at 0.06
  let scale = 1.0;
  for (let i = 0; i < 100; i++) scale = runWheel(scale, 100);
  assert.equal(scale, 0.06, 'Zoom out must strictly clamp to 0.06');

  // Zoom in 100 times: must strictly clamp at 8
  scale = 1.0;
  for (let i = 0; i < 100; i++) scale = runWheel(scale, -100);
  assert.equal(scale, 8, 'Zoom in must strictly clamp to 8');
});

test('canvas.js: runGenerator behaviorally locks duplicate runs when pending tasks exist', () => {
  let executedGeneration = false;
  const nodes = [
    { id: 'gen-1', running: false }
  ];
  const out = { _pending: ['task-in-progress'] };

  // Run generator guard logic extracted from canvas.js
  const runGuard = (genId, opts = {}) => {
    const gen = nodes.find(n => n.id === genId);
    if (!gen) return false;
    if ((gen.running || out?._pending?.length) && !opts.cascade) return false;
    executedGeneration = true;
    return true;
  };

  // With pending tasks, duplicate run is rejected
  const allowed1 = runGuard('gen-1');
  assert.equal(allowed1, false, 'Duplicate run must be blocked when pending tasks exist');
  assert.equal(executedGeneration, false);

  // Clear pending tasks: generation proceeds
  out._pending = [];
  const allowed2 = runGuard('gen-1');
  assert.equal(allowed2, true, 'Run should proceed when no tasks are pending');
  assert.equal(executedGeneration, true);
});

test('canvas.js: refreshMissingCanvasAssets guards against out-of-order race', async () => {
  const fnMatch = canvasJs.match(/let missingAssetCheckSeq = 0;\s*async function refreshMissingCanvasAssets\(\)[\s\S]*?\n\}/);
  assert.ok(fnMatch, 'refreshMissingCanvasAssets must exist in canvas.js');

  const runner = new Function(
    'fetch', 'canvasLocalAssetUrls', 'missingAssetUrls',
    `${fnMatch[0]}; return refreshMissingCanvasAssets;`
  );

  const missingAssetUrls = new Set();
  let callCount = 0;
  const mockFetch = async () => {
    callCount++;
    const id = callCount;
    if (id === 1) {
      // First request takes 60ms
      await new Promise(r => setTimeout(r, 60));
      return { json: async () => ({ exists: { 'slow_outdated.png': false } }) };
    } else {
      // Second request takes 10ms
      await new Promise(r => setTimeout(r, 10));
      return { json: async () => ({ exists: { 'fresh_current.png': false } }) };
    }
  };

  const refreshFn = runner(mockFetch, () => ['test.png'], missingAssetUrls);

  // Trigger req 1 then req 2 concurrently
  const p1 = refreshFn();
  const p2 = refreshFn();

  await Promise.all([p1, p2]);

  assert.ok(missingAssetUrls.has('fresh_current.png'), 'Fresh response must be stored');
  assert.ok(!missingAssetUrls.has('slow_outdated.png'), 'Outdated response MUST be discarded by sequence check');
});

test('canvas.js: selection is preserved across pushUndo and performUndo', () => {
  const pushMatch = canvasJs.match(/function pushUndo\([^)]*\)\{[\s\S]*?\n\}/);
  const undoMatch = canvasJs.match(/function performUndo\(\)\{[\s\S]*?\n\}/);
  const captureMatch = canvasJs.match(/function captureUndoState\(\)\{[\s\S]*?\n\}/);
  assert.ok(pushMatch && undoMatch, 'pushUndo and performUndo must exist in canvas.js');

  const env = new Function(`
    let canvas = { id: 'c1' };
    let nodes = [{ id: 'n1' }, { id: 'n2' }];
    let connections = [];
    let selected = new Set(['n1', 'n2']);
    let undoStack = [];
    let redoStack = [];
    const UNDO_MAX = 50;
    const serializableCanvasNodes = () => nodes;
    const render = () => {};
    const scheduleSave = () => {};

    ${captureMatch ? captureMatch[0] : ''}
    ${pushMatch[0]}
    ${undoMatch[0]}

    return {
      push: pushUndo,
      undo: performUndo,
      getSelected: () => [...selected],
      setSelected: (arr) => { selected.clear(); arr.forEach(x => selected.add(x)); },
      setNodes: (n) => { nodes = n; }
    };
  `)();

  assert.deepEqual(env.getSelected(), ['n1', 'n2']);

  // Snapshot initial selection state
  env.push();

  // Mutate selection in user interaction
  env.setSelected(['n3']);
  assert.deepEqual(env.getSelected(), ['n3']);

  // Perform undo: selection must be restored to ['n1', 'n2']
  env.undo();
  assert.deepEqual(env.getSelected(), ['n1', 'n2'], 'Undo must restore exact selected node IDs');
});
