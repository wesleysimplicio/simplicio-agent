---
name: web-interface-design-workflow
description: Use when building or reviewing web interfaces for quality, aesthetics, UX, accessibility, and guideline compliance. Unifies UI creation and UI audit into one class-level workflow.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [frontend, web-design, ui, ux, accessibility, review]
    related_skills: []
---

# Web Interface Design Workflow

## Overview

This is the umbrella skill for web-interface work that combines two sides of the same class:
- **design/build** of distinctive, production-grade interfaces
- **review/audit** of existing UI against explicit guidelines and best practices

A maintainable library should not split these into tiny siblings when the practical user intent is usually: build a better UI, or review one using the same quality bar.

## When to use

Use this skill when the user asks to:
- design or style a page/component
- improve an interface visually
- review a UI for accessibility or UX quality
- audit code against web-interface guidelines
- turn a generic interface into something more distinctive and polished

## Workflow A — build/design

Use this when creating or substantially redesigning the interface.

### Rules
- choose a clear aesthetic direction before coding
- make typography, spacing, palette, and motion feel intentional
- avoid generic AI-looking layouts and overused defaults
- match implementation complexity to the aesthetic direction
- keep the result functional and production-grade, not just decorative

## Workflow B — review/audit

Use this when the user already has UI code and wants critique or compliance review.

### Rules
- inspect actual files, not screenshots alone, when code review is possible
- fetch or consult the governing guideline source when the workflow calls for fresh rules
- report findings with actionable specificity
- treat accessibility, usability, and consistency as first-class issues, not optional polish

## Combined working style

When redesigning an existing screen, do both in sequence:
1. audit what is wrong
2. choose the new design direction
3. implement changes
4. verify the result against the same quality bar

## Common pitfalls

- Treating visual build and guideline review as unrelated domains
- Giving aesthetic advice with no concrete implementation path
- Generating pretty but generic interfaces
- Running an audit with no explicit quality standard
- Ignoring accessibility while optimizing visual flair

## Verification checklist

- [ ] Aesthetic direction is explicit when designing
- [ ] Review criteria are explicit when auditing
- [ ] Findings or output are actionable
- [ ] Accessibility and UX concerns are included
- [ ] Final result improves both appearance and usability
