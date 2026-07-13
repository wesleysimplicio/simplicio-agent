#!/bin/bash
# Close old Autopilot v5 issues
echo "Closing Autopilot v5 issues (already implemented in PR #1846)..."
for issue in 1847 1848 1849 1850 1851 1852 1853 1854 1855 1856 1857 1858 1859 1860 1861 1862 1863; do
  gh issue close "$issue" -c "Already implemented in PR #1846 and related PRs." --repo wesleysimplicio/simplicio-runtime
done

# Delete test issues
gh issue close 1864 -c "Test" --repo wesleysimplicio/simplicio-runtime
gh issue close 1865 -c "Test" --repo wesleysimplicio/simplicio-runtime

echo "All issues done!"

# Create new feature issues for Agentic Chat
echo "Creating Agentic Chat issues..."

cat > /tmp/issue1.md << 'ISSUE1'
**Objetivo:** Adicionar tool use ao comando `simplicio chat` existente, transformando o loop de conversa em um agente que pode executar ferramentas do runtime.

**Mudanças necessarias:**
- Tool binding no loop do chat (shell, edit, run, memory-db)
- Ciclo agente: recebe mensagem -> orienta -> usa tool -> responde
- Substituir o chat existente mantendo compatibilidade
- O motor agente fica implicito (sem nome Isa em comandos)
ISSUE1

gh issue create --repo wesleysimplicio/simplicio-runtime --title "Runtime Agentic Chat tool use no loop de conversa" --body "$(cat /tmp/issue1.md)"

cat > /tmp/issue2.md << 'ISSUE2'
**Objetivo:** Adicionar modo REPL interativo e roteamento multiplataforma ao `simplicio chat`.

**Mudancas:**
- Modo REPL: `simplicio chat --repl`
- Listener Discord: resposta no mesmo canal
- Listener Telegram: resposta no mesmo canal
- Roteamento automatico: detecta origem, responde no mesmo lugar
ISSUE2

gh issue create --repo wesleysimplicio/simplicio-runtime --title "Runtime Agentic Chat REPL mode e roteamento multiplataforma" --body "$(cat /tmp/issue2.md)"

cat > /tmp/issue3.md << 'ISSUE3'
**Objetivo:** Implementar delegacao de subagentes no runtime, permitindo que o chat dispare tarefas isoladas.

**Mudancas:**
- `simplicio agents delegate` melhorado com isolamento de contexto
- Subagente com tools proprias
- Resultado retornado como resumo
- Paralelismo de ate 3 subagentes
ISSUE3

gh issue create --repo wesleysimplicio/simplicio-runtime --title "Runtime Agentic Chat subagent delegation" --body "$(cat /tmp/issue3.md)"

echo "Feature issues created!"
