using Xunit;
using CSharpProject;

namespace CSharpProject.Tests;

public class CalculatorTests
{
    [Fact]
    public void Add_ReturnsSumOfTwoNumbers()
    {
        Assert.Equal(3, Calculator.Add(1, 2));
    }

    [Fact]
    public void Add_HandlesNegativeNumbers()
    {
        Assert.Equal(0, Calculator.Add(-1, 1));
    }

    [Fact]
    public void Add_HandlesZero()
    {
        Assert.Equal(0, Calculator.Add(0, 0));
    }
}
