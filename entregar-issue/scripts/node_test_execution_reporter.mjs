/**
 * JSONL companion to Node 24's native JUnit test reporter.
 *
 * Run both reporters in one invocation. This stream records runner facts only;
 * it never asserts a passing invocation, exact-SHA provenance or coverage.
 */
import { isAbsolute } from 'node:path';

const outcomes = new Set(['test:pass', 'test:fail']);

export default async function* nodeTestExecutionReporter(events) {
  if (process.versions.node.split('.')[0] !== '24') {
    throw new Error('Node test execution reporter requires Node 24');
  }
  for await (const { type, data } of events) {
    if (!outcomes.has(type) || data.details?.type !== 'test') continue;

    const { file, entryFile, name } = data;
    const classname = data.classname ?? data.details.classname ?? 'test';
    if (typeof file !== 'string' || !isAbsolute(file) ||
        typeof entryFile !== 'string' || !isAbsolute(entryFile) ||
        typeof name !== 'string' || !name.trim() ||
        typeof classname !== 'string' || !classname.trim()) {
      throw new Error('Node test event has no usable source identity');
    }

    const status = data.skip || data.todo ? 'skipped' :
      type === 'test:pass' ? 'passed' : 'failure';
    yield JSON.stringify({ schema_version: 1, runner: 'node:test', file,
      entry_file: entryFile, classname, name, status }) + '\n';
  }
}

