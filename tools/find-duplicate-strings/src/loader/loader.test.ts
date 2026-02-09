import { equal } from 'node:assert';
import { type Mock, afterEach, beforeEach, mock, suite, test } from 'node:test';
import { Loader } from './loader.js';

const mockClearLine: Mock<() => boolean> = mock.fn();
const mockCursorTo: Mock<() => boolean> = mock.fn();
const mockWrite: Mock<() => boolean> = mock.fn();
process.stdout.clearLine = mockClearLine;
process.stdout.cursorTo = mockCursorTo;
process.stdout.write = mockWrite;

mock.timers.enable();

suite('Loader', () => {
  let loader: Loader;

  beforeEach(() => {
    mockClearLine.mock.resetCalls();
    mockCursorTo.mock.resetCalls();
    mockWrite.mock.resetCalls();
  });

  afterEach(() => {
    loader.destroy();
  });

  test('should not log anything when the interval has not occurred yet', () => {
    loader = new Loader(15);

    equal(mockWrite.mock.callCount(), 0);

    mock.timers.tick(5);

    equal(mockWrite.mock.callCount(), 0);
  });

  test('should log one dot for each interval', () => {
    loader = new Loader(15);

    equal(mockWrite.mock.callCount(), 0);

    mock.timers.tick(40);

    equal(mockWrite.mock.callCount(), 2);
  });

  test('should clear the line each time it reaches 10 dots', () => {
    loader = new Loader(15);

    equal(mockWrite.mock.callCount(), 0);

    mock.timers.tick(400);

    equal(mockWrite.mock.callCount(), 24);
    equal(mockClearLine.mock.callCount(), 2);
    equal(mockCursorTo.mock.callCount(), 2);
  });

  test('should clear the interval and remove all listeners when destroyed', () => {
    loader = new Loader(15);

    const mockClearInterval = mock.fn();
    const mockRemoveListeners: Mock<() => typeof process> = mock.fn();
    const mockClearLine = mock.fn();
    global.clearInterval = mockClearInterval;
    process.removeAllListeners = mockRemoveListeners;
    loader['clearLine'] = mockClearLine;

    loader.destroy();

    mock.timers.tick(100);

    equal(mockClearInterval.mock.callCount(), 1);
    equal(mockRemoveListeners.mock.callCount(), 2);
    equal(mockClearLine.mock.callCount(), 1);
  });

  test('should destroy when the process is terminated', () => {
    const processEvents: { [key: string]: () => void } = {};
    process.on = mock.fn((signal: string, cb: () => void) => {
      processEvents[signal] = cb;
      return process;
      // biome-ignore lint: mock
    }) as any;
    process.kill = mock.fn((_pid: number, signal: keyof typeof processEvents): true => {
      processEvents[signal]();
      return true;
    });
    loader = new Loader(15);

    const mockDestroy = mock.fn();
    loader['destroy'] = mockDestroy;

    process.kill(process.pid, 'SIGTERM');

    equal(mockDestroy.mock.callCount(), 1);
  });

  test('should destroy when the user presses CTRL/CMD + C to end the program', () => {
    const processEvents: { [key: string]: NodeJS.ExitListener } = {};
    process.on = mock.fn((event: string, listener: NodeJS.ExitListener) => {
      processEvents[event] = listener;
      return process;
      // biome-ignore lint: mock
    }) as any;
    process.kill = mock.fn((_pid: number, signal: keyof typeof processEvents): true => {
      processEvents[signal](1);
      return true;
    });
    loader = new Loader(15);

    const mockDestroy = mock.fn();
    loader['destroy'] = mockDestroy;

    process.kill(process.pid, 'SIGINT');

    equal(mockDestroy.mock.callCount(), 1);
  });
});
