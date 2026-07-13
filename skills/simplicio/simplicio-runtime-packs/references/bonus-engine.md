# Bonus Engine — Over-delivery com momentum (Inércia)

**Módulo:** crates/simplicio-agents/src/bonus_engine.rs (371 linhas)
**Testes:** 9/9 | **Release:** v2.0.0

## Princípio físico: Inércia / Momentum
Após tarefa complexa, o usuário já está engajado. Melhor momento pra oferecer algo a mais.

## Fluxo
1. Tarefa concluída
2. detect() analisa contexto por palavras-chave
3. Gera 1-2 sugestões específicas (max 2 — não sobrecarregar)
4. Oferece: "Quer que eu implemente?"
5. Se sim → executa. Se não → registra e segue.

## 8 categorias de bônus
🤖 Automação · 🔔 Notificação · 📝 Documentação · 🧪 Testes
🔒 Segurança · 📊 Monitoramento · 🔗 Integração · 🛡️ Resiliência

## Padrões detectados por palavra-chave
- backup/restore → 🔔 notificação
- deploy/release/ci → 🛡️ rollback
- api/endpoint → 📊 health check
- script/automat/cron → 📊 logging
- config/setup/install → 📝 README
- test/coverage → 🤖 CI com testes
