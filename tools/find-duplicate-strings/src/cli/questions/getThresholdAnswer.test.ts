import { equal } from 'node:assert';
import { mock, suite, test } from 'node:test';

const mockInput = mock.fn(() => '5');
mock.module('@inquirer/prompts', {
  namedExports: {
    input: mockInput,
  },
});

const { getThresholdAnswer } = await import('./getThresholdAnswer.js');

suite('getThresholdAnswer', () => {
  test('should return the answer when it is found', async () => {
    const answer = await getThresholdAnswer();

    equal(answer, '5');
  });
});
