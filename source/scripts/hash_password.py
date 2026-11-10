"""Print an Argon2id hash for a password (used to prepare seed data).

Usage:  python source/scripts/hash_password.py
The password is read interactively and is never echoed or stored.
"""
import getpass

from argon2 import PasswordHasher

if __name__ == "__main__":
    password = getpass.getpass("Password: ")
    print(PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4).hash(password))
