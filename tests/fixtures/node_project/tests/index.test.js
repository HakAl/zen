const { add } = require('../src/index');

test('add returns sum of two numbers', () => {
    expect(add(1, 2)).toBe(3);
});

test('add handles negative numbers', () => {
    expect(add(-1, 1)).toBe(0);
});

test('add handles zero', () => {
    expect(add(0, 0)).toBe(0);
});
