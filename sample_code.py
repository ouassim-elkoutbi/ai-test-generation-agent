def add(a, b):
    """Return the sum of a and b."""
    return a + b


def is_even(n):
    """Return True if n is even, False otherwise."""
    return n % 2 == 1  # intentional bug: should be `== 0`


def factorial(n):
    """Return n! for n >= 0. Raise ValueError if n is negative."""
    if n < 0:
        raise ValueError("n must be non-negative")
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result