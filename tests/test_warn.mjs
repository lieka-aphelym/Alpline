// Node runner for viewer/test/cases.js:   node tests/test_warn.mjs
import { runAll } from '../viewer/test/cases.js';
const { failed } = await runAll();
process.exit(failed.length ? 1 : 0);
