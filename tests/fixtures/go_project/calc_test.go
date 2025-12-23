package calc

import "testing"

func TestAdd(t *testing.T) {
	result := Add(1, 2)
	if result != 3 {
		t.Errorf("Add(1, 2) = %d; want 3", result)
	}
}

func TestAddNegative(t *testing.T) {
	result := Add(-1, 1)
	if result != 0 {
		t.Errorf("Add(-1, 1) = %d; want 0", result)
	}
}

func TestAddZero(t *testing.T) {
	result := Add(0, 0)
	if result != 0 {
		t.Errorf("Add(0, 0) = %d; want 0", result)
	}
}
