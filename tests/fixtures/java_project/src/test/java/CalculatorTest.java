import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertEquals;

class CalculatorTest {
    @Test
    void testAdd() {
        assertEquals(3, Calculator.add(1, 2));
    }

    @Test
    void testAddNegative() {
        assertEquals(0, Calculator.add(-1, 1));
    }

    @Test
    void testAddZero() {
        assertEquals(0, Calculator.add(0, 0));
    }

    @Test
    void testAddThreeParameters() {
        assertEquals(6, Calculator.add(1, 2, 3));
    }

    @Test
    void testAddThreeParametersNegative() {
        assertEquals(0, Calculator.add(-3, 1, 2));
    }

    @Test
    void testAddThreeParametersZero() {
        assertEquals(0, Calculator.add(0, 0, 0));
    }
}
