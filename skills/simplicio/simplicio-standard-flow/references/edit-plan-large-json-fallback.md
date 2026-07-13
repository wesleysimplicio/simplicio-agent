# Fallback verificado para `simplicio edit` com plano grande

Contexto durável: em uma sessão de evolução do `self-observe`, `simplicio edit --plan` falhou com:

- `invalid edit plan JSON: invalid unicode codepoint in JSON string`

Isso aconteceu ao tentar aplicar um plano grande em `src/agent_state_command.rs`.

## Lição operacional
Não transformar isso em crença permanente de que `simplicio edit` está quebrado.

A resposta correta é:
1. tentar `simplicio edit` primeiro;
2. se o parser JSON falhar em plano grande, usar fallback mínimo e verificável;
3. manter validação real após a mutação;
4. registrar como gap do runtime para correção posterior.

## Fallback recomendado
- preferir mutação cirúrgica por bloco exato;
- usar `patch` quando a troca for localizada;
- usar `write_file` apenas quando necessário e com escopo controlado;
- depois rodar testes focados e smoke do comando real.

## Heurística
- erro estrutural/schema do plano -> continuar insistindo em `simplicio edit`, guiado pelo erro
- erro de encoding/Unicode no JSON do plano grande -> fallback verificado + abrir espaço para melhoria do runtime

## Exemplo de evidência útil depois do fallback
- `cargo test <filtro>`
- `cargo run --quiet -- <subcomando real>`
- `simplicio validate "<task>" --repo <repo>`

## Meta
Voltar depois para reduzir ou eliminar esse fallback no runtime, em vez de normalizar edição manual como padrão.