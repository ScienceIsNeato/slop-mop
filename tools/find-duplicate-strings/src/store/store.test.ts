import { deepEqual, throws } from 'node:assert';
import { beforeEach, suite, test } from 'node:test';
import { store } from './store.js';

const dummy = { key: 'someStringMatch', count: 0, files: [] };

suite('store', () => {
  beforeEach(() => {
    store.clear();
  });

  test('should add a value', () => {
    store.add('dummy1', dummy);

    deepEqual(store.getAll(), [dummy]);
  });

  test('should add two values', () => {
    store.add('dummy1', dummy);
    store.add('dummy2', dummy);

    deepEqual(store.getAll(), [dummy, dummy]);
  });

  test('should find value by key', () => {
    store.add('dummy1', { ...dummy, key: 'foo' });
    store.add('dummy2', dummy);

    deepEqual(store.find('dummy2'), dummy);
  });

  test('should return null when the key is not found', () => {
    deepEqual(store.find('dummy2'), null);
  });

  test('should throw an error when adding a key that already exists', () => {
    store.add('dummy1', dummy);

    throws(() => store.add('dummy1', dummy), new Error('Key dummy1 already exists'));
  });
});
