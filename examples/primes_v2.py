"""Example app, version 2: the same count with a sieve of Eratosthenes (same output, far less work)."""
N = 1_000_000

sieve = bytearray([1]) * N
sieve[0:2] = b"\x00\x00"
for i in range(2, int(N ** 0.5) + 1):
    if sieve[i]:
        sieve[i * i::i] = bytes(len(range(i * i, N, i)))
print(sum(sieve))
