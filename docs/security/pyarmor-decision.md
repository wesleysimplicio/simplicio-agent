# Decisão: PyArmor é Desnecessário

> **Issue:** #75 — [SECURITY] Ofuscar bytecode com PyArmor (AES-256)
> **Status:** Rejeitado — runtime é Rust compilado, não há bytecode Python para ofuscar.

## Contexto

A issue #75 propunha ofuscar o bytecode Python com PyArmor para impedir
engenharia reversa. Isso fazia sentido quando o agente era Python puro.

## Realidade Atual

**O runtime Simplicio é 100% Rust compilado.** Não há bytecode Python para ofuscar.
O que existe é um binário Mach-O/ELF/PE de ~27MB, compilado com LTO e strip.

## Por que PyArmor não se aplica

| Aspecto | Python (antigo) | Rust (atual) |
|---|---|---|
| Formato de distribuicao | Bytecode .pyc + Nuitka | Binario nativo estatico |
| Acesso ao codigo | Strings visiveis no binario Nuitka | Compilado com LTO + strip |
| Protecao contra RE | PyArmor adicionava AES-256 | Rust compilado ~ C++ |
| Performance | PyArmor degrada ~5% | Sem overhead |

## Decisao

**PyArmor nao sera usado.** Motivos:
1. Nao ha o que ofuscar - codigo-fonte e Rust compilado para binario nativo.
2. Protecao por obscuridade nao e seguranca real - ed25519 ja prove criptografia.
3. Custo de manutencao zero - sem dependencia extra no build.

## Camadas de Protecao Reais

1. Ed25519 signing - license keys assinadas; binario verifica mas nao minta.
2. Assinatura de manifest - simplicio-update-manifest.json assinado.
3. Compilacao release - LTO + strip + codegen-units=1.

## Referencias

- simplicio-runtime/src/license.rs - sistema de licenciamento
- scripts/sign-manifest.sh - assinatura de manifest
- simplicio security --json - auditoria de supply chain
