const { add } = require('../src/index');

test('add returns sum of three numbers', () => {
    expect(add(1, 2, 3)).toBe(6);
});

test('add handles negative numbers', () => {
    expect(add(-1, 1, 0)).toBe(0);
});

test('add handles zero', () => {
    expect(add(0, 0, 0)).toBe(0);
});
