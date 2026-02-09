import { deepEqual, equal } from 'node:assert';
import { beforeEach, mock, suite, test } from 'node:test';

const mockExistsSync = mock.fn(() => false);
const mockWrite = mock.fn();
const mockCreateWriteStream = mock.fn(() => ({ write: mockWrite }));

mock.module('node:fs', {
  namedExports: {
    existsSync: mockExistsSync,
    createWriteStream: mockCreateWriteStream,
  },
});

const { resolve } = await import('node:path');
const { Output } = await import('./output.js');
const { findings, manyFindings } = await import('./mocks/output.mocks.js');

// let expectedOutput = JSON.stringify(
// 	findings.sort((a, b) => b.count - a.count),
// 	null,
// 	2,
// );

// expectedOutput = expectedOutput.substring(4, expectedOutput.length - 4);

suite('Output', () => {
  beforeEach(() => {
    mockExistsSync.mock.resetCalls();
    mockCreateWriteStream.mock.resetCalls();
  });

  test('should write with the expected content', async () => {
    const output = new Output(findings);

    output.output();

    equal(mockWrite.mock.calls.at(0)?.arguments.at(0), '[');
    equal(
      mockWrite.mock.calls.at(1)?.arguments.at(0),
      '{\n  "key": "foo",\n  "count": 2,\n  "fileCount": 1,\n  "files": [\n    "dummy/path/2"\n  ]\n}'
    );
    equal(mockWrite.mock.calls.at(2)?.arguments.at(0), ',');
    equal(
      mockWrite.mock.calls.at(3)?.arguments.at(0),
      '{\n  "key": "foo",\n  "count": 1,\n  "fileCount": 1,\n  "files": [\n    "dummy/path/1"\n  ]\n}'
    );
    equal(mockWrite.mock.calls.at(4)?.arguments.at(0), ']');
  });

  test('should write with a custom file name', async () => {
    const output = new Output(findings, 'foo-bar');

    output.output();

    equal(
      mockCreateWriteStream.mock.calls.at(0)?.arguments.at(0),
      resolve(process.cwd(), 'foo-bar.json')
    );
  });

  test('should update the output name if it already exists', async () => {
    const output = new Output(findings);

    mockExistsSync.mock.mockImplementation(() => false);

    output.output();

    equal(
      mockCreateWriteStream.mock.calls.at(0)?.arguments.at(0),
      resolve(process.cwd(), 'fds-output.json')
    );

    mockExistsSync.mock.resetCalls();
    mockExistsSync.mock.mockImplementationOnce(() => true, 0);

    output.output();

    equal(
      mockCreateWriteStream.mock.calls.at(1)?.arguments.at(0),
      resolve(process.cwd(), 'fds-output-1.json')
    );

    mockExistsSync.mock.resetCalls();
    mockExistsSync.mock.mockImplementationOnce(() => true, 0);

    output.output();

    equal(
      mockCreateWriteStream.mock.calls.at(2)?.arguments.at(0),
      resolve(process.cwd(), 'fds-output-2.json')
    );

    mockExistsSync.mock.resetCalls();
    mockExistsSync.mock.mockImplementationOnce(() => true, 0);

    output.output();

    equal(
      mockCreateWriteStream.mock.calls.at(3)?.arguments.at(0),
      resolve(process.cwd(), 'fds-output-3.json')
    );

    equal(mockCreateWriteStream.mock.callCount(), 4);
  });
});
