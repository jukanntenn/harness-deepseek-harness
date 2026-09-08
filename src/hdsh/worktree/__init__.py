"""Worktree-local prek hook installation and pairing merge-driver registration.

The submodules separate concerns by concept: ``git`` the Git subprocess
boundary, ``ownership`` the guarded hooks directory and installer lock,
``config`` the worktree-config migration and merge-driver registration, and
``install`` the orchestration behind ``hdsh worktree install``.
"""
