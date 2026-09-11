import fs from 'node:fs';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const {parse} = require('acorn');
const source = fs.readFileSync('static/app.js', 'utf8');
const ast = parse(source, {ecmaVersion: 'latest', sourceType: 'script', allowHashBang: true});

const assignments = [];
const calls = [];

function isWindowSetPage(member) {
  return member?.type === 'MemberExpression'
    && !member.computed
    && member.object?.type === 'Identifier'
    && member.object.name === 'window'
    && member.property?.type === 'Identifier'
    && member.property.name === 'setPage';
}

function isSetPageCall(node) {
  if (node?.type !== 'CallExpression') return false;
  if (node.callee?.type === 'Identifier' && node.callee.name === 'setPage') return true;
  return isWindowSetPage(node.callee);
}

function isFunctionNode(node) {
  return node?.type === 'FunctionExpression'
    || node?.type === 'FunctionDeclaration'
    || node?.type === 'ArrowFunctionExpression';
}

function directIife(functionNode, parent) {
  return !!parent && parent.type === 'CallExpression' && parent.callee === functionNode;
}

function walk(node, ancestors = []) {
  if (!node || typeof node !== 'object') return;
  if (node.type === 'AssignmentExpression' && isWindowSetPage(node.left)) {
    assignments.push({node, ancestors: [...ancestors], text: source.slice(node.start, node.end)});
  }
  if (isSetPageCall(node)) {
    const enclosingFunctions = ancestors.filter(isFunctionNode);
    let immediate = true;
    for (const fn of enclosingFunctions) {
      const index = ancestors.indexOf(fn);
      const parent = index > 0 ? ancestors[index - 1] : null;
      if (!directIife(fn, parent)) {
        immediate = false;
        break;
      }
    }
    calls.push({node, immediate, ancestors: [...ancestors], text: source.slice(node.start, Math.min(node.end, node.start + 180))});
  }
  const next = [...ancestors, node];
  for (const [key, value] of Object.entries(node)) {
    if (key === 'start' || key === 'end' || key === 'loc') continue;
    if (Array.isArray(value)) {
      for (const child of value) if (child?.type) walk(child, next);
    } else if (value?.type) {
      walk(value, next);
    }
  }
}

walk(ast);
assignments.sort((a, b) => a.node.start - b.node.start);
calls.sort((a, b) => a.node.start - b.node.start);

function compact(text) {
  return text.replace(/\s+/g, ' ').trim();
}

function classify(item) {
  const t = compact(item.text);
  if (t.includes('saveUiState()') && t.includes('state.page=p')) return 'v34-persist';
  if (t.includes("state.page=p==='自动标注'?'自动标注及清洗':p") && t.includes('render()')) return 'v427-alias';
  if (/^window\.setPage=function\(p\)\{state\.page=p;render\(\)\}$/.test(t)) return 'plain-direct';
  if (t.includes('toggleMobileSidebarV37') && t.includes('baseSetPage417')) return 'v417-sidebar';
  if (t.startsWith('window.setPage=async function(page)') && t.includes('setPageReady414')) return 'v414-readiness';
  return 'other';
}

for (const item of assignments) item.label = classify(item);
const persist = assignments.filter(x => x.label === 'v34-persist');
const plain = assignments.filter(x => x.label === 'plain-direct');
const alias = assignments.filter(x => x.label === 'v427-alias');
const sidebar = assignments.filter(x => x.label === 'v417-sidebar');
const readiness = assignments.filter(x => x.label === 'v414-readiness');

function requireCount(label, items, count) {
  if (items.length !== count) throw new Error(`${label}: expected ${count}, found ${items.length}`);
}
requireCount('v34 persist direct owner', persist, 1);
requireCount('plain direct owners', plain, 2);
requireCount('v42.7 alias owner', alias, 1);
requireCount('v41.7 sidebar wrapper', sidebar, 1);
requireCount('v42.14 readiness wrapper', readiness, 1);

const candidates = [persist[0], ...plain, alias[0]].sort((a, b) => a.node.start - b.node.start);
const labels = candidates.map(x => x.label);
if (labels.join('|') !== 'v34-persist|plain-direct|plain-direct|v427-alias') {
  throw new Error(`unexpected direct-owner order: ${labels.join(' -> ')}`);
}

let blocked = false;
for (let i = 0; i < candidates.length - 1; i += 1) {
  const from = candidates[i];
  const to = candidates[i + 1];
  const intervalCalls = calls.filter(call => call.node.start >= from.node.end && call.node.start < to.node.start);
  const immediateCalls = intervalCalls.filter(call => call.immediate);
  console.log(`interval ${i + 1}: ${from.label} -> ${to.label}`);
  console.log(`  all setPage calls: ${intervalCalls.length}`);
  console.log(`  load-time immediate calls: ${immediateCalls.length}`);
  for (const call of immediateCalls) {
    console.log(`  BLOCK @${call.node.start}: ${compact(call.text)}`);
  }
  if (immediateCalls.length) blocked = true;
}

console.log('owner positions:', candidates.map(x => `${x.label}@${x.node.start}`).join(', '));
console.log(`preserved readiness@${readiness[0].node.start}, sidebar@${sidebar[0].node.start}`);
if (blocked) throw new Error('pre-v42.7 direct owner has a load-time setPage call before the next overwrite');
console.log('PASS: no pre-v42.7 direct owner is consumed by a load-time setPage call before the next overwrite.');
