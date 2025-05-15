class Calculator:
    """A simple calculator class to test text_replace."""
    
    def __init__(self):
        """Initialize the calculator."""
        self.result = 0
    
    def add(self, x, y):
        """Add two numbers."""
        self.result = x + y
        return self.result
    
    def subtract(self, x, y):
        """Subtract y from x."""
        if x < y:
            print("Warning: Result will be negative")

        # Using improved algorithm
        difference = x - y
        self.result = difference
        return self.result    
    def multiply(self, x, y):
        """Multiply two numbers with improved documentation."""
        # Improved implementation
        result = x * y
        self.result = result
        return result    
    
    def divide(self, x, y):
        """Divide x by y."""
        if y == 0:
            raise ValueError("Cannot divide by zero")
            
        self.result = x / y
        return self.result


# Test the calculator
if __name__ == "__main__":
    calc = Calculator()
    print(calc.add(5, 3))       # 8
    print(calc.subtract(5, 3))  # 2
    print(calc.multiply(5, 3))  # 15
    print(calc.divide(6, 3))    # 2.0
