"""Example app, version 1: counts primes below N by trial division (slow, wasteful)."""
N = 1_000_000


def is_prime(n: int) -> bool:
    if n < 2:
        return False
    d = 2
    while d * d <= n:
        if n % d == 0:
            return False
        d += 1
    return True


print(sum(1 for n in range(N) if is_prime(n)))
