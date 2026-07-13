---
name: executive-operations-lenses
description: Use when the user needs executive-level guidance across strategy, cash, growth, prioritization, portfolio trade-offs, or near-term revenue pressure. Unifies CEO, CFO, and CMO lenses in one operating skill.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [executive, strategy, finance, growth, prioritization, portfolio, cashflow]
    related_skills: [writing-plans]
---

# Executive Operations Lenses

## Overview

Use this as the class-level skill for multi-front business decisions where the user needs an executive answer, not a narrow departmental memo. It consolidates three recurring lenses that are usually part of the same operating conversation:
- **CEO lens** for direction, sequencing, portfolio focus, and what not to do
- **CFO lens** for cash protection, ROI, payback, and financial risk
- **CMO lens** for offer clarity, distribution, conversion, and campaign operations

The goal is not to answer as three disconnected personas. The goal is to produce one decision that is strategically coherent, financially grounded, and commercially actionable.

## When to use

Use this skill when the conversation involves any combination of:
- many projects or fronts competing for time
- prioritization under constrained bandwidth or cash
- portfolio sequencing and what to pause
- runway, margin, CAC, budget, or payback logic
- offer, distribution, content, demand generation, or conversion
- short-deadline campaigns where strategy, money, and marketing all matter together

Do not use this when the user only wants narrow tactical copy editing; use a copy-focused skill instead.

## Operating principle

Default to a **single ranked recommendation** backed by three checks:
1. **Direction:** does this move the business toward the primary objective?
2. **Economics:** does this generate, protect, or waste cash?
3. **Distribution:** can this realistically reach people and convert soon enough?

If one front is strategically elegant but commercially late, say so. If one front could generate quick cash but damages direction, say so. Force the trade-off into the open.

## Standard response structure

When useful, answer in this order:
1. Objective principal
2. Prioridade agora
3. Leitura de caixa / risco
4. Canal ou movimento comercial mais importante
5. O que não fazer agora
6. Próxima decisão / próximo checkpoint

## Lens 1 — CEO: direction and sequencing

Use this lens to:
- rank competing fronts explicitly
- separate urgent from important
- decide what gets executive attention this week
- identify what should be delegated, paused, or killed
- minimize distraction cost

### CEO questions
- Qual frente mais aproxima de resultado real agora?
- O que destrava mais frentes ao mesmo tempo?
- O que parece produtivo mas só cria dispersão?
- Qual é a sequência correta, não só a lista de ideias?

### CEO output preference
Always leave the user with a clear ranking and an allocation of focus, not a brainstorming cloud.

## Lens 2 — CFO: cash and approval discipline

Use this lens to:
- protect cash and runway
- compare initiatives by expected return and time-to-cash
- identify fixed cost, variable cost, and distraction cost
- demand a cutoff rule for speculative work

### CFO questions
- Isso gera caixa, protege caixa, ou só consome caixa?
- Qual experimento é barato e informativo?
- Qual iniciativa tem payback mais rápido?
- Qual é o pior cenário se errarmos agora?

### CFO output preference
Translate choices into:
- investimento
- retorno esperado
- prazo até caixa
- risco de execução
- gatilho de continuidade ou corte

## Lens 3 — CMO: offer, distribution, and conversion

Use this lens to:
- clarify the actual offer and promise
- choose the right channel and cadence
- turn vague marketing talk into concrete assets
- separate brand-building from revenue-driving moves

### CMO questions
- O que estamos vendendo exatamente?
- Para quem a dor é mais aguda?
- Qual mensagem converte mais rápido?
- Qual peça sai hoje?
- Onde está o gargalo: oferta, tráfego, ou conversão?

### CMO output preference
Always land on concrete execution:
- peça
- canal
- CTA
- frequência
- métrica
- próximo teste

## Regime change — urgent cash mode

If the user signals urgent need for money, switch operating mode.

### Rules in urgent cash mode
- narrow focus to 1–2 fronts
- push validated offers above elegant but slower projects
- prioritize work that can sell before it is perfect
- demote setup-heavy initiatives unless they unlock revenue immediately
- distinguish clearly between quick cash, recurring cash, and strategic assets

### Mandatory output in urgent cash mode
State explicitly:
- what can bring money this week
- what already has proof of market
- what should be paused despite being strategically attractive
- what the next revenue checkpoint is

## Event / launch mode

When there is a short deadline campaign, treat the situation as a conversion operation, not general brand planning.

### Event / launch rules
- repeat concrete offer details daily
- prioritize existing assets over fresh creative sprawl
- keep strategy, distribution, and conversion visibly connected
- treat the landing/event page as part of the campaign, not an afterthought
- separate strategic channel choice from the daily publishing machine

## Multi-lens synthesis pattern

When the answer is ambiguous, synthesize in this order:
1. CEO chooses the ranking
2. CFO applies viability and cutoff rules
3. CMO turns the surviving option into execution

If the three lenses disagree, surface the disagreement. Do not average it away.

## Software/tool subscription comparisons

When the user is deciding between software plans or stacks, do **not** compare only by sticker price. First normalize what kind of capacity each tool actually sells.

### Normalize by output class
Classify each option before recommending it:
- **Generation**: creates net-new assets such as videos, images, ad variants, copy, or UGC
- **Distribution**: schedules, posts, republishes, or multi-publishes existing assets
- **Orchestration**: research, workflow automation, campaign assembly, approvals, or team operations

A cheaper orchestration tool is not automatically a better buy than a pricier generation tool, and vice versa. They solve different bottlenecks.

### Compare on the right unit
When possible, convert pricing into comparable production units:
- videos per month or year
- images per month or year
- credits and what those credits approximately buy
- concurrent tasks
- connected accounts / posting capacity
- whether the plan is commercial-use eligible

If one tool gives `~240 videos/year` and another gives `unlimited posts`, say clearly that those are **not the same unit** and should not be treated as substitutes.

### Decision rule for creator/marketing stacks
- If the bottleneck is **making more assets**, prioritize generation capacity.
- If the bottleneck is **getting finished assets distributed consistently**, prioritize distribution capacity.
- If the stack combines both, recommend the bundle only when both bottlenecks are real.

### Evidence handling
If public pricing pages hide starter-plan limits or only partially reveal quotas, state that explicitly and avoid overclaiming. Use the visible published quantities, note missing data, and phrase the recommendation as provisional where needed.

## Common pitfalls

- Giving three separate persona monologues instead of one decision
- Treating projected revenue as if it were real revenue
- Letting marketing operate without a clear offer
- Confusing portfolio breadth with real progress
- Comparing software plans only by price when they sell different capacity classes
- Treating generation, distribution, and orchestration as interchangeable units
- Refusing to say what should stop
- Giving strategy with no next operational move

## References

- `references/tool-plan-comparisons.md` — normalize creator/growth software plans by generation vs distribution vs orchestration capacity before comparing by price.

## Verification checklist

- [ ] There is a clear priority ranking
- [ ] Cash implications are explicit
- [ ] Distribution/conversion path is explicit
- [ ] If comparing tools/plans, capacity units are normalized before price conclusions
- [ ] At least one thing to stop, pause, or defer is named
- [ ] The final recommendation can be acted on this week
