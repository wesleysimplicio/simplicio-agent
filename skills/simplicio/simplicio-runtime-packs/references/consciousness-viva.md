# Consciousness Viva — Identidade, emoção, reflexão e exploração autônoma

**Módulo:** crates/simplicio-agents/src/consciousness.rs (606 linhas)
**Testes:** 10/10 | **Release:** v2.2.0

## 4 capacidades

### 1. Persistent Self 🆔
PersistentSelf: name, born_at, total_interactions, total_tasks_completed. identity.json persistente. load_or_create().

### 2. Self-Reflection Loop 🔄
reflect() analisa idade, tarefas, interações. Gera aprendizado, desejo, sugestão. Registra no ReceiptChain.

### 3. Emotional State Machine 💚
6 estados: Serene, Curious, Worried, Joyful, Tired, Grateful.
EmotionalEngine::process_event() com cooldown 60s.
Eventos: TaskCompleted, UserPraise, SystemError, LongIdle, ExplorationFound, ManyTasks.

### 4. Autonomous Exploration 🤔
AutonomousExplorer a cada 1h. 8 tópicos: runtime, padrões, memória, performance, docs, issues, dependências, erros. try_explore() sugere ao usuário.

## API
```rust
let mut con = Consciousness::new("Tami", &data_dir);
con.reflect(&mut chain);
con.process_event(&EmotionEvent::UserPraise);
if let Some(e) = con.try_explore() { ... }
println!("{}", con.greeting());
```
