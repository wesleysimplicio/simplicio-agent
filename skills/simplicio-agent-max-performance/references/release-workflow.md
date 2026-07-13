# Synchronized Release Workflow

## Quando usar
Após uma sessão com múltiplos PRs em diferentes repositórios do ecossistema Simplicio, criar releases sincronizadas em todos eles.

## Ordem de dependências
1. `simplicio-runtime` (core — sem dependências)
2. `simplicio-mapper` (depende do runtime)
3. `simplicio-dev-cli` (depende do runtime + mapper)
4. `simplicio-prompt` (depende do runtime)
5. `simplicio-sprint` (depende do runtime)
6. `simplicio-loop` (depende do runtime + mapper + dev-cli)
7. `simplicio-agent` (depende do runtime + loop)
8. `hermes-turbo-agent` (depende do runtime)
9. `simplicio-loop-marketing` (independente)
10. `simplicio` (published package, depende do runtime)

## Fluxo
```bash
cd ~/Projetos/ai/<repo>
git tag v<version>
git push origin v<version>
gh release create v<version> --target main --title "<name>" --notes "Release notes..."
```

## Release notes
- Incluir número de todos os PRs desta release
- Referenciar versão mínima das dependências (`runtime >=1.6.4`)
- Mencionar issues resolvidas

## Matriz de dependências
Salvar em `.simplicio/proof/SIMPLICIO-RELEASE-MATRIX.md` e copiar para `docs/onboarding/` no simplicio-agent.
