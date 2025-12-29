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
}
