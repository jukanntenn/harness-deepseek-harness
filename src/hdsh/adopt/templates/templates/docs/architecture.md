# __HDSH_REPOSITORY_NAME__ architecture

English | [中文](architecture.zh.md)

Read this before changing the source tree. It is the ordered map of the codebase — components, their boundaries, and where new behavior goes; decision rationale lives in the linked RFCs.

## What this package is

TODO(adopt): Describe in two or three sentences what this repository ships and who consumes it.

## Components

TODO(adopt): Map every top-level component: one table row per component with its responsibility and its public surface (CLI subcommand, API, or hook id). Keep one name for one concept across the directory, the interface, and any id prefix, following the domain-package convention the harness itself uses.

## Where new behavior goes

TODO(adopt): For each common kind of change, name the file or module it belongs in, so contributors do not have to rediscover the layout. Link the owning reference documents — the [documentation standard](AGENTS.md), the [bilingual documentation contract](i18n/README.md), and the [RFC rules](../.agents/rfcs/README.md).

The contributor entry points are in [development.md](development.md).
