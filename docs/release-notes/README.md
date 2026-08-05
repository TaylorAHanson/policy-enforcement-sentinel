# Release notes

One Markdown file per release, named `<version>.md` — `2.0.0.md`, `1.4.0.md`.
Versions sort semantically, so `1.10.0` comes after `1.9.0` rather than before it.

Each file starts with a small YAML front matter block and then the notes:

```markdown
---
version: 2.0.0
date: 2026-08-04
title: Safety-first enforcement
highlight: Nothing in this repository can destroy a resource as shipped.
---

## What changed

...
```

`highlight` is the one line shown in the sidebar's Release Notes badge and at the
top of the release list. Write it for someone who will read nothing else.

## When to add one

Whenever behaviour a user can see changes. That includes anything that changes
what the system will *do* to a resource — a new action tier, a new gate, a
changed default — even when the change is internal, because the whole point of
the safety model is that nobody is surprised by it.

Adding to this directory is enough. The endpoint reads the directory at request
time, and no build step or registry needs updating.
